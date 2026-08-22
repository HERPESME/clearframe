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
    assert types.count("stage_start") == 11
    assert types.count("stage_complete") == 11
    assert "script_mentions" in types and "drift_computed" in types
    assert "scan_found" in types and "audit_found" in types
    assert "research_planned" in types
    # 8 findings, but the disputed identity (e8) is never dispatched to research
    assert types.count("research_start") == 7
    assert types.count("research_blocked") == 1
    assert "corroboration_done" in types and "identity_conflict" in types
    assert "territory_assessed" in types and "freshness_checked" in types
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
