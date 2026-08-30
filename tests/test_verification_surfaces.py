"""The new evidence (identity, territory, live signals) must reach every transport."""

import json

import pytest
from fastapi.testclient import TestClient

from clearframe.mcp.server import build_server
from clearframe.webapp.server import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(out_root=tmp_path)) as c:
        c.post("/api/productions/demo")
        yield c


def test_state_endpoint_carries_the_new_evidence(client):
    state = client.get("/api/productions/demo").json()
    assert state["corroboration"]["e8"]["verdict"] == "CONFLICTED"
    assert state["corroboration"]["e3"]["verdict"] == "CORROBORATED"
    assert state["territories"] == ["US", "DE", "FR"]
    bands = {t["territory"]: t["band"] for t in state["territory_risk"]["e5"]}
    assert bands == {"US": "MEDIUM", "DE": "LOW", "FR": "HIGH"}
    assert any(s["material"] for s in state["freshness"]["e3"])


def test_freshness_endpoint_reruns_the_live_search(client):
    resp = client.post("/api/productions/demo/freshness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["holders"] >= 2 and body["material_signals"] >= 1
    audit = client.get("/api/productions/demo").json()["audit_log"]
    assert any(a["event"] == "freshness_checked" for a in audit)


def test_freshness_endpoint_unknown_production_404(client):
    assert client.post("/api/productions/nope/freshness").status_code == 404


async def _mcp(tmp_path):
    server = build_server(out_root=tmp_path)
    await server.call_tool(
        "run_clearance", {"footage_uri": "demo://salted-scene", "title": "T"}
    )
    return server


async def _call(server, name, args):
    result = await server.call_tool(name, args)
    return json.loads(result.content[0].text)


async def test_mcp_exposes_the_new_tools(tmp_path):
    server = await _mcp(tmp_path)
    names = {t.name for t in await server.list_tools()}
    assert {"verify_identities", "territory_report", "check_freshness"} <= names


async def test_mcp_verify_identities_reports_the_block(tmp_path):
    server = await _mcp(tmp_path)
    body = await _call(server, "verify_identities", {"production_id": "demo"})
    assert body["conflicts"] == 1
    assert body["blocked_from_research"] == ["e8"]
    verdicts = {r["id"]: r["verdict"] for r in body["findings"]}
    assert verdicts["e2"] == "CORROBORATED"


async def test_mcp_territory_report_bands_per_jurisdiction(tmp_path):
    server = await _mcp(tmp_path)
    body = await _call(server, "territory_report", {"production_id": "demo"})
    assert body["territories"] == ["US", "DE", "FR"]
    mural = next(f for f in body["findings"] if f["id"] == "e5")
    assert mural["by_territory"]["DE"]["band"] == "LOW"
    assert "UrhG" in mural["by_territory"]["DE"]["authority"]


async def test_mcp_get_finding_returns_the_full_evidence_chain(tmp_path):
    server = await _mcp(tmp_path)
    body = await _call(
        server, "get_finding", {"production_id": "demo", "element_id": "e3"}
    )
    assert body["corroboration"]["verdict"] == "CORROBORATED"
    assert len(body["territory_risk"]) == 3
    assert any(s["material"] for s in body["freshness"])


async def test_mcp_list_findings_includes_identity(tmp_path):
    server = await _mcp(tmp_path)
    body = await _call(server, "list_findings", {"production_id": "demo"})
    identities = {f["id"]: f["identity"] for f in body["findings"]}
    assert identities["e8"] == "CONFLICTED"


async def test_mcp_check_freshness_runs_and_audits(tmp_path):
    server = await _mcp(tmp_path)
    body = await _call(server, "check_freshness", {"production_id": "demo"})
    assert body["checked"] >= 2
    assert "e3" in body["material_signals"]


async def test_mcp_reports_which_rung_answered_each_finding(tmp_path):
    """A finding resolved for free is a documented position, so an MCP client
    must be able to read the reasoning and the required action — not just see
    that no research ran."""
    server = await _mcp(tmp_path)

    listed = await _call(server, "list_findings", {"production_id": "demo"})
    tiers = {f["id"]: f["resolved_by"] for f in listed["findings"]}
    assert tiers["e6"] == "STATUTE"
    assert tiers["e2"] == "SEARCH"
    assert tiers["e8"] == "BLOCKED"

    face = await _call(
        server, "get_finding", {"production_id": "demo", "element_id": "e6"}
    )
    route = face["route"]
    assert route["tier"] == "STATUTE"
    assert "release" in route["disposition"].lower()
    assert route["basis"]
    assert route["est_cost_usd"] == 0.0
