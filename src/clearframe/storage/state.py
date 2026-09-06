"""Production state as a blob, with the index kept in step.

`ProductionState` is the clearance record — every finding, every route, every
band, the court transcript and the liability table. Measured at **227KB for a
42-second clip** (court 45KB, defences 36KB, preview 21KB), and it grows with
the footage. Firestore's hard limit is 1 MiB per document, so a feature-length
run would simply fail to save. It is a blob, and the small queryable row that
the dashboard lists is a separate thing living in `index.py`.

Keeping the two in step is this module's whole job. `save()` is called by
`Pipeline.run` after every stage, which makes it exactly the right hook: the
index learns the title, the progress and the timestamp without any caller having
to remember to tell it.
"""

from __future__ import annotations

import logging
import time

from clearframe.models import ProductionState
from clearframe.storage.blobs import BlobStore
from clearframe.storage.index import IndexRow, ProductionIndex
from clearframe.store import is_reserved_state_file

log = logging.getLogger("clearframe.storage.state")


def state_key(pid: str) -> str:
    return f"state/{pid}.json"


class BlobStateStore:
    """The `LocalJsonStore` interface, over any blob store.

    Deliberately the same three methods — `save`, `load`, `production_ids` —
    because everything that touches state (the pipeline, review, the CLI, the
    MCP server) already speaks them, and a wider interface would mean changing
    all of it to gain nothing.

    `load` raises `FileNotFoundError` rather than `KeyError` for the same
    reason: callers already catch that to mean "no such production", and
    `cli._try_resume` and the MCP server both depend on it.
    """

    def __init__(self, blobs: BlobStore, index: ProductionIndex | None = None):
        self._blobs = blobs
        self._index = index

    def save(self, state: ProductionState) -> None:
        pid = state.production.id
        self._blobs.put(state_key(pid), state.model_dump_json(indent=2).encode())
        if self._index is None:
            return
        # The index follows the state rather than being maintained beside it.
        # `Pipeline.run` saves after every stage, so this is where progress
        # becomes visible to the dashboard — including for a run executing in a
        # different container, which is the entire point.
        #
        # Writing only the three fields this caller owns, not the whole row.
        # The old shape — read, `model_copy`, full `.set()` — reverted anything
        # written in between, and the beat timer writes every thirty seconds
        # while this runs after every stage, so they collide by design. Worse,
        # on a read MISS it rebuilt the row from defaults and dropped
        # `owner_uid`, which is the field the listing filters on: one unreadable
        # row became a permanently invisible production.
        self._index.record_progress(
            pid, state.production.title, dict(state.stage_status)
        )

    def load(self, production_id: str) -> ProductionState:
        try:
            raw = self._blobs.get(state_key(production_id))
        except KeyError as exc:
            raise FileNotFoundError(production_id) from exc
        return ProductionState.model_validate_json(raw)

    def production_ids(self) -> list[str]:
        """Ids in this store, sorted.

        The same reserved-name rule as the local store, plus the per-user ledger
        shape: `state/` also holds `licences.json` and `licences-{uid}.json`, and
        returning either as a production id is the bug that reserved list exists
        to prevent.
        """
        out = []
        for key in self._blobs.list("state/"):
            stem = key.removeprefix("state/").removesuffix(".json")
            if is_reserved_state_file(stem):
                continue
            out.append(stem)
        return sorted(out)
