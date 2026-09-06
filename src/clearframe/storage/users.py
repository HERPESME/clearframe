"""Who has used this deployment, and when.

**Not credentials.** Firebase Authentication owns those — the email, the
provider, the scrypt password hash, the whole sign-in flow — and duplicating any
of it here would mean holding a second copy of the one thing that must never
have two copies. This is the *application's* record of a person: what they last
called themselves, which role they have been working as, when they first
appeared and when they were last seen.

It exists because Firebase can tell you an account exists and nothing about what
it did here. A deployment that records a decision against `someone@x.com` should
be able to say who that is without going to another console.

Small, one document per user, keyed by uid — the same shape and the same reasons
as the production index next door, and emphatically not a reason to add a
relational database: this is a handful of fields read by primary key.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

COLLECTION = "users"


class UserRecord(BaseModel):
    """One person, as this application knows them."""

    uid: str
    email: str | None = None
    name: str | None = None
    # Whether the provider confirmed the address. Carried here so the directory
    # can be read on its own without re-deriving it from a token, and because a
    # deployment reviewing its own audit trail wants to know.
    email_verified: bool = False
    # The role they were last working as. On an open-roles deployment this is
    # what they chose, which is worth recording precisely BECAUSE it was their
    # choice rather than a grant.
    role: str = "editor"
    first_seen: float = 0.0
    last_seen: float = 0.0
    sign_ins: int = 0


@runtime_checkable
class UserDirectory(Protocol):
    def seen(self, uid: str, **fields) -> UserRecord:
        """Record a sign-in, creating the person if this is their first."""

    def get(self, uid: str) -> UserRecord | None: ...

    def list(self) -> list[UserRecord]:
        """Everyone, most recently seen first."""


def _merge(existing: UserRecord | None, uid: str, now: float, fields: dict) -> UserRecord:
    """First sighting creates; later ones update without losing the beginning."""
    if existing is None:
        return UserRecord(
            uid=uid, first_seen=now, last_seen=now, sign_ins=1,
            **{k: v for k, v in fields.items() if v is not None},
        )
    update = {k: v for k, v in fields.items() if v is not None}
    update["last_seen"] = now
    update["sign_ins"] = existing.sign_ins + 1
    return existing.model_copy(update=update)


class LocalUserDirectory:
    """One JSON file per user. What a laptop and the test suite run."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, uid: str) -> Path:
        safe = "".join(c for c in uid if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError(f"unusable uid: {uid!r}")
        return self.root / f"{safe}.json"

    def get(self, uid: str) -> UserRecord | None:
        try:
            return UserRecord.model_validate_json(self._path(uid).read_text())
        except (FileNotFoundError, ValueError, OSError):
            return None

    def seen(self, uid: str, **fields) -> UserRecord:
        record = _merge(self.get(uid), uid, time.time(), fields)
        target = self._path(uid)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(record.model_dump_json(indent=2))
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return record

    def list(self) -> list[UserRecord]:
        out = []
        for path in self.root.glob("*.json"):
            try:
                out.append(UserRecord.model_validate_json(path.read_text()))
            except (ValueError, OSError):
                continue
        return sorted(out, key=lambda r: r.last_seen, reverse=True)


class FirestoreUserDirectory:
    """`users/{uid}`. The SDK import is lazy, like every other Google import."""

    def __init__(self, project: str | None = None):
        self._project = project
        self._db = None

    def _c(self):
        if self._db is None:
            from google.cloud import firestore

            self._db = firestore.Client(project=self._project)
        return self._db.collection(COLLECTION)

    def get(self, uid: str) -> UserRecord | None:
        snap = self._c().document(uid).get()
        if not snap.exists:
            return None
        try:
            return UserRecord.model_validate(snap.to_dict())
        except Exception:
            return None

    def seen(self, uid: str, **fields) -> UserRecord:
        record = _merge(self.get(uid), uid, time.time(), fields)
        self._c().document(uid).set(record.model_dump())
        return record

    def list(self) -> list[UserRecord]:
        rows = []
        for snap in self._c().stream():
            try:
                rows.append(UserRecord.model_validate(snap.to_dict()))
            except Exception:
                continue
        return sorted(rows, key=lambda r: r.last_seen, reverse=True)
