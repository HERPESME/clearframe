"""A production's poster is a frame of its own footage.

The dashboard needs a picture per production, and the honest picture is one the
production already contains. Anything else would mean shipping somebody else's
marketing art inside a product whose whole pitch is finding other people's IP
before you ship it.

The moment is chosen rather than arbitrary: the middle of the first finding's
first appearance, because that is what the analysis says this footage is about.
With no findings yet it falls back to a point inside the clip.

Extraction is one ffmpeg spawn, so the result is cached on disk under the
media version — a re-upload at the same production id gets a new picture, which
is the same rule the video URL and the box cache already follow.
"""

import json

import pytest
from fastapi.testclient import TestClient

from clearframe.webapp.server import create_app

JPEG_MAGIC = b"\xff\xd8"


def _production(tmp_path, pid="p1", with_media=True, with_elements=True):
    state = {
        "production": {"id": pid, "title": "t", "footage_uri": "c.mp4",
                       "duration_s": 40.0, "fps": 24.0},
        "elements": [],
    }
    if with_elements:
        state["elements"] = [{
            "id": "e1", "label": "Nike", "element_type": "LOGO",
            "description": "", "category": "TRADEMARK",
            "time_ranges": [{"start_s": 10.0, "end_s": 14.0}],
            "prominence": {"screen_time_s": 4.0, "frame_coverage": 0.1,
                           "centrality": 0.5, "plot_integral": False},
        }]
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / f"{pid}.json").write_text(json.dumps(state))
    if with_media:
        media = tmp_path / "media" / pid
        media.mkdir(parents=True, exist_ok=True)
        (media / "footage.mp4").write_bytes(b"\x00" * 2048)


@pytest.fixture
def frames(monkeypatch):
    """Record every extraction so the cache can be proven, not assumed."""
    asked: list[float] = []

    def _extract(path, at_s, **kw):
        asked.append(at_s)
        return JPEG_MAGIC + b"pretend-jpeg"

    monkeypatch.setattr("clearframe.webapp.server.extract_frame", _extract)
    return asked


def test_a_production_with_footage_has_a_poster(tmp_path, frames):
    _production(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    r = c.get("/api/productions/p1/thumbnail")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert r.content.startswith(JPEG_MAGIC)


def test_the_frame_is_the_middle_of_the_first_finding(tmp_path, frames):
    """What the analysis says the footage is about, not an arbitrary second."""
    _production(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    c.get("/api/productions/p1/thumbnail")

    assert frames == [12.0]  # (10.0 + 14.0) / 2


def test_a_production_with_no_findings_still_gets_a_frame(tmp_path, frames):
    _production(tmp_path, with_elements=False)
    c = TestClient(create_app(out_root=tmp_path))

    assert c.get("/api/productions/p1/thumbnail").status_code == 200
    assert frames == [16.0]  # 40.0 * 0.4, comfortably inside the clip


def test_the_frame_is_extracted_once_however_often_it_is_asked_for(tmp_path, frames):
    """One ffmpeg spawn per production, then a file on disk.

    A rail of cards asks for every poster at once, and every reload asks again.
    """
    _production(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    for _ in range(4):
        assert c.get("/api/productions/p1/thumbnail").status_code == 200

    assert len(frames) == 1


def test_new_footage_gets_a_new_poster(tmp_path, frames):
    """Every upload lands at the same production id; the picture must follow."""
    import os
    import time

    _production(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))
    c.get("/api/productions/p1/thumbnail")

    footage = tmp_path / "media" / "p1" / "footage.mp4"
    time.sleep(0.01)
    footage.write_bytes(b"\x01" * 4096)
    os.utime(footage, None)

    c.get("/api/productions/p1/thumbnail")

    assert len(frames) == 2, "the second film was served the first film's poster"


def test_no_footage_is_a_404_so_the_client_can_draw_its_own(tmp_path, frames):
    """404 rather than a placeholder: the fallback art belongs to the client."""
    _production(tmp_path, with_media=False)
    c = TestClient(create_app(out_root=tmp_path))

    assert c.get("/api/productions/p1/thumbnail").status_code == 404


def test_an_unextractable_frame_is_a_404_not_a_broken_image(tmp_path, monkeypatch):
    _production(tmp_path)
    monkeypatch.setattr(
        "clearframe.webapp.server.extract_frame", lambda path, at_s, **kw: None
    )
    c = TestClient(create_app(out_root=tmp_path))

    assert c.get("/api/productions/p1/thumbnail").status_code == 404


def test_the_poster_is_behind_the_gate_like_everything_else(tmp_path, frames, monkeypatch):
    """It is a frame of the user's footage, so it is not public."""
    monkeypatch.setenv("CLEARFRAME_AUTH", "firebase")
    _production(tmp_path)
    c = TestClient(create_app(out_root=tmp_path))

    assert c.get("/api/productions/p1/thumbnail").status_code == 401
