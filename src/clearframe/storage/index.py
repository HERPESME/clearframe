"""The production index: ownership, progress, and who is still working.

Small, queryable rows kept apart from the state documents on purpose. A
`ProductionState` measures 227KB for a 42-second clip — court 45KB, defences
36KB — and grows with the footage, so it belongs in a blob. What the dashboard
needs is a title, a timestamp and a progress map, which is a few hundred bytes
and wants ordering and an owner filter. Those are different storage problems and
this module is the smaller one.

**Ownership lives here, not in `ProductionState`.** Who may open a production is
a fact about a deployment; what was found in the footage is the clearance
record. Putting a uid in the record would put it in the E&O dossier, and it does
not belong there.

**`running` is a heartbeat, not a flag.** The old answer was `pid in _live_runs`
— a set in one process, whose docstring conceded "a restart empties it, which is
the point". That is a correct answer to "is this process running it" and a wrong
answer to "is anyone running it", and the two stop being the same question the
moment the pipeline moves to a worker container. A worker beats while it works;
a row that has stopped beating was abandoned, on whatever machine, and the
dashboard can say so without knowing which machine that was.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

# How long silence is tolerated before a run is presumed dead.
#
# This has to clear the longest single STAGE, not the longest run, because the
# beat rides on the save `Pipeline.run` already performs after each stage
# (pipeline.py:74) rather than on a timer of its own. The measured worst case is
# research at ~335s of a ~502s run, and a three-pass scan is minutes; 90s — the
# first number tried here — would have marked a healthy run interrupted in the
# middle of its most expensive stage, told the client to stop polling, and shown
# a "this run died" banner over a run that was proceeding normally.
#
# The cost of the generous window is the opposite error: a worker killed
# mid-stage still reads as running until the lease lapses. That is the better
# direction to be wrong in — a stalled spinner invites a refresh, whereas a
# false "interrupted" invites paying for the whole analysis again.
HEARTBEAT_STALE_S = 900.0


class IndexRow(BaseModel):
    """One dashboard row. Everything here is cheap to read and safe to list."""

    id: str
    owner_uid: str | None = None
    title: str = "Untitled Production"
    stage_status: dict[str, str] = Field(default_factory=dict)
    updated_at: float = 0.0
    media_version: str | None = None
    has_media: bool = False
    # Wall-clock of the last "still working" signal. None means nobody is.
    heartbeat_at: float | None = None

    def is_complete(self) -> bool:
        from clearframe.pipeline import ANALYSIS_STAGES

        return all(self.stage_status.get(s) == "complete" for s in ANALYSIS_STAGES)

    def is_running(self) -> bool:
        if self.is_complete() or self.heartbeat_at is None:
            return False
        return (time.time() - self.heartbeat_at) < HEARTBEAT_STALE_S

    def is_interrupted(self) -> bool:
        """Part-way through and nobody is working on it.

        Deliberately requires *some* progress: a row with no stages done and no
        heartbeat is a production that has not started, not one that died.
        """
        if self.is_complete() or self.is_running():
            return False
        return any(v == "complete" for v in self.stage_status.values())


@runtime_checkable
class ProductionIndex(Protocol):
    def put(self, row: IndexRow) -> None: ...

    def get(self, pid: str) -> IndexRow | None: ...

    def list_for(self, owner_uid: str | None) -> list[IndexRow]:
        """Newest first. `None` means unscoped — authentication is off."""

    def record_stage(self, pid: str, stage: str, status: str) -> None: ...

    def heartbeat(self, pid: str) -> None: ...

    def clear_heartbeat(self, pid: str) -> None: ...

    def delete(self, pid: str) -> None: ...


class LocalProductionIndex:
    """One JSON file per row under a directory, with the state dir as a fallback.

    Not a database, and does not need to be: a laptop has a handful of
    productions and the whole point of this implementation is that the test
    suite exercises the same call sites the cloud one will.

    **The backfill is not a convenience, it is the compatibility contract.** A
    production written before this module existed — by the CLI, by the MCP
    server, by any of the forty-odd tests that hand-write
    `<out>/state/{pid}.json` directly — has no index row, and without a fallback
    it would simply vanish from the dashboard. So a row that is missing is
    synthesised from the state document: title and stage_status read from it,
    `updated_at` from its mtime (which is exactly what the listing used to do),
    and no owner, because a production written before ownership existed cannot
    have had one and must stay visible to everybody.

    `index_dir` is deliberately NOT `state_dir`: `LocalJsonStore.production_ids`
    globs `state/*.json`, so an index file kept alongside would be returned as a
    production id — the same class of bug that made `licences.json` a reserved
    name in that module.
    """

    def __init__(self, root: Path, state_dir: Path | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir = Path(state_dir) if state_dir is not None else None

    def _backfill(self, pid: str) -> IndexRow | None:
        """Synthesise a row from a state document written without one."""
        if self.state_dir is None:
            return None
        path = self.state_dir / f"{pid}.json"
        try:
            raw = json.loads(path.read_text())
        except (FileNotFoundError, ValueError, OSError):
            return None
        production = raw.get("production") or {}
        return IndexRow(
            id=pid,
            owner_uid=None,
            title=production.get("title") or "Untitled Production",
            stage_status=raw.get("stage_status") or {},
            updated_at=path.stat().st_mtime,
            # No heartbeat: nothing is claiming to run it. An unfinished one
            # reads as interrupted, which is what a run that died with its
            # process actually is.
            heartbeat_at=None,
        )

    def _path(self, pid: str) -> Path:
        safe = "".join(c for c in pid if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError(f"unusable production id: {pid!r}")
        return self.root / f"{safe}.json"

    def _write(self, row: IndexRow) -> None:
        target = self._path(row.id)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(row.model_dump_json(indent=2))
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def put(self, row: IndexRow) -> None:
        if not row.updated_at:
            row = row.model_copy(update={"updated_at": time.time()})
        self._write(row)

    def get(self, pid: str) -> IndexRow | None:
        try:
            raw = self._path(pid).read_text()
        except (FileNotFoundError, ValueError):
            return self._backfill(pid)
        try:
            return IndexRow.model_validate_json(raw)
        except Exception:
            # A corrupt row must not sink the listing, and the state document is
            # the authority anyway.
            return self._backfill(pid)

    def _known_ids(self) -> set[str]:
        ids = {p.stem for p in self.root.glob("*.json")}
        if self.state_dir is not None and self.state_dir.exists():
            from clearframe.store import RESERVED_STATE_FILES

            ids |= {
                p.stem
                for p in self.state_dir.glob("*.json")
                if p.stem not in RESERVED_STATE_FILES
                and not p.stem.startswith("licences-")
            }
        return ids

    def list_for(self, owner_uid: str | None) -> list[IndexRow]:
        rows = []
        for pid in self._known_ids():
            row = self.get(pid)
            if row is None:
                continue
            # An unowned production — written before ownership existed, or by
            # the CLI, or the shared demo — is visible to everyone. Ownership is
            # opt-in for exactly the same reason authentication is.
            if owner_uid is not None and row.owner_uid not in (None, "", owner_uid):
                continue
            rows.append(row)
        return sorted(rows, key=lambda r: r.updated_at, reverse=True)

    def _mutate(self, pid: str, **changes) -> None:
        row = self.get(pid)
        if row is None:
            return  # a retried task for a deleted production must not raise
        self._write(row.model_copy(update=changes))

    def record_stage(self, pid: str, stage: str, status: str) -> None:
        row = self.get(pid)
        if row is None:
            return
        status_map = dict(row.stage_status)
        status_map[stage] = status
        self._write(
            row.model_copy(update={"stage_status": status_map, "updated_at": time.time()})
        )

    def heartbeat(self, pid: str) -> None:
        self._mutate(pid, heartbeat_at=time.time())

    def clear_heartbeat(self, pid: str) -> None:
        self._mutate(pid, heartbeat_at=None)

    def delete(self, pid: str) -> None:
        try:
            self._path(pid).unlink(missing_ok=True)
        except ValueError:
            pass
