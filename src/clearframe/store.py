"""Local JSON persistence for production state (Firestore replaces this in cloud mode)."""

import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from clearframe.models import ProductionState


RESERVED_STATE_FILES = {"licences"}


def is_reserved_state_file(stem: str) -> bool:
    """Is this state-directory file something other than a production?

    The directory holds the rights ledger beside the productions, and the ledger
    is now per-owner — `licences-{uid}.json` — so a bare membership test against
    the old set would start returning every user's ledger as a production id.
    One predicate, used by both store implementations and the local index, so
    the next thing kept in here cannot be missed at one of the three call sites.
    """
    return stem in RESERVED_STATE_FILES or stem.startswith("licences-")


class LocalJsonStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, production_id: str) -> Path:
        return self.root / f"{production_id}.json"

    def save(self, state: ProductionState) -> None:
        target = self._path(state.production.id)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(state.model_dump_json(indent=2))
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load(self, production_id: str) -> ProductionState:
        return ProductionState.model_validate_json(self._path(production_id).read_text())

    def production_ids(self) -> list[str]:
        """Production ids in this store, sorted.

        The state directory also holds non-production JSON (the rights ledger),
        so callers must never glob it blindly — reserved names are excluded here
        in one place rather than at every call site.
        """
        return sorted(
            path.stem
            for path in self.root.glob("*.json")
            if not is_reserved_state_file(path.stem)
        )


DEMO_LEDGER = (
    Path(__file__).parent / "integrations" / "fixtures" / "licences" / "demo_ledger.json"
)


class LicenceStore:
    """The clearances a production already holds.

    Kept beside production state as `licences.json`. A production with no ledger
    is a valid state (every finding reads UNKNOWN/NOT_COVERED) — the ledger is
    something a real clearance department already maintains and uploads, not
    something ClearFrame invents.

    **Keyed by owner, because a ledger is the most consequential thing here.**
    One global file meant one user's licences decided another user's coverage:
    upload a grant for Nike and every other account's Nike finding reads COVERED,
    with that conclusion written into their E&O dossier. And since the upload
    defaults to `replace=True` and is gated on a role that an open-roles
    deployment lets the client assert for itself, any visitor could wipe the
    whole deployment's ledger — reopening gaps in everyone's next run.

    `owner_uid=""` keeps the old global path byte-identical, which is what the
    CLI, the MCP server and the demo seed still use: they have no signed-in user
    and no other ledger to confuse theirs with.
    """

    def __init__(self, root: Path, owner_uid: str = ""):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in (owner_uid or "") if c.isalnum() or c in "-_")
        self.path = self.root / (f"licences-{safe}.json" if safe else "licences.json")

    def load(self) -> list:
        from clearframe.models import LicenceGrant

        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text())
        entries = raw.get("licences", raw) if isinstance(raw, dict) else raw
        out = []
        for e in entries:
            try:
                out.append(LicenceGrant.model_validate(e))
            except ValidationError:
                continue  # a malformed row must not sink the whole ledger
        return out

    def save(self, licences: list) -> None:
        payload = {"licences": [lic.model_dump(mode="json") for lic in licences]}
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(payload, indent=2))
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def seed_demo(self) -> list:
        """Install the sample ledger if the production has none yet."""
        if self.path.exists():
            return self.load()
        if DEMO_LEDGER.exists():
            self.path.write_text(DEMO_LEDGER.read_text())
        return self.load()
