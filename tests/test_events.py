import json

import pytest
from fastapi.testclient import TestClient

from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.webapp.server import create_app


async def test_pipeline_emits_stage_and_agent_events(tmp_path):
    events = []
    ctx = demo_context(tmp_path)
    ctx.listener = events.append
    await Pipeline(build_demo_pipeline()).run(ctx)
    types = [e["type"] for e in events]
    assert types.count("stage_start") == 13
    assert types.count("stage_complete") == 13
    assert "script_mentions" in types and "drift_computed" in types
    assert "scan_found" in types and "audit_found" in types
    assert "research_planned" in types

    # The complete footage-derived report lands BEFORE research starts. On live
    # footage that is ~90s into a run whose deep rights lookups take minutes.
    preview = next(e for e in events if e["type"] == "preview_ready")
    assert preview["count"] == 8
    assert types.index("preview_ready") < types.index("research_planned")
    assert all(
        f["band"] and f["tier"] and f["start_s"] is not None
        for f in preview["findings"]
    )
    assert preview["resolved_now"] >= 1
    # 8 findings routed down the ladder: 5 deep + 1 search are dispatched;
    # the background face resolves by statute and the disputed identity (e8)
    # is never dispatched at all.
    assert types.count("research_start") == 6
    assert types.count("research_blocked") == 1
    assert types.count("research_resolved") == 2  # statute + blocked
    planned = next(e for e in events if e["type"] == "research_planned")
    assert planned["deep_runs"] == 5
    assert planned["routes"]["STATUTE"] == 1
    assert "corroboration_done" in types and "identity_conflict" in types
    assert "territory_assessed" in types and "freshness_checked" in types
    assert "coverage_checked" in types and "coverage_gap" in types
    assert types.count("case_ruled") == 5
    ruled = [e for e in events if e["type"] == "case_ruled"]
    assert any(e["holding"] == "clear_required" for e in ruled)


@pytest.fixture
def client(tmp_path):
    app = create_app(out_root=tmp_path)
    with TestClient(app) as c:
        yield c


def test_paced_demo_run_streams_events_over_sse(client):
    resp = client.post("/api/productions/demo", json={"pace_s": 0.01})
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    received = []
    with client.stream("GET", "/api/productions/demo/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                received.append(json.loads(line[len("data: ") :]))
                if received[-1]["type"] == "run_complete":
                    break
    types = [e["type"] for e in received]
    assert "stage_start" in types and "case_ruled" in types
    assert types[-1] == "run_complete"

    state = client.get("/api/productions/demo").json()
    assert len(state["elements"]) == 8


def test_events_without_run_404(client):
    assert client.get("/api/productions/demo/events").status_code == 404


def test_a_queued_run_streams_immediately_rather_than_404ing(tmp_path, monkeypatch):
    """The regression that made Mission Control sit at "Standing by" in prod.

    The client opens its EventSource the instant the upload responds. In one
    process that was safe: `create_production` created the event queue
    synchronously before returning, so the endpoint could never 404 for a run
    that had just started.

    Moving the producer to a worker container broke that invariant. The run is
    QUEUED when the upload responds — a different container, several seconds of
    cold start away from writing its first event — so the stream 404'd, and
    `MissionControl.tsx` closes on error and never retries. The analysis ran to
    completion with the screen showing nothing.

    Observed on the deployed site: one 404 on `/events`, and no second attempt.
    """
    from fastapi.testclient import TestClient

    from clearframe.webapp.server import create_app

    monkeypatch.setenv("CLEARFRAME_MODE", "live")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "a-project")
    monkeypatch.setenv("PARALLEL_API_KEY", "a-key")

    class _NeverRuns:
        """A queue that accepts the job and does nothing — exactly the window
        between the upload responding and the worker starting."""

        async def enqueue(self, job):
            return job.production_id

    monkeypatch.setattr(
        "clearframe.webapp.server.build_queue", lambda cfg, runner: _NeverRuns()
    )
    monkeypatch.setattr(
        "clearframe.webapp.server.probe_media", lambda path: (10.0, 24.0)
    )
    client = TestClient(create_app(out_root=tmp_path))

    resp = client.post(
        "/api/productions",
        files={"file": ("clip.mp4", b"\x00" * 2048, "video/mp4")},
        data={"title": "Queued", "production_id": "queued1"},
    )
    assert resp.status_code == 200

    with client.stream("GET", "/api/productions/queued1/events") as stream:
        assert stream.status_code == 200, (
            "the client would close the stream and never reopen it"
        )
