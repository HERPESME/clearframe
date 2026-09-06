"""Re-uploading footage must replace the video in the player, not just on disk.

Every upload lands at the same production id, so the player's src —
/api/productions/upload/media — is byte-identical between two completely
different films. The browser does what it is told and replays the video it
already has, so a user watching the analysis of one clip sees the footage of
the previous one, with the previous frames under the new boxes.

Nothing on the server is wrong when this happens, which is why it is hard to
see: the state is right, the file on disk is right, and the endpoint serves the
right bytes to curl.
"""

import io

from fastapi.testclient import TestClient

from clearframe.webapp.server import create_app


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("PARALLEL_API_KEY", "key")

    def _fixture_context(cfg, production, out_root, **kw):
        """Store the footage and the production, without a live pipeline.

        The upload endpoint always starts a run; this test is about the bytes
        it stored, not the analysis it triggers.
        """
        from clearframe.pipeline import demo_context

        ctx = demo_context(out_root)
        ctx.state.production = production
        return ctx

    monkeypatch.setattr("clearframe.webapp.server.build_context", _fixture_context)
    return TestClient(create_app(out_root=tmp_path))


def _upload(client, payload: bytes, title: str):
    return client.post(
        "/api/productions",
        files={"file": ("clip.mp4", io.BytesIO(payload), "video/mp4")},
        data={"title": title, "duration_s": "10", "autorun": "false"},
        headers={"X-Role": "producer"},
    )


def test_replacing_the_footage_changes_the_media_version(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    first = _upload(client, b"\x00" * 2048, "Code Geass clip")
    assert first.status_code == 200, first.text
    v1 = client.get("/api/productions/upload").json()["production"]["media_version"]
    assert v1 != ""

    second = _upload(client, b"\x01" * 4096, "Hangover clip")
    assert second.status_code == 200, second.text
    v2 = client.get("/api/productions/upload").json()["production"]["media_version"]

    # Different bytes behind the same URL must present a different URL.
    assert v2 != v1


def test_media_is_revalidated_rather_than_replayed(tmp_path, monkeypatch):
    """A cache-busting token cannot help a player that already has the URL."""
    client = _client(tmp_path, monkeypatch)
    _upload(client, b"\x00" * 2048, "clip")

    r = client.get("/api/productions/upload/media")

    assert r.status_code == 200
    assert "no-cache" in r.headers.get("cache-control", "")


def test_media_version_is_zero_without_footage(tmp_path, monkeypatch):
    """A production with no media must not advertise a version for one."""
    client = _client(tmp_path, monkeypatch)
    body = client.get("/api/productions/demo")
    if body.status_code == 200:
        assert body.json()["production"]["media_version"] == ""
