"""Where the bytes live: a local directory, or a bucket.

Three kinds of thing go through here — production state documents, uploaded
footage, and artifacts derived from footage (poster frames, dossiers, exports).
On a laptop they are files under `--out`. On Cloud Run the instance and its
`/tmp` are gone within a minute of the last request, so they have to be in
Cloud Storage, and nothing above this module should have to know which.

Same shape as the integration clients: one protocol, a local implementation and
a cloud one sharing the caller's code path, so the credential-free test suite
exercises the real thing rather than a mock.

`open_local` is the method that keeps this honest. Three callers cannot work
with bytes:

  - `media.probe_media` and `media.extract_frame` build an ffmpeg argv and hand
    it a path (`media.py`), and `-ss` before `-i` is a keyframe seek that a pipe
    would defeat.
  - `integrations.audio_client` refuses a `gs://` URI outright and cuts its
    samples out of a local file.

So the contract includes "materialise this somewhere a subprocess can open it".
The local store hands back the real file and copies nothing; the GCS store
downloads to a temporary file and removes it on exit.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class BlobStore(Protocol):
    """Content-addressed-ish storage. Keys are `/`-separated, never absolute."""

    def put(self, key: str, data: bytes) -> str:
        """Write bytes, returning the new version."""

    def put_file(self, key: str, path: Path) -> str:
        """Write from a file without reading it into memory."""

    def get(self, key: str) -> bytes:
        """Read. Raises `KeyError` if absent — never returns empty for missing."""

    def open_local(self, key: str) -> contextlib.AbstractContextManager[Path]:
        """Yield a real filesystem path for the blob, for subprocess consumers."""

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None:
        """Remove. Absent is not an error."""

    def list(self, prefix: str) -> list[str]:
        """Every key under `prefix`."""

    def version(self, key: str) -> str | None:
        """An opaque token that changes when the content does; None if absent."""


def check_key(key: str) -> str:
    """Reject anything that could address outside the store.

    Keys are assembled from `{pid}` path parameters and user ids, so this is a
    real boundary rather than a formality: the local store's root is a directory
    on somebody's laptop, and `..` in a key would write outside it.
    """
    if not key or key.startswith("/"):
        raise ValueError(f"blob key must be relative and non-empty: {key!r}")
    parts = key.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"blob key may not contain empty or relative segments: {key!r}")
    return key


class LocalBlobStore:
    """Files under a directory. The profile a laptop and the test suite use."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / check_key(key)

    def put(self, key: str, data: bytes) -> str:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Same atomic write as LocalJsonStore: a half-written state document read
        # by a concurrent request is worse than a missing one.
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return self.version(key) or ""

    def put_file(self, key: str, path: Path) -> str:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(path).resolve() != target.resolve():
            shutil.copyfile(path, target)
        return self.version(key) or ""

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise KeyError(key) from exc

    @contextlib.contextmanager
    def open_local(self, key: str) -> Iterator[Path]:
        path = self._path(key)
        if not path.exists():
            raise KeyError(key)
        yield path  # already a real file; copying it would be pure waste

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        base = self.root
        out = []
        for path in base.rglob("*"):
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            key = path.relative_to(base).as_posix()
            if key.startswith(prefix):
                out.append(key)
        return sorted(out)

    def version(self, key: str) -> str | None:
        """Size and nanosecond mtime.

        Whole seconds collide when two uploads land in the same second — that
        exact bug served one film's cached boxes for the next one, so the
        nanoseconds are load-bearing rather than decorative.
        """
        try:
            st = self._path(key).stat()
        except FileNotFoundError:
            return None
        return f"{st.st_size}-{st.st_mtime_ns}"
