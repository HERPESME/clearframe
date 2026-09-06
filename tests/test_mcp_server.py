import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from clearframe.mcp.server import build_server


@pytest.fixture
def server(tmp_path):
    return build_server(out_root=tmp_path)


def _payload(result):
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


async def test_tools_are_registered(server):
    tools = {t.name for t in await server.list_tools()}
    assert tools == {
        "run_clearance",
        "get_status",
        "list_findings",
        "get_finding",
        "verify_identities",
        "territory_report",
        "check_freshness",
        "list_licences",
        "check_coverage",
        "record_decision",
        "generate_dossier",
    }


async def test_full_clearance_flow(server, tmp_path):
    run = _payload(
        await server.call_tool(
            "run_clearance",
            {"footage_uri": "demo://salted-scene", "title": "Golden Hour"},
        )
    )
    assert run["findings"] == 8 and run["bands"]["CRITICAL"] == 1
    pid = run["production_id"]

    findings = _payload(await server.call_tool("list_findings", {"production_id": pid}))
    assert len(findings["findings"]) == 8
    top = findings["findings"][0]
    assert top["band"] == "CRITICAL"

    detail = _payload(
        await server.call_tool(
            "get_finding", {"production_id": pid, "element_id": top["id"]}
        )
    )
    assert detail["research"]["basis"], "evidence citations must be exposed"

    for f in findings["findings"]:
        _payload(
            await server.call_tool(
                "record_decision",
                {
                    "production_id": pid,
                    "element_id": f["id"],
                    "action": "license",
                    "note": "via mcp",
                    "role": "legal",
                },
            )
        )

    dossier = _payload(await server.call_tool("generate_dossier", {"production_id": pid}))
    assert "dossier.html" in dossier["artifacts"]
    assert (tmp_path / "artifacts" / pid / "dossier.html").exists()

    status = _payload(await server.call_tool("get_status", {"production_id": pid}))
    assert status["stage_status"]["review"] == "complete"
    assert status["pending"] == []


async def test_editor_role_is_error(server):
    _payload(
        await server.call_tool(
            "run_clearance", {"footage_uri": "demo://salted-scene", "title": "T"}
        )
    )
    with pytest.raises(ToolError, match="cannot record decisions"):
        await server.call_tool(
            "record_decision",
            {
                "production_id": "demo",
                "element_id": "e1",
                "action": "license",
                "note": "",
                "role": "editor",
            },
        )


async def test_dossier_before_decisions_is_error(server):
    _payload(
        await server.call_tool(
            "run_clearance", {"footage_uri": "demo://salted-scene", "title": "T"}
        )
    )
    with pytest.raises(ToolError, match="e1"):
        await server.call_tool("generate_dossier", {"production_id": "demo"})


async def test_unknown_production_is_error(server):
    with pytest.raises(ToolError, match="Unknown production"):
        await server.call_tool("get_status", {"production_id": "nope"})


async def test_live_without_env_is_actionable_error(server, monkeypatch):
    for var in ("GOOGLE_CLOUD_PROJECT", "PARALLEL_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ToolError, match="GOOGLE_CLOUD_PROJECT"):
        await server.call_tool(
            "run_clearance", {"footage_uri": "clip.mp4", "title": "T"}
        )
