"""The cloud twins: Cloud Storage for bytes, Firestore for the index.

Thin on purpose. Every decision — what a key looks like, what `running` means,
how a version busts a cache — was made in the local implementations and tested
there, credential-free. These translate and nothing more, which is the same
arrangement the integration clients use and the reason a fixture run exercises
the real code path.

**Every Google import is inside a function body.** The base image installs no
Google packages at all and the test suite must import this module without them;
that discipline is what keeps `pip install .` clean and the 815 tests offline.

**No signed URLs.** Serving footage straight from a bucket URL was the obvious
shortcut and it is wrong twice: minting one needs `iam.serviceAccounts.signBlob`,
which a default runtime account does not hold on itself, and — more importantly
— a signed URL bypasses the ownership check that was just built. The bytes go
through the API so that the question "may you see this?" is still asked.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from clearframe.storage.blobs import check_key
from clearframe.storage.index import IndexRow

log = logging.getLogger("clearframe.storage.cloud")

COLLECTION = "productions"


class GcsBlobStore:
    """Objects in one bucket, keyed exactly as the local store keys files."""

    def __init__(self, bucket: str, cache_dir: Path | None = None):
        self._bucket_name = bucket
        self._bucket = None
        self._cache_dir = Path(
            cache_dir or os.environ.get("CLEARFRAME_CACHE_DIR", "/tmp/clearframe-cache")
        )

    def _b(self):
        if self._bucket is None:
            from google.cloud import storage

            self._bucket = storage.Client().bucket(self._bucket_name)
        return self._bucket

    def put(self, key: str, data: bytes) -> str:
        blob = self._b().blob(check_key(key))
        blob.upload_from_string(data)
        return f"{blob.size}-{blob.generation}"

    def put_file(self, key: str, path: Path) -> str:
        blob = self._b().blob(check_key(key))
        # Streamed by the client library: a 512MB upload must not become a
        # 512MB allocation on a container sized for an API.
        blob.upload_from_filename(str(path))
        return f"{blob.size}-{blob.generation}"

    def get(self, key: str) -> bytes:
        blob = self._b().blob(check_key(key))
        try:
            return blob.download_as_bytes()
        except Exception as exc:
            if _is_missing(exc):
                raise KeyError(key) from exc
            raise

    def local_path(self, key: str) -> Path | None:
        """Materialise the object as a real file, for ffmpeg and FileResponse.

        Cached by key AND version, so re-uploaded footage never serves the
        previous film's frames — the same rule the box cache learned the hard
        way — and a second grounding call on the same clip pays nothing.

        The download goes to a `.part` and is renamed, because a half-downloaded
        mp4 that ffmpeg reads as a whole one produces a plausible wrong answer
        rather than an error.
        """
        version = self.version(key)
        if version is None:
            return None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        stamp = hashlib.sha1(f"{key}@{version}".encode()).hexdigest()[:16]
        local = self._cache_dir / f"{stamp}{Path(key).suffix}"
        if not local.exists():
            tmp = local.with_suffix(local.suffix + ".part")
            self._b().blob(check_key(key)).download_to_filename(str(tmp))
            os.replace(tmp, local)
        return local

    @contextlib.contextmanager
    def open_local(self, key: str) -> Iterator[Path]:
        local = self.local_path(key)
        if local is None:
            raise KeyError(key)
        yield local

    def exists(self, key: str) -> bool:
        return self._b().blob(check_key(key)).exists()

    def delete(self, key: str) -> None:
        try:
            self._b().blob(check_key(key)).delete()
        except Exception as exc:
            if not _is_missing(exc):
                raise

    def list(self, prefix: str) -> list[str]:
        return sorted(b.name for b in self._b().list_blobs(prefix=prefix))

    def version(self, key: str) -> str | None:
        # `bucket.blob()` does no I/O and its generation is None; only
        # `get_blob` actually fetches the metadata. Getting this wrong yields a
        # version string that never changes, which would silently disable every
        # cache that depends on it.
        blob = self._b().get_blob(check_key(key))
        return None if blob is None else f"{blob.size}-{blob.generation}"


def _is_missing(exc: Exception) -> bool:
    from google.api_core import exceptions as gexc

    return isinstance(exc, gexc.NotFound)


class FirestoreProductionIndex:
    """One small document per production. Never the state — see `index.py`."""

    def __init__(self, project: str | None = None):
        self._project = project
        self._db = None

    def _c(self):
        if self._db is None:
            from google.cloud import firestore

            self._db = firestore.Client(project=self._project)
        return self._db.collection(COLLECTION)

    def put(self, row: IndexRow) -> None:
        if not row.updated_at:
            row = row.model_copy(update={"updated_at": time.time()})
        self._c().document(row.id).set(row.model_dump())

    def get(self, pid: str) -> IndexRow | None:
        snap = self._c().document(pid).get()
        if not snap.exists:
            return None
        try:
            return IndexRow.model_validate(snap.to_dict())
        except Exception:
            log.warning("unreadable index row for %s", pid)
            return None

    def list_for(self, owner_uid: str | None) -> list[IndexRow]:
        # Filtered server-side, ordered in Python. Combining `where` with
        # `order_by` on a different field demands a composite index and a
        # console round trip to create it; a user has tens of productions, not
        # thousands, so the sort is free and the deploy is one step shorter.
        query = self._c()
        if owner_uid is not None:
            from google.cloud.firestore_v1.base_query import FieldFilter

            query = query.where(filter=FieldFilter("owner_uid", "in", [owner_uid, None, ""]))
        rows = []
        for snap in query.stream():
            try:
                rows.append(IndexRow.model_validate(snap.to_dict()))
            except Exception:
                continue
        return sorted(rows, key=lambda r: r.updated_at, reverse=True)

    def record_stage(self, pid: str, stage: str, status: str) -> None:
        self._c().document(pid).set(
            {"stage_status": {stage: status}, "updated_at": time.time()}, merge=True
        )

    def heartbeat(self, pid: str) -> None:
        self._c().document(pid).set({"heartbeat_at": time.time()}, merge=True)

    def clear_heartbeat(self, pid: str) -> None:
        self._c().document(pid).set({"heartbeat_at": None}, merge=True)

    def delete(self, pid: str) -> None:
        self._c().document(pid).delete()
