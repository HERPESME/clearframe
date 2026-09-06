"""The rights ledger, where both containers can reach it.

Media, state and events all moved into the blob store when the topology split
into an API and a worker. The ledger did not, and nothing noticed — because the
local profile has one filesystem and it is the only profile the suite exercised.

In the cloud that omission had a specific consequence. `build_context` read
`LicenceStore(out_root / "state", owner_uid=...)`, and both services run
`--out /tmp/out` on separate instances, so the worker's coverage stage opened an
empty ledger no matter what the user had uploaded through the API. An empty
ledger is not an error — it answers UNKNOWN or NOT_COVERED for every finding, so
the product went on looking like it worked and simply never told anyone they
were already licensed.

Same interface as `LicenceStore`, same on-the-wire bytes (both go through
`store.parse_ledger` / `store.serialise_ledger`), so a ledger written by either
reads in the other. That matters more than it sounds: `scripts/dev.sh --split`
runs the two-container arrangement against `LocalBlobStore`, which is how this
gets exercised without a bucket.
"""

from __future__ import annotations

import logging

from clearframe.store import (
    DEMO_LEDGER,
    ledger_slug,
    parse_ledger,
    serialise_ledger,
)

log = logging.getLogger("clearframe.licences")

# The shelf for callers with no signed-in user: the CLI, the MCP server and the
# demo seed. Named rather than empty so it cannot be reached by sending a blank
# uid and cannot collide with a real account's slug, which is alphanumeric.
SHARED = "_shared"


class BlobLicenceStore:
    """One account's grants, in the blob store.

    Keyed by owner for the reason `LicenceStore` documents at length: being
    wrong in the COVERED direction is the single failure this ledger must not
    have, and one shared file meant Alice's Nike grant cleared Bob's Nike
    finding in Bob's E&O dossier.
    """

    def __init__(self, blobs, owner_uid: str = ""):
        self._blobs = blobs
        self.owner_uid = owner_uid or ""
        self.key = f"licences/{ledger_slug(owner_uid) or SHARED}.json"

    def load(self) -> list:
        """The grants on this shelf. An absent ledger is empty, not an error."""
        try:
            raw = self._blobs.get(self.key)
        except KeyError:
            return []
        try:
            return parse_ledger(raw)
        except Exception:
            # Same tolerance the local store has, one level up: a ledger that
            # will not parse at all reads as no ledger rather than failing the
            # analysis. It is logged because, unlike a single bad row, this one
            # means somebody's uploaded file is unreadable.
            log.warning("unreadable rights ledger at %s", self.key, exc_info=True)
            return []

    def save(self, licences: list) -> None:
        self._blobs.put(self.key, serialise_ledger(licences).encode())

    def seed_demo(self) -> list:
        """Install the sample ledger if this shelf has none yet."""
        if self._blobs.exists(self.key):
            return self.load()
        if DEMO_LEDGER.exists():
            self._blobs.put(self.key, DEMO_LEDGER.read_bytes())
        return self.load()
