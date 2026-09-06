"""Pipeline progress, readable by a process that is not running the pipeline.

Mission Control is driven entirely by an event stream — twenty event types from
forty emit sites, and the payloads carry real content, not just stage names. The
`preview_ready` event holds the whole findings list and is what unlocks "See
findings now" while research is still going. So this cannot be reduced to a
progress percentage without gutting the screen.

Until now the events went into an `asyncio.Queue` in the API process, which is
the right structure exactly as long as the producer and the consumer share an
event loop. Once the pipeline runs in a worker container they do not, and the
queue on the API side stays empty for ever.

Two properties of the old queue are worth not reproducing:

  - It was **single-consumer**. `queue.get()` removes the item, so two browser
    tabs on one run split the events between them rather than each seeing all.
  - It was **destroyed on completion** (`event_queues.pop`), and the endpoint
    404s without it — so a reader who reconnected a second late got nothing at
    all, for ever. A refresh mid-run lost the stream permanently.

A log fixes both by being a log: readers hold their own cursor, and replay from
the top converges because every Mission Control handler is a `patch(key, …)`
setter rather than an increment.

**Why one blob rewritten rather than one blob per event.** A run emits on the
order of a hundred events at a couple of hundred bytes each — twenty kilobytes
all told. One object means no listing, no sequence-number coordination and no
partial reads; the cost is rewriting twenty kilobytes a few times a minute,
which is nothing next to a single Gemini call.
"""

from __future__ import annotations

import json
import logging
import time

from clearframe.storage.blobs import BlobStore

log = logging.getLogger("clearframe.events")

# Events that must reach a reader immediately rather than on the next timer.
# Both are contracts the UI acts on: `stage_complete` advances the agent roster
# and triggers pre-grounding, and `run_complete` is the only thing that reveals
# the "Enter review" button.
ALWAYS_FLUSH = ("stage_complete", "run_complete", "preview_ready")


def key_for(pid: str) -> str:
    return f"events/{pid}.json"


class EventLog:
    """Append-only progress for one production.

    `append` is the `ctx.listener` callable, and `PipelineContext.emit` is
    **synchronous** — so this must not do a network write per event. In the
    cloud profile a blob write is tens of milliseconds and there are forty emit
    sites, several of them inside the `asyncio.gather` that runs three video
    scans at once; writing on every one would stall the very work it is
    reporting on. So writes are coalesced on a timer, with the events the UI
    actually waits for exempted.
    """

    def __init__(self, blobs: BlobStore, pid: str, flush_every_s: float = 0.0):
        self._blobs = blobs
        self._pid = pid
        self._key = key_for(pid)
        self._events: list[dict] = []
        self._dirty = False
        self._flush_every_s = flush_every_s
        self._last_flush = 0.0

    def append(self, event: dict) -> None:
        """The listener. Never raises: losing progress must not fail a run."""
        self._events.append(event)
        self._dirty = True
        due = (time.monotonic() - self._last_flush) >= self._flush_every_s
        if event.get("type") in ALWAYS_FLUSH or due:
            self.flush()

    def flush(self) -> None:
        if not self._dirty:
            return
        try:
            self._blobs.put(self._key, json.dumps(self._events).encode())
            self._dirty = False
            self._last_flush = time.monotonic()
        except Exception:
            # A progress write that fails is a cosmetic loss; a run that dies
            # because progress could not be written is not.
            log.exception("could not write the event log for %s", self._pid)

    @staticmethod
    def read(blobs: BlobStore, pid: str) -> list[dict]:
        """Every event so far. Empty when the run has not started."""
        try:
            raw = blobs.get(key_for(pid))
        except KeyError:
            return []
        try:
            events = json.loads(raw)
        except ValueError:
            return []
        return events if isinstance(events, list) else []

    @staticmethod
    def exists(blobs: BlobStore, pid: str) -> bool:
        return blobs.exists(key_for(pid))

    @staticmethod
    def clear(blobs: BlobStore, pid: str) -> None:
        blobs.delete(key_for(pid))
