"""Storage seams: blobs, the production index, and the analysis job queue.

Each is a protocol with a local implementation and a cloud one, selected by
`CLEARFRAME_PROFILE`. The local implementations are not stubs — they are what a
laptop and the test suite run, so the behaviour under test is the behaviour that
ships. Same discipline as the integration clients, where demo mode exercises the
identical code path with zero credentials.

This module is the **only** place that branches on the profile. Everything above
it takes a `Backends` and never asks where the bytes are.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from clearframe.config import ClearFrameConfig
from clearframe.storage.blobs import BlobStore, LocalBlobStore, check_key
from clearframe.storage.index import (
    HEARTBEAT_STALE_S,
    IndexRow,
    LocalProductionIndex,
    ProductionIndex,
)
from clearframe.storage.queue import (
    AnalysisJob,
    CloudTasksJobQueue,
    HttpJobQueue,
    InProcessJobQueue,
    JobQueue,
    Runner,
)

__all__ = [
    "AnalysisJob",
    "Backends",
    "BlobStore",
    "HEARTBEAT_STALE_S",
    "IndexRow",
    "JobQueue",
    "LocalBlobStore",
    "LocalProductionIndex",
    "ProductionIndex",
    "build_backends",
    "build_queue",
    "check_key",
]


class Backends(NamedTuple):
    blobs: BlobStore
    index: ProductionIndex


def build_backends(cfg: ClearFrameConfig, out_root: Path) -> Backends:
    """Blobs and the index for this profile.

    The local layout is deliberately the one that already exists on disk —
    `<out>/state/{pid}.json`, `<out>/media/{pid}/footage.mp4` — so a working
    directory written before any of this keeps working, and the forty tests that
    hand-write those paths keep passing.
    """
    out_root = Path(out_root)
    if cfg.profile == "cloud":
        from clearframe.storage.cloud import GcsBlobStore, FirestoreProductionIndex

        if not cfg.bucket:
            raise ValueError("CLEARFRAME_PROFILE=cloud needs CLEARFRAME_BUCKET")
        return Backends(
            blobs=GcsBlobStore(cfg.bucket),
            index=FirestoreProductionIndex(cfg.project),
        )
    return Backends(
        blobs=LocalBlobStore(out_root),
        # The index lives beside `state/`, never inside it: `production_ids()`
        # globs `state/*.json` and would return index files as productions —
        # the same trap that made `licences.json` a reserved name there.
        index=LocalProductionIndex(out_root / "index", state_dir=out_root / "state"),
    )


def build_queue(cfg: ClearFrameConfig, runner: Runner, limit: int = 5) -> JobQueue:
    """How an analysis gets scheduled.

    Three arrangements, in order of how much infrastructure they need:

    - a worker URL **and** a Cloud Tasks queue: production. The queue enforces
      the concurrency cap and retries.
    - a worker URL alone: the two-container topology on a laptop, with no GCP
      account. The cap comes from the worker's own admission control.
    - neither: everything in this process, capped by a semaphore. What the
      tests and a single-process `clearframe serve` run.
    """
    if cfg.worker_url and cfg.tasks_queue:
        return CloudTasksJobQueue(cfg.tasks_queue, cfg.worker_url, cfg.tasks_sa)
    if cfg.worker_url:
        return HttpJobQueue(cfg.worker_url)
    return InProcessJobQueue(runner, limit=limit)
