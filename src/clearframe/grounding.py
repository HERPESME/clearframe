"""Measured rectangles, and the shelf both containers can reach.

Grounding answers "where exactly is this element on the frame you paused on".
It exists because the scan's box is a union: Gemini samples video at about 1fps
and returns ONE rectangle per time range — where the subject travelled, not where
it is at any instant. A still has none of that.

It is also slow and it costs money: about eight seconds and a fraction of a cent
per frame. So the run measures every second something is on screen, in the
background, while the expensive stages are waiting on the network — and by the
time a reviewer opens the video the boxes are already there.

**That worked on a laptop and silently did not work in production.** The trigger
lived in `create_production`'s closure, which only runs under
`InProcessJobQueue`; in the deployed topology the pipeline runs in the worker,
whose listener had no such hook. And the caches were in-memory dicts inside
`create_app`, so even with the hook nothing the worker measured could reach the
API that serves `/ground`. Measured on the deployed site: 13.98s cold, 0.19s
warm, and no measurements in the bucket at all.

This module is the half that crosses the boundary. It is modelled on `EventLog`
— the existing precedent for "worker writes, API reads", down to the static
readers so the reading side needs no instance and no shared state — with one
deliberate difference:

**One blob per second, not one per production.** `EventLog` rewrites a single
array because it has one writer appending in order. Grounding has four
measurements in flight at once, and a read-modify-write against one object under
that would lose answers. Per-second objects are written exactly once each, need
no coordination, and are idempotent.

`media_version` is IN the key path rather than in a value. That lesson has been
paid for twice — the browser's video cache, then `_ground_cache` keyed
`(pid, second)` handing the second upload the first film's rectangles marked
`grounded: true`. A re-upload changes the prefix; the old objects are orphaned
and the bucket's 30-day lifecycle rule collects them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from clearframe.media import extract_frame
from clearframe.overlay import bind_ground_boxes
from clearframe.storage.blobs import BlobStore

log = logging.getLogger("clearframe.grounding")

# How many frames may be measured at once. One gate for the whole process: it
# bounds the warm-up and the on-demand path together, which is what stops a
# reviewer dragging the scrubber from queueing dozens of model calls on top of
# a warm-up already in flight.
GROUND_CONCURRENCY = 4

# How often the warm-up publishes its progress. Every frame would be 150 writes
# per run for a number the client reads twice a second; the start and the finish
# are always written, so the poll never misses the transition that matters.
PROGRESS_EVERY = 5


def prefix(pid: str, version: str) -> str:
    """Where one film's measurements live. The version is part of the path."""
    return f"ground/{pid}/{version or 'none'}"


class GroundStore:
    """One film's measured rectangles, in the blob store.

    A value is `{element_id: [ {ymin,xmin,ymax,xmax}, ... ]}` — already plain
    JSON, because `bind_ground_boxes` has run and the boxes are `model_dump`ed
    before they get here.
    """

    def __init__(self, blobs: BlobStore, pid: str, version: str):
        self._blobs = blobs
        self.pid = pid
        self.version = version or ""
        self.prefix = prefix(pid, version)

    def key(self, second: int) -> str:
        # Zero-padded so a listing sorts in time order, which is the only order
        # anyone would ever want to read these in.
        return f"{self.prefix}/{int(second):06d}.json"

    def read(self, second: int) -> dict | None:
        """The boxes measured on this second, or None if nobody has looked.

        **None is not an answer.** `grounded: true` with no boxes is a
        conclusion — nothing is on this frame — and `grounded: false` is a gap.
        A missing blob is a third thing: it means the frame has not been
        measured, so the caller must fall through to measuring it. Returning an
        empty answer here would suppress every box on that frame for ever.
        """
        try:
            raw = self._blobs.get(self.key(second))
        except KeyError:
            return None
        try:
            boxes = json.loads(raw)
        except ValueError:
            log.warning("unreadable measurement at %s", self.key(second))
            return None
        return boxes if isinstance(boxes, dict) else None

    def write(self, second: int, boxes: dict) -> None:
        try:
            self._blobs.put(self.key(second), json.dumps(boxes).encode())
        except Exception:
            # The measurement is already in the caller's memory and already
            # correct. Failing to share it costs another container a round trip,
            # not an answer, and this runs inside an analysis request.
            log.warning("could not store the measurement at %s", self.key(second),
                        exc_info=True)

    @property
    def progress_key(self) -> str:
        return f"{self.prefix}/progress.json"

    def read_progress(self) -> dict | None:
        """How far the warm-up got, or None if none has started.

        None rather than a zeroed dict, because the client distinguishes *not
        started* (total 0) from *finished* (total > 0, running false) and
        latches its poll off on the second. Conflating them is what stopped
        "measuring boxes N/M" appearing on the restore path.
        """
        try:
            raw = self._blobs.get(self.progress_key)
        except KeyError:
            return None
        try:
            body = json.loads(raw)
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def write_progress(self, progress: dict) -> None:
        try:
            self._blobs.put(self.progress_key, json.dumps(progress).encode())
        except Exception:
            log.warning("could not publish warm-up progress for %s", self.pid,
                        exc_info=True)


