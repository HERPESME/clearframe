"""`has_media` is derived from disk, not trusted from the stored state.

The review app renders its video player on `production.has_media`. That flag
was set only by the upload endpoint, so a production re-scanned from the CLI —
against footage sitting right there on disk, with the media endpoint happily
returning 200 — came back with has_media False and no player.

A flag that says whether a file exists should be answered by looking for the
file. Anything else can go stale, and this one did.
"""

import pytest
from fastapi.testclient import TestClient

from clearframe.webapp.server import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(out_root=tmp_path)) as c:
        c.post("/api/productions/demo")
        yield c


def test_no_footage_on_disk_means_no_player(client):
    body = client.get("/api/productions/demo").json()
    assert body["production"]["has_media"] is False
    assert client.get("/api/productions/demo/media").status_code == 404


def test_footage_on_disk_means_a_player_even_if_the_state_says_otherwise(
    client, tmp_path
):
    """The exact failure: state written by a CLI run that never set the flag."""
    from clearframe.store import LocalJsonStore

    store = LocalJsonStore(tmp_path / "state")
    state = store.load("demo")
    assert state.production.has_media is False
    store.save(state)

    media = tmp_path / "media" / "demo"
    media.mkdir(parents=True, exist_ok=True)
    (media / "footage.mp4").write_bytes(b"\x00" * 64)

    body = client.get("/api/productions/demo").json()
    assert body["production"]["has_media"] is True, "player would be hidden"
    assert client.get("/api/productions/demo/media").status_code == 200


def test_the_flag_agrees_with_the_media_endpoint(client, tmp_path):
    """These two must never disagree — one hides the player, the other serves
    the file, and a user seeing no player while the bytes are served has no
    way to work out why."""
    for suffix in (".mp4", ".mov", ".webm"):
        media = tmp_path / "media" / "demo"
        media.mkdir(parents=True, exist_ok=True)
        for old in media.glob("footage.*"):
            old.unlink()
        (media / f"footage{suffix}").write_bytes(b"\x00" * 64)

        flag = client.get("/api/productions/demo").json()["production"]["has_media"]
        served = client.get("/api/productions/demo/media").status_code == 200
        assert flag is served, f"{suffix}: flag={flag} served={served}"
