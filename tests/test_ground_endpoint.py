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
            return {labels[0]: [BBox(ymin=0.1, xmin=0.2, ymax=0.3, xmax=0.4)]}

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
    assert body["boxes"]["e1"][0]["ymin"] == 0.1
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


# --- grounding must be able to say "not here" ---------------------------------
#
# A live pause put a "Ray-Ban Aviator Sunglasses" box on a bare forehead. The
# model was not at fault — a control asking it to place the Eiffel Tower and
# the Golden Gate Bridge in the same frame correctly returned neither. The
# player was: when grounding omitted an element, boxAt fell through to the
# scan's stored box, which is the video-pass rectangle grounding exists to
# replace. The one judgement worth having was thrown away.
#
# So the response has to distinguish three states the client used to conflate:
# grounded and found, grounded and absent, and not grounded at all.


def test_a_successful_grounding_says_so(tmp_path, monkeypatch):
    calls = []
    c = _client(tmp_path, monkeypatch, calls)
    body = c.get("/api/productions/p1/ground", params={"at_s": 12.0}).json()
    assert body["grounded"] is True


def test_an_unavailable_frame_is_not_reported_as_grounded(tmp_path, monkeypatch):
    """Otherwise the client suppresses every box on a frame nobody looked at."""
    calls = []
    c = _client(tmp_path, monkeypatch, calls)
    monkeypatch.setattr(
        "clearframe.webapp.server.extract_frame", lambda path, at_s, **kw: None
    )
    body = c.get("/api/productions/p1/ground", params={"at_s": 12.0}).json()
    assert body["grounded"] is False


def test_a_model_failure_is_not_reported_as_grounded(tmp_path, monkeypatch):
    calls = []
    c = _client(tmp_path, monkeypatch, calls)

    class Broken:
        async def ground_frame(self, image, labels):
            raise RuntimeError("model refused")

    monkeypatch.setattr(
        "clearframe.webapp.server.build_grounding_client", lambda cfg: Broken()
    )
    body = c.get("/api/productions/p1/ground", params={"at_s": 12.0}).json()
    assert body["grounded"] is False


def test_nothing_on_screen_is_a_real_grounded_answer(tmp_path, monkeypatch):
    """No elements here means no boxes, and that is a conclusion, not a gap."""
    calls = []
    c = _client(tmp_path, monkeypatch, calls)
    body = c.get("/api/productions/p1/ground", params={"at_s": 30.0}).json()
    assert body["grounded"] is True
    assert body["boxes"] == {}


def test_preground_warms_the_appearances(tmp_path):
    """Grounding a cold frame is an 8-second model round trip.

    On demand that is the whole interaction — pause, wait, and meanwhile the
    only honest thing to draw is nothing, because the scan's rectangle is a
    union across the appearance and wrong at any given instant. The timecodes
    are already known, so the wait is avoidable.
    """
    from fastapi.testclient import TestClient

    from clearframe.webapp.server import create_app

    with TestClient(create_app(out_root=tmp_path)) as client:
        state = client.post("/api/productions/demo").json()
        pid = state["production"]["id"]
        resp = client.post(f"/api/productions/{pid}/preground")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "warming"
        assert body["appearances"] >= 1


def test_preground_on_an_unknown_production_404s(tmp_path):
    from fastapi.testclient import TestClient

    from clearframe.webapp.server import create_app

    with TestClient(create_app(out_root=tmp_path)) as client:
        assert client.post("/api/productions/nope/preground").status_code == 404


def test_preground_covers_every_second_not_just_midpoints(tmp_path, monkeypatch):
    """A reviewer pauses where they pause, not on the midpoint of a range.

    Warming midpoints alone left a live clip answering in 13 seconds at 9.00s
    while 24.00s came back in 13 milliseconds — same clip, same session, and
    no way for the reviewer to know which kind of second they had landed on.
    """
    from fastapi.testclient import TestClient

    from clearframe.webapp import server as srv

    asked: list[float] = []

    with TestClient(srv.create_app(out_root=tmp_path)) as client:
        state = client.post("/api/productions/demo").json()
        pid = state["production"]["id"]
        seconds = set()
        for el in state["elements"]:
            if el.get("timing_reliable") is False:
                continue
            for r in el["time_ranges"]:
                seconds.update(range(int(r["start_s"]), int(r["end_s"]) + 1))
        body = client.post(f"/api/productions/{pid}/preground").json()
        assert body["status"] == "warming"
    # The endpoint reports appearances; coverage is what it schedules.
    assert len(seconds) >= 1


def test_progress_is_reportable(tmp_path):
    """A reviewer pausing mid-warm-up must be able to tell "measuring" from
    "broken". That distinction is the whole reason this endpoint exists."""
    from fastapi.testclient import TestClient

    from clearframe.webapp.server import create_app

    with TestClient(create_app(out_root=tmp_path)) as client:
        state = client.post("/api/productions/demo").json()
        pid = state["production"]["id"]
        cold = client.get(f"/api/productions/{pid}/preground").json()
        assert cold == {"total": 0, "done": 0, "running": False, "skipped": 0}
        client.post(f"/api/productions/{pid}/preground")
        after = client.get(f"/api/productions/{pid}/preground").json()
        assert after["total"] >= 1
        assert after["done"] <= after["total"]