def elements_at(state, at_s: float) -> list:
    """The findings the analysis says are on screen at this instant.

    Only these are named to the model. Asked to place something that is not in
    the frame it will sometimes oblige, and asking costs a call. A finding whose
    timecodes were disowned has no instant to be at, so it is never named.
    """
    return [
        el
        for el in state.elements
        if el.timing_reliable
        and any(r.start_s <= at_s <= r.end_s for r in el.time_ranges)
    ]


def plan_seconds(state) -> list[int]:
    """Which whole seconds to measure, most useful first.

    Every whole second something is on screen, because a reviewer pauses where
    they pause — not on the midpoint of an appearance. Midpoints first so the
    moments most likely to be jumped to are warm earliest; a clip long enough to
    exceed the cap gets its midpoints regardless.
    """
    midpoints, filler = set(), set()
    for el in state.elements:
        if not el.timing_reliable:
            continue
        for r in el.time_ranges:
            midpoints.add(int((r.start_s + r.end_s) / 2))
            filler.update(range(int(r.start_s), int(r.end_s) + 1))
    return sorted(midpoints) + sorted(filler - midpoints)


def build_client(cfg):
    """The client that locates known labels on a still frame.

    Separate from `build_context` because grounding is not a pipeline stage — it
    answers an interactive question about one moment, long after the run
    finished. Demo mode gets the fixture twin, so the identical parser and the
    identical drawing code run with no credentials and no network.

    Lives here rather than in the webapp because the worker needs one too: it is
    the container that warms the boxes during a run.
    """
    if cfg.mode == "live":
        from clearframe.integrations.gemini_live import LiveGeminiClient

        # The configured model, like every other caller. This used to fall
        # through to the hard-coded default, so grounding ignored
        # CLEARFRAME_GEMINI_MODEL and re-paid the 404-then-fallback round trip
        # on a model the rest of the run had already given up on.
        return LiveGeminiClient(cfg.project, cfg.location, model=cfg.gemini_model)

    from pathlib import Path

    from clearframe.integrations.gemini_client import FixtureGeminiClient

    return FixtureGeminiClient(
        Path(__file__).parent / "integrations" / "fixtures"
    )


