"""Grounding on pause, cached, and never able to invent a finding.

The endpoint answers "where is each known element on the frame at T". It must:

  * only ever return boxes for elements already in the analysis
  * cost one model call per distinct moment, not one per pause
  * degrade to nothing when the frame or the model is unavailable, because the
    player already renders "on screen, position unknown" correctly
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

from clearframe.webapp.server import create_app


def _client(tmp_path, monkeypatch, calls):
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("PARALLEL_API_KEY", "key")

    state = {
        "production": {"id": "p1", "title": "t", "footage_uri": "c.mp4",
                       "duration_s": 41.5, "fps": 24.0},
        "elements": [
            {"id": "e1", "label": "Nike hoodie swoosh", "element_type": "LOGO",
             "description": "", "category": "TRADEMARK",
             "time_ranges": [{"start_s": 10.0, "end_s": 14.0}],
             "prominence": {"screen_time_s": 4.0, "frame_coverage": 0.1,
                            "centrality": 0.5, "plot_integral": False}},
        ],
    }
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "p1.json").write_text(json.dumps(state))
    media = tmp_path / "media" / "p1"
    media.mkdir(parents=True)
    (media / "footage.mp4").write_bytes(b"\x00" * 2048)

    monkeypatch.setattr(
        "clearframe.webapp.server.extract_frame",
        lambda path, at_s, **kw: b"\xff\xd8frame",
    )

    class Grounder:
        async def ground_frame(self, image, labels):
            from clearframe.models import BBox

            calls.append(tuple(labels))
            return {labels[0]: BBox(ymin=0.1, xmin=0.2, ymax=0.3, xmax=0.4)}

    monkeypatch.setattr(
        "clearframe.webapp.server.build_grounding_client", lambda cfg: Grounder()
    )
    return TestClient(create_app(out_root=tmp_path))


def test_a_box_comes_back_for_a_known_element(tmp_path, monkeypatch):
    calls = []
    c = _client(tmp_path, monkeypatch, calls)

    r = c.get("/api/productions/p1/ground", params={"at_s": 12.0})

    assert r.status_code == 200
    body = r.json()
    assert body["boxes"]["e1"]["ymin"] == 0.1
    # Keyed by element id, not by label: the client draws against its own state.
    assert set(body["boxes"]) <= {"e1"}


def test_the_same_moment_is_only_grounded_once(tmp_path, monkeypatch):
    calls = []
    c = _client(tmp_path, monkeypatch, calls)

    c.get("/api/productions/p1/ground", params={"at_s": 12.0})
    c.get("/api/productions/p1/ground", params={"at_s": 12.0})
    c.get("/api/productions/p1/ground", params={"at_s": 12.4})

    # 12.0 and 12.4 round to the same second, so one call covers all three.
    assert len(calls) == 1


def test_only_elements_on_screen_at_that_moment_are_offered(tmp_path, monkeypatch):
    """No point asking where a thing is in a frame it does not appear in."""
    calls = []
    c = _client(tmp_path, monkeypatch, calls)

    r = c.get("/api/productions/p1/ground", params={"at_s": 30.0})

    assert r.status_code == 200
    assert r.json()["boxes"] == {}
    assert calls == []


def test_an_unavailable_frame_is_not_an_error(tmp_path, monkeypatch):
    calls = []
    c = _client(tmp_path, monkeypatch, calls)
    monkeypatch.setattr(
        "clearframe.webapp.server.extract_frame", lambda path, at_s, **kw: None
    )

    r = c.get("/api/productions/p1/ground", params={"at_s": 12.0})

    assert r.status_code == 200
    assert r.json()["boxes"] == {}


def test_a_model_failure_is_not_an_error(tmp_path, monkeypatch):
    """A refined box is a nicety; the player already handles not having one.

    This exercises the exception path, which had a NameError in it — the
    handler logged through a module logger that server.py never defined, so
    the one branch that exists to keep a failure quiet would itself have 500'd.
    """
    calls = []
    c = _client(tmp_path, monkeypatch, calls)

    class Broken:
        async def ground_frame(self, image, labels):
            raise RuntimeError("model refused")

    monkeypatch.setattr(
        "clearframe.webapp.server.build_grounding_client", lambda cfg: Broken()
    )

    r = c.get("/api/productions/p1/ground", params={"at_s": 12.0})

    assert r.status_code == 200
    assert r.json()["boxes"] == {}
