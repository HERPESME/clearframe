from pathlib import Path

from clearframe.integrations.court_client import CourtCase, FixtureCourtClient
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context

FIXTURES = Path("src/clearframe/integrations/fixtures")


async def _ran_state(tmp_path):
    ctx = demo_context(tmp_path)
    return await Pipeline(build_demo_pipeline()).run(ctx)


async def test_fixture_client_loads_song_case(tmp_path):
    state = await _ran_state(tmp_path)
    el = next(e for e in state.elements if e.id == "e1")
    case = CourtCase(
        element=el,
        research=state.research["e1"],
        risk=state.risk["e1"],
        production=state.production,
    )
    opinion = await FixtureCourtClient(FIXTURES).try_case(case)
    assert opinion is not None
    assert opinion.holding == "clear_required" and opinion.confidence == "high"
    sides = {b.side for b in opinion.briefs}
    assert sides == {"counsel", "advocate"}
    all_citations = [p.citation for b in opinion.briefs for p in b.precedents]
    assert any("504" in c or "F.3d" in c or "F. Supp" in c for c in all_citations)


async def test_court_stage_tries_contested_findings_only(tmp_path):
    state = await _ran_state(tmp_path)
    # MEDIUM+ = e1..e5; e6 (de-minimis LOW) and e7 (LOW) never go to court
    assert set(state.court.keys()) == {"e1", "e2", "e3", "e4", "e5"}
    assert state.court["e5"].holding == "escalate"
    assert state.court["e2"].holding == "defensible"


async def test_court_never_changes_risk_scores(tmp_path):
    state = await _ran_state(tmp_path)
    # deterministic floor untouched: same scores as before the court existed
    assert state.risk["e1"].score == 70
    assert state.risk["e3"].score == 46


async def test_dossier_html_renders_court_opinions(tmp_path):
    from clearframe.dossier import auto_decisions, build_dossier
    from clearframe.exporters.dossier_html import render_dossier_html

    state = await _ran_state(tmp_path)
    state.decisions = auto_decisions(state)
    html = render_dossier_html(build_dossier(state, generated_at="2026-08-15T12:00:00Z"))
    assert "Ringgold" in html and "Clearance Court" in html
    assert "de minimis doctrine is inapplicable" in html  # extracted precedent quote


async def test_mcp_get_finding_exposes_opinion(tmp_path):
    import json

    from clearframe.mcp.server import build_server

    server = build_server(out_root=tmp_path)
    await server.call_tool(
        "run_clearance", {"footage_uri": "demo://salted-scene", "title": "T"}
    )
    result = await server.call_tool(
        "get_finding", {"production_id": "demo", "element_id": "e1"}
    )
    detail = json.loads(result.content[0].text)
    assert detail["court"]["holding"] == "clear_required"


async def test_live_court_falls_back_when_primary_model_404s(tmp_path):
    # Live-observed 2026-08-19: gemini-3-pro-preview 404s in some projects; the
    # court must fall back to the fallback model instead of silently returning
    # no opinion for every contested finding.
    import json as jsonlib

    from clearframe.integrations.court_client import LiveCourtClient

    state = await _ran_state(tmp_path)
    el = next(e for e in state.elements if e.id == "e1")
    case = CourtCase(
        element=el,
        research=state.research["e1"],
        risk=state.risk["e1"],
        production=state.production,
    )

    calls = []

    class _Resp:
        def __init__(self, text):
            self.text = text

    class _Models:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "gemini-3-pro-preview":
                raise RuntimeError("404 NOT_FOUND: Publisher model not found")
            payload = (
                {"argument": "a", "precedents": []}
                if "precedents" in jsonlib.dumps(getattr(config, "response_schema", {}))
                or (isinstance(config, dict))
                else {}
            )
            if "JUDGE" in contents[0] or "judge" in contents[0].lower():
                payload = {"holding": "defensible", "confidence": "medium", "reasoning": "r"}
            return _Resp(jsonlib.dumps(payload))

    class _Client:
        models = _Models()

    client = LiveCourtClient(
        project="p", location="us-central1", model="gemini-3-pro-preview",
        client_factory=lambda: _Client(),
    )
    opinion = await client.try_case(case)
    assert opinion is not None
    assert opinion.holding == "defensible"
    assert "gemini-2.5-pro" in calls
