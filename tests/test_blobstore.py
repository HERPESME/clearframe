"""The seam between "a file" and "where the file actually lives".

Everything ClearFrame persists is one of three things: a state document, a piece
of uploaded footage, or something derived from footage (a poster frame, a
dossier). On a laptop all three are files under `--out`. On Cloud Run the
instance is gone in a minute and `/tmp` with it, so they have to live in a
bucket — and the pipeline must not have to care which.

The awkward member of the interface is `open_local`. Three things in this
codebase can only work on a real filesystem path: ffmpeg (`media.probe_media`,
`media.extract_frame`) shells out with the path as an argument, and audio
fingerprinting refuses a `gs://` URI outright and needs to cut samples from a
local file. So the contract has to include "give me this as a path I can hand to
a subprocess", with the local implementation handing back the real file and
paying nothing for it.
"""

from pathlib import Path

import pytest

from clearframe.storage.blobs import LocalBlobStore


@pytest.fixture
def store(tmp_path):
    return LocalBlobStore(tmp_path / "blobs")


def test_what_goes_in_comes_out(store):
    store.put("u/alice/p1/state.json", b"{}")

    assert store.get("u/alice/p1/state.json") == b"{}"


def test_a_missing_blob_raises_rather_than_returning_empty(store):
    """Silence and emptiness must not look the same.

    `LocalJsonStore.load` raises FileNotFoundError and callers catch it to mean
    "no such production" — cli.py:41 and mcp/server.py:90 both resume on it.
    """
    with pytest.raises(KeyError):
        store.get("u/alice/nope.json")


def test_existence_is_answerable_without_reading(store):
    store.put("a", b"x")

    assert store.exists("a")
    assert not store.exists("b")


def test_a_blob_can_be_written_from_a_file_without_being_read_into_memory(store, tmp_path):
    """Footage is capped at 512MB; `put(key, path.read_bytes())` would be a
    512MB allocation on the API container to move a file it never inspects."""
    src = tmp_path / "footage.mp4"
    src.write_bytes(b"\x00" * 4096)

    store.put_file("u/alice/p1/footage.mp4", src)

    assert store.get("u/alice/p1/footage.mp4") == b"\x00" * 4096


def test_open_local_yields_a_path_a_subprocess_can_read(store):
    """The whole reason this method exists: ffmpeg takes a path, not bytes."""
    store.put("u/alice/p1/footage.mp4", b"\xff\xd8data")

    with store.open_local("u/alice/p1/footage.mp4") as path:
        assert isinstance(path, Path)
        assert path.exists()
        assert path.read_bytes() == b"\xff\xd8data"


def test_open_local_on_a_missing_blob_raises(store):
    with pytest.raises(KeyError):
        with store.open_local("nope"):
            pass


def test_the_local_store_does_not_copy_to_serve_open_local(store, tmp_path):
    """A 512MB copy per grounding call would be absurd; the file is already here."""
    store.put("u/alice/p1/footage.mp4", b"data")

    with store.open_local("u/alice/p1/footage.mp4") as path:
        assert path == (tmp_path / "blobs" / "u/alice/p1/footage.mp4")


def test_version_changes_when_the_content_does(store):
    """`media_version` busts four separate caches — the video URL, the thumbnail
    filename, the box cache key and the pre-ground set. It was `stat()`-derived,
    which a bucket cannot offer, so it becomes the store's answer."""
    store.put("k", b"first")
    first = store.version("k")
    store.put("k", b"second-and-longer")

    assert first and store.version("k") != first


def test_version_of_a_missing_blob_is_none(store):
    assert store.version("nope") is None


def test_deleting_removes_it(store):
    store.put("k", b"x")

    store.delete("k")

    assert not store.exists("k")


def test_deleting_something_absent_is_not_an_error(store):
    """Upload sweeps stale thumbnails without checking; a raise there would turn
    a successful upload into a 500."""
    store.delete("never-existed")


def test_listing_is_by_prefix_so_one_production_can_be_swept(store):
    store.put("u/alice/p1/thumb-1.jpg", b"a")
    store.put("u/alice/p1/thumb-2.jpg", b"b")
    store.put("u/alice/p2/thumb-3.jpg", b"c")

    assert sorted(store.list("u/alice/p1/")) == [
        "u/alice/p1/thumb-1.jpg",
        "u/alice/p1/thumb-2.jpg",
    ]


def test_a_key_cannot_escape_the_root(store):
    """Keys reach this from `{pid}` path params. `..` in a key must not write
    outside the store, which on a laptop is somebody's home directory."""
    with pytest.raises(ValueError):
        store.put("../../escape.json", b"x")
    with pytest.raises(ValueError):
        store.get("u/../../etc/passwd")
