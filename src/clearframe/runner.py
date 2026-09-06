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

import logging
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


def already_finished(state) -> bool:
    return all(state.stage_status.get(s) == "complete" for s in ANALYSIS_STAGES)


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

    run_log = EventLog(backends.blobs, pid, flush_every_s=_flush_interval(cfg))
    ctx = build_context(cfg.model_copy(update={"mode": "live"}), state.production, out_root)
    ctx.store = store
    ctx.state = state  # resume from what is persisted, not from a fresh model

    def listen(event: dict) -> None:
        run_log.append(event)
        stage = event.get("stage")
        kind = event.get("type")
        if stage and kind in ("stage_start", "stage_complete"):
            backends.index.record_stage(
                pid, stage, "complete" if kind == "stage_complete" else "running"
            )
            backends.index.heartbeat(pid)

    ctx.listener = listen
    backends.index.heartbeat(pid)
    try:
        await Pipeline(build_demo_pipeline()).run(ctx)
        return "ran"
    finally:
        backends.index.clear_heartbeat(pid)
        run_log.append({"type": "run_complete"})
        run_log.flush()


def _flush_interval(cfg: ClearFrameConfig) -> float:
    """How long progress may be buffered before it is written.

    Zero on a laptop, where a write is a `write()` to the page cache and there
    are tests that pace a whole run in under a second. Non-zero against a bucket,
    where each write is a round trip and forty emit sites — several inside the
    gather that runs three video scans at once — would otherwise spend more time
    reporting than working.
    """
    return 0.5 if cfg.profile == "cloud" else 0.0
