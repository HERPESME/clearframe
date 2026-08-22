"""The report ships before ownership research finishes."""

import pytest

from clearframe.models import RiskBand
from clearframe.pipeline import ANALYSIS_STAGES, Pipeline, build_demo_pipeline, demo_context
from clearframe.scoring import provisional_score, score_element


async def _run(tmp_path):
    ctx = demo_context(tmp_path)
    return await Pipeline(build_demo_pipeline()).run(ctx)


def test_preview_runs_before_research():
    assert ANALYSIS_STAGES.index("preview") < ANALYSIS_STAGES.index("research")
    assert ANALYSIS_STAGES.index("corroborate") < ANALYSIS_STAGES.index("preview")


async def test_every_finding_is_in_the_preview_with_timestamps(tmp_path):
    state = await _run(tmp_path)
    assert len(state.preview) == len(state.elements)
    for f in state.preview:
        assert f.time_ranges, "a report without timecodes cannot be worked from"
        assert f.provisional_band in set(RiskBand)
        assert f.route_tier


async def test_the_preview_is_ordered_by_exposure(tmp_path):
    state = await _run(tmp_path)
    scores = [f.provisional_score for f in state.preview]
    assert scores == sorted(scores, reverse=True)


async def test_provisional_risk_is_an_upper_bound_not_a_guess(tmp_path):
    """Pinning the posture factor at its worst case means the band can only
    fall once research lands — never a reassuring number that turns out worse."""
    state = await _run(tmp_path)
    for el in state.elements:
        final = score_element(el, state.research.get(el.id))
        assert provisional_score(el) >= final.score


async def test_findings_needing_no_research_are_already_actionable(tmp_path):
    """The point of the preview: the free rungs are DONE, with the required
    action attached, while the deep runs are still going."""
    state = await _run(tmp_path)
    settled = [f for f in state.preview if not f.awaiting_research]
    assert settled, "demo scene must contain at least one settled finding"
    assert all(f.disposition for f in settled)


async def test_the_preview_carries_identity_and_territory(tmp_path):
    state = await _run(tmp_path)
    by_id = {f.element_id: f for f in state.preview}
    assert by_id["e1"].identity is not None            # fingerprinted music
    assert by_id["e8"].identity.value == "CONFLICTED"  # disputed Adidas
    mural = by_id["e5"]
    assert {t.territory for t in mural.territory} == {"US", "DE", "FR"}
    assert all(t.authority for t in mural.territory)


async def test_research_reuses_the_routes_the_preview_published(tmp_path):
    """A producer who acts on the preview must not find the pipeline quietly
    decided something else a minute later."""
    state = await _run(tmp_path)
    for f in state.preview:
        assert state.routes[f.element_id].tier is f.route_tier
