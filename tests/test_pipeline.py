from clearframe.models import RiskBand
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context


async def test_demo_pipeline_end_to_end(tmp_path):
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline()).run(ctx)
    assert len(state.elements) == 8
    assert state.risk["e1"].band == RiskBand.CRITICAL  # Weeknd track
    assert state.research["e5"].status == "incomplete"  # mural
    assert state.risk["e6"].de_minimis is True  # passerby face
    assert all(state.remediation[e.id] for e in state.elements)
    assert state.stage_status["review"] == "awaiting"


async def test_research_cap_bounds_only_the_expensive_rung(tmp_path):
    """The spend cap exists to bound Parallel Task runs on long footage. The
    free rungs cost nothing, so dropping them for budget would lose findings
    for no saving."""
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline(max_research=2)).run(ctx)
    assert len(state.research) == 8

    deep = [r for r in state.routes.values() if r.tier.value == "DEEP"]
    assert len(deep) == 2, "cap must bound deep runs"

    # budget goes to the most prominent elements (screen time desc)
    researched_ids = {
        r.element_id for r in state.research.values() if r.status == "complete"
    }
    assert "e3" in researched_ids and "e1" in researched_ids  # 15s hoodie, 12s song

    # overflow is reported honestly, never silently dropped
    overflow = [
        r for r in state.routes.values()
        if r.tier.value == "BLOCKED" and "spend cap" in r.rationale
    ]
    assert overflow, "deep runs beyond the cap must say so"
    assert all(state.research[r.element_id].status == "incomplete" for r in overflow)


async def test_pipeline_resumes_skipping_complete_stages(tmp_path):
    ctx = demo_context(tmp_path)
    p = Pipeline(build_demo_pipeline())
    await p.run(ctx)
    ctx.state.detections = []  # would change results if scan re-ran
    state = await p.run(ctx)  # all stages complete -> no-op
    assert len(state.elements) == 8