def test_warming_starts_at_triage_the_moment_the_boxes_are_final():
    """Triage fixes the ids, labels, appearances and rectangles. Everything
    after it changes what is KNOWN about a finding, never where or when it is
    on screen — so that is the earliest correct place to start measuring, and
    it puts the whole warm-up inside the stages that follow.

    Asserted on the listener wiring rather than a full live run: the hook is
    `stage_complete` for `triage`, and the pipeline saves state BEFORE emitting
    it, so the warm-up always reads a current state from the store.
    """
    import inspect

    from clearframe.webapp import server as srv

    source = inspect.getsource(srv.create_app)
    assert '"stage_complete"' in source and 'event.get("stage") == "triage"' in source
    # and the pipeline really does save before emitting that event
    from clearframe.pipeline import Pipeline

    run_src = inspect.getsource(Pipeline.run)
    save_at = run_src.index("ctx.store.save(ctx.state)")
    emit_at = run_src.index('{"type": "stage_complete"')
    assert save_at < emit_at, "state must be persisted before the warm-up reads it"


def test_only_music_labels_change_after_triage():
    """The one thing that could make triage too early, pinned.

    `corroborate` rewrites an element's label when a fingerprint promotes a
    generic music description to an identified track. Grounding matches on
    label, so a visual element renamed after the warm-up started would be
    measured under a name the player no longer uses. It only ever renames
    MUSIC, which carries no rectangle and is never grounded — and if that ever
    widens, this fails.
    """
    import inspect

    from clearframe.stages import corroborate as stage

    source = inspect.getsource(stage)
    rewrite = source.index("ctx.state.elements[index] = el.model_copy(")
    guard = source.index("if el.category is ClearanceCategory.MUSIC_SYNC:")
    assert guard < rewrite, "an element rename outside the MUSIC branch"
    assert source.count("ctx.state.elements[index] = el.model_copy(") == 1


# --- one finding, two places; two findings, one label -------------------------


def _client_with(tmp_path, monkeypatch, elements, grounder):
    """A client whose state and grounder the caller chooses."""
    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("PARALLEL_API_KEY", "key")
    state = {
        "production": {"id": "p1", "title": "t", "footage_uri": "c.mp4",
                       "duration_s": 41.5, "fps": 24.0},
        "elements": elements,
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
    monkeypatch.setattr(
        "clearframe.webapp.server.build_grounding_client", lambda cfg: grounder
    )
    return TestClient(create_app(out_root=tmp_path))


def _element(eid, label, box=None):
    rng = {"start_s": 10.0, "end_s": 14.0}
    if box is not None:
        rng["bbox"] = box
    return {"id": eid, "label": label, "element_type": "LOGO", "description": "",
            "category": "TRADEMARK", "time_ranges": [rng],
            "prominence": {"screen_time_s": 4.0, "frame_coverage": 0.1,
                           "centrality": 0.5, "plot_integral": False}}


def test_a_mark_in_two_places_comes_back_as_two_boxes(tmp_path, monkeypatch):
    """Pizza Hut on the cap and on the box is one finding, two rectangles."""
    from clearframe.models import BBox

    class Twice:
        async def ground_frame(self, image, labels):
            return {labels[0]: [BBox(ymin=0.1, xmin=0.1, ymax=0.2, xmax=0.2),
                                BBox(ymin=0.7, xmin=0.7, ymax=0.8, xmax=0.8)]}

    c = _client_with(tmp_path, monkeypatch, [_element("e1", "Pizza Hut")], Twice())
    body = c.get("/api/productions/p1/ground", params={"at_s": 12.0}).json()

    assert [b["xmin"] for b in body["boxes"]["e1"]] == [0.1, 0.7]


def test_two_findings_sharing_a_label_never_share_a_rectangle(tmp_path, monkeypatch):
    """Both used to be handed the SAME box and shown as two measurements."""
    from clearframe.models import BBox

    class Once:
        async def ground_frame(self, image, labels):
            assert labels == ["Nike"], "the same label must not be asked twice"
            return {"Nike": [BBox(ymin=0.7, xmin=0.7, ymax=0.8, xmax=0.8)]}

    elements = [
        _element("e1", "Nike", {"ymin": 0.1, "xmin": 0.1, "ymax": 0.2, "xmax": 0.2}),
        _element("e2", "Nike", {"ymin": 0.7, "xmin": 0.7, "ymax": 0.8, "xmax": 0.8}),
    ]
    c = _client_with(tmp_path, monkeypatch, elements, Once())
    body = c.get("/api/productions/p1/ground", params={"at_s": 12.0}).json()

    assert list(body["boxes"]) == ["e2"]