async def measure_frame(footage, at_s: float, here: list, client) -> dict | None:
    """Locate this frame's elements, or None if the frame could not be read.

    None is a GAP, not a conclusion — the caller must not turn it into
    `grounded: true`, which would suppress every box on the frame.

    Both the extraction and the model call go to a thread. ffmpeg is a
    subprocess and the SDK call is synchronous; either one inline in a coroutine
    stops the whole service, which is precisely how grounding froze the server
    for eight seconds at a time before.
    """
    frame = await asyncio.to_thread(extract_frame, footage, at_s)
    if frame is None:
        return None
    try:
        located = await client.ground_frame(
            # One entry per distinct label: asking twice about the same words
            # invites the model to answer twice for one object.
            frame, list(dict.fromkeys(el.label for el in here))
        )
    except Exception as exc:  # a refined box is a nicety, never a failure
        log.warning("grounding failed at %.2fs: %s", at_s, exc)
        return None

    # Keyed by element id, and a LIST: the client draws against its own state, a
    # label is not a stable identifier, and one finding can be in two places in
    # the same frame.
    return {
        eid: [b.model_dump() for b in found]
        for eid, found in bind_ground_boxes(here, located, at_s).items()
    }


# `measure(at_s, here)` returns the boxes to store, or **None** meaning "nothing
# to store" — either because the measurement failed, or because the caller has
# already persisted it. The API passes the second kind: its own `_ground_second`
# has to write the blob anyway, since a reviewer pausing on a cold frame must
# leave a measurement behind for everyone else.
Measurer = Callable[[float, list], Awaitable[dict | None]]


async def warm(
    store: GroundStore,
    state,
    measure: Measurer,
    *,
    cap: int,
    concurrency: int = GROUND_CONCURRENCY,
    progress: dict | None = None,
) -> dict:
    """Measure every second something is on screen, and publish the progress.

    `measure(at_s, here)` returns `{element_id: [box, ...]}` or raises. It is
    passed in rather than built here so the caller decides what a measurement
    is: the API already has a memoised client and an in-flight map it wants this
    to go through, and the worker has neither.

    Returns the final progress. Failures are swallowed per frame — a cold second
    still works the old way, just slowly — because on the worker this runs
    inside the analysis request, and an exception here would fail a run that has
    already done everything a user asked for.
    """
    ordered = plan_seconds(state)
    seconds = ordered[:cap]
    # Filled in place when the caller supplied it. The API seeds this dict
    # SYNCHRONOUSLY before the task starts, because the player polls progress
    # from a child effect and React runs child effects before the parent's — so
    # the first GET goes out before the POST that starts the warm-up exists. If
    # progress only appeared once the task got a turn, that poll saw "not
    # running", latched off, and the reviewer watched an eight-second model call
    # with nothing on screen saying it was happening.
    progress = progress if progress is not None else {}
    progress.update({
        "total": len(seconds),
        "done": 0,
        "running": True,
        "skipped": max(0, len(ordered) - len(seconds)),
    })
    if not seconds:
        progress["running"] = False
        return progress

    if progress["skipped"]:
        # Never a silent cap: an unwarmed second still works, it is just slow,
        # and the reviewer should not have to guess which ones.
        log.info(
            "warming %d of %d frame(s) for %s (capped; the rest are measured on "
            "demand)", len(seconds), len(ordered), store.pid,
        )
    store.write_progress(progress)
    gate = asyncio.Semaphore(concurrency)

    async def one(second: int) -> None:
        try:
            # Already in the bucket: another instance, or an earlier run,
            # measured it. Two API instances would otherwise pay Gemini
            # separately for the same frame.
            if store.read(second) is not None:
                return
            at_s = float(second)
            here = elements_at(state, at_s)
            if not here:
                return
            async with gate:
                boxes = await measure(at_s, here)
            if boxes is not None:
                store.write(second, boxes)
        except Exception as exc:
            log.warning("warming %s at %ss failed: %s", store.pid, second, exc)
        finally:
            progress["done"] += 1
            if progress["done"] % PROGRESS_EVERY == 0:
                store.write_progress(progress)

    try:
        await asyncio.gather(*(one(s) for s in seconds), return_exceptions=True)
    finally:
        progress["running"] = False
        store.write_progress(progress)
    log.info("warming complete for %s (%d frame(s))", store.pid, progress["done"])
    return progress
