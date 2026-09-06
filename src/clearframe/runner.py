"""Running one analysis, wherever the running happens.

Both transports come through here — the in-process queue on a laptop and the
worker's HTTP handler in the cloud — so there is one set of rules about claiming
a job, publishing progress and releasing it, rather than two that drift.

The important property is that it takes a **production id, not a context**. A
job has to survive being handed to another container, where a closure cannot go;
and a retried job has to pick up whatever the previous attempt persisted rather
than restarting from a snapshot taken when the job was created. Loading the
state at the start of the run gives both.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path

from clearframe.config import ClearFrameConfig
from clearframe.events import EventLog
from clearframe.pipeline import (
    ANALYSIS_STAGES,
    Pipeline,
    build_context,
    build_demo_pipeline,
)
from clearframe.storage import AnalysisJob, Backends

log = logging.getLogger("clearframe.runner")

# How often a running analysis says it is still there.
#
# The beat used to ride on stage events, which made it a stage counter rather
# than a heartbeat: `scan` emits `scan_found`, `audit_found`, `fingerprint_*`
# and `corroborator_hits`, and not one of them is a `stage_start` or a
# `stage_complete`. So a three-pass scan beat once and then went silent for its
# whole duration — ~1270s on a deployed run, against a 900s staleness window.
# `is_running()` therefore went false on a perfectly healthy run, which told the
# dashboard nothing was happening, cut the Mission Control stream off, and left
# a Cloud Tasks redelivery free to start a second concurrent PAID analysis.
#
# 30s is chosen against the write, not the read: one beat is a single small
# merge into the index, so a 540s run costs eighteen of them.
HEARTBEAT_EVERY_S = 30.0


def already_finished(state) -> bool:
    return all(state.stage_status.get(s) == "complete" for s in ANALYSIS_STAGES)


async def beat(index, pid: str, every_s: float) -> None:
    """Say "still here" until cancelled.

    In a thread because the cloud index is a Firestore round trip, and this
    coroutine shares the worker's event loop with the pipeline it is reporting
    on. A beat that blocked the loop would slow the very thing it is measuring.
    """
    while True:
        await asyncio.sleep(every_s)
        try:
            await asyncio.to_thread(index.heartbeat, pid)
        except Exception:
            # Losing a beat is survivable — the next one is `every_s` away and
            # the staleness window is several beats wide. Failing the analysis
            # over it would not be.
            log.warning("could not record a heartbeat for %s", pid, exc_info=True)


async def run_analysis(
    job: AnalysisJob,
    cfg: ClearFrameConfig,
    out_root: Path,
    backends: Backends,
    store,
) -> str:
    """Claim, run, release. Returns what actually happened.

    Three outcomes, and the first two are why a retry is safe:

    - `already-complete` — every stage is done. A redelivered task is a no-op
      rather than a second full run, which matters because Cloud Tasks is
      at-least-once and a live run costs real money.
    - `already-running` — something else holds the lease. With
      `--concurrency=1` a redelivery lands on a *different instance*, so an
      in-process guard could not see it; the index can.
    - `ran` — this call did the work.

    Resume is free rather than engineered: `Pipeline.run` already skips stages
    marked complete and persists after each one, so a task that died half-way —
    or hit the queue's 30-minute dispatch deadline — continues from where it
    stopped instead of re-paying for the scan.
    """
    pid = job.production_id
    try:
        state = store.load(pid)
    except FileNotFoundError:
        log.warning("no such production to analyse: %s", pid)
        return "unknown"

    if already_finished(state):
        return "already-complete"

    row = backends.index.get(pid)
    if row is not None and row.is_running():
        log.info("%s is already being analysed elsewhere; acking", pid)
        return "already-running"

    # Claim it NOW, before anything slow.
    #
    # The check above and this write are two round trips, and everything that
    # used to sit between them — resolving the footage, then `build_context`
    # constructing four live SDK clients and reading the rights ledger — was
    # time in which a second delivery could take the same lease and start a
    # second paid run. Moving the claim up shrinks that window to the gap
    # between two adjacent statements. It does not close it: only a
    # transactional compare-and-set would, and Firestore can do that if this
    # ever proves insufficient.
    backends.index.heartbeat(pid)

    # Put the footage where THIS container can open it.
    #
    # `footage_uri` is an absolute path written by whichever container took the
    # upload, and in the cloud profile that is the API's own download cache —
    # `/tmp/clearframe-cache/<hash>.mp4`, on a filesystem this process has never
    # seen. The bytes are in the bucket the whole time; what does not travel is
    # the path to them. So the worker resolves the footage through the store and
    # rewrites the uri for the run.
    #
    # A path rather than a `gs://` uri because the consumers disagree: Gemini
    # and Video Intelligence accept `gs://`, but ffmpeg takes an argv and audio
    # fingerprinting refuses a `gs://` outright. One local file satisfies all
    # three.
    state = _with_local_footage(state, pid, backends)

    run_log = EventLog(backends.blobs, pid, flush_every_s=_flush_interval(cfg))
    # `job.owner_uid` has been on the wire since the queue was written and
    # was dropped on the floor here. It selects whose rights ledger the
    # coverage stage reads — the worker has no request to ask.
    #
    # Opened through the backends rather than from `out_root`, because in the
    # cloud profile `out_root` is this container's own tmpfs and the ledger was
    # uploaded to the API's. Reading it from disk here found an empty file every
    # time and reported every finding uncovered, which looks exactly like a
    # production that genuinely holds no licences.
    ctx = build_context(
        cfg.model_copy(update={"mode": "live"}),
        state.production,
        out_root,
        owner_uid=job.owner_uid or "",
        licences=backends.ledger(job.owner_uid or "").load(),
    )
    ctx.store = store
    ctx.state = state  # resume from what is persisted, not from a fresh model

    warming: list[asyncio.Task] = []

    def listen(event: dict) -> None:
        run_log.append(event)
        stage = event.get("stage")
        kind = event.get("type")
        if stage and kind in ("stage_start", "stage_complete"):
            backends.index.record_stage(
                pid, stage, "complete" if kind == "stage_complete" else "running"
            )
            backends.index.heartbeat(pid)
        # Warm the boxes at the EARLIEST moment they are final, which is triage.
        #
        # Triage fixes the element ids, labels, appearances and rectangles;
        # everything after it changes what is KNOWN about a finding, never where
        # or when it is on screen. Warming a 50s clip takes ~100s and the run
        # still has ~370s of corroborate, research and court to go, so it hides
        # entirely inside work that is waiting on the network anyway.
        #
        # This hook existed only in `create_production`'s closure, which runs
        # under `InProcessJobQueue` and nowhere else — so on the deployed site
        # nothing was ever warmed and every pause paid fourteen seconds.
        if kind == "stage_complete" and stage == "triage" and not warming:
            warming.append(asyncio.create_task(_warm_boxes(pid, cfg, backends, store)))

    ctx.listener = listen
    heart = asyncio.create_task(beat(backends.index, pid, HEARTBEAT_EVERY_S))
    try:
        await Pipeline(build_demo_pipeline()).run(ctx)
        return "ran"
    finally:
        # Awaited, not abandoned. Cloud Run throttles CPU to near-zero once a
        # response is sent — the entire reason this container exists — so a task
        # still running when `run_analysis` returns would be frozen mid-warm.
        # That is the original background-task bug, one layer down.
        if warming:
            await asyncio.gather(*warming, return_exceptions=True)
        # Cancel first, and await the cancellation. A beat still in flight when
        # the lease is cleared would put it straight back, and a run that has
        # finished or crashed would then read as live until the window lapsed —
        # which is worse than the bug this replaces, because `is_running()` is
        # the only thing standing between a redelivery and paying twice.
        heart.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heart
        backends.index.clear_heartbeat(pid)
        run_log.append({"type": "run_complete"})
        run_log.flush()


MEDIA_SUFFIXES = (".mp4", ".m4v", ".mov", ".webm")

# How many frames one production may warm. Each is a model round trip on a still
# — about eight seconds and a fraction of a cent — so a feature-length upload
# must not try to measure every second of itself. Same name and same default as
# the API's, because it is the same budget.
PREGROUND_MAX_FRAMES = int(os.environ.get("CLEARFRAME_PREGROUND_MAX", "150"))


async def _warm_boxes(pid: str, cfg: ClearFrameConfig, backends: Backends, store) -> None:
    """Measure every second something is on screen, into the shared store.

    Reloaded from the store rather than closed over: triage has just written it,
    and the whole point is to measure what triage decided rather than what the
    state looked like when the run began.

    Never raises. It runs inside the analysis request, and a warm cache is a
    nicety — failing a run that has already done everything the user asked for,
    because a rectangle could not be measured, would be a poor trade.
    """
    from clearframe import grounding

    try:
        state = await asyncio.to_thread(store.load, pid)
        media_key = _media_key(pid, backends)
        if media_key is None:
            return
        footage = await asyncio.to_thread(backends.blobs.local_path, media_key)
        if footage is None:
            return
        version = await asyncio.to_thread(backends.blobs.version, media_key) or ""
        client = grounding.build_client(cfg)

        async def measure(at_s: float, here: list):
            return await grounding.measure_frame(footage, at_s, here, client)

        await grounding.warm(
            grounding.GroundStore(backends.blobs, pid, version),
            state,
            measure,
            cap=PREGROUND_MAX_FRAMES,
        )
    except Exception:
        log.warning("could not warm the boxes for %s", pid, exc_info=True)


def _media_key(pid: str, backends: Backends) -> str | None:
    for suffix in MEDIA_SUFFIXES:
        key = f"media/{pid}/footage{suffix}"
        if backends.blobs.exists(key):
            return key
    return None


def _with_local_footage(state, pid: str, backends: Backends):
    """Point `footage_uri` at a file this container actually has.

    Returns the state unchanged when there is no footage in the store — a demo
    production, or one the CLI created against a path that really is local. The
    stored uri is only wrong when it was written by a different container, and
    the store is the thing that knows.
    """
    key = _media_key(pid, backends)
    if key is not None:
        local = backends.blobs.local_path(key)
        if local is None:
            return state
        if str(local) == state.production.footage_uri:
            return state
        log.info("resolved footage for %s to %s", pid, local)
        return state.model_copy(
            update={
                "production": state.production.model_copy(
                    update={"footage_uri": str(local)}
                )
            }
        )
    return state


def _flush_interval(cfg: ClearFrameConfig) -> float:
    """How long progress may be buffered before it is written.

    Zero on a laptop, where a write is a `write()` to the page cache and there
    are tests that pace a whole run in under a second. Non-zero against a bucket,
    where each write is a round trip and forty emit sites — several inside the
    gather that runs three video scans at once — would otherwise spend more time
    reporting than working.
    """
    return 0.5 if cfg.profile == "cloud" else 0.0
