import pytest

from clearframe.dossier import auto_decisions, build_dossier
from clearframe.exporters.dossier_html import render_dossier_html
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context


async def _ran_state(tmp_path):
    ctx = demo_context(tmp_path)
    return await Pipeline(build_demo_pipeline()).run(ctx)


async def test_dossier_sorted_and_summarised(tmp_path):
    state = await _ran_state(tmp_path)
    state.decisions = auto_decisions(state)
    d = build_dossier(state, generated_at="2026-08-15T12:00:00Z")
    assert d.entries[0].element.id == "e1"  # highest score first
    assert d.summary["CRITICAL"] == 1 and d.summary["incomplete_research"] == 2


async def test_html_contains_citations_and_disclaimer(tmp_path):
    state = await _ran_state(tmp_path)
    state.decisions = auto_decisions(state)
    html = render_dossier_html(build_dossier(state, generated_at="2026-08-15T12:00:00Z"))
    assert "umusicpub.com" in html and "not legal advice" in html.lower()


async def test_dossier_stage_requires_decisions(tmp_path):
    from clearframe.stages.dossier import DossierStage, ReviewPendingError

    state = await _ran_state(tmp_path)
    stage = DossierStage(out_dir=tmp_path / "out")
    ctx = demo_context(tmp_path)
    ctx.state = state
    with pytest.raises(ReviewPendingError):
        await stage.run(ctx)
