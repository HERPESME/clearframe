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


async def test_research_cap_marks_overflow_incomplete(tmp_path):
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline(max_research=2)).run(ctx)
    complete = [r for r in state.research.values() if r.status == "complete"]
    incomplete = [r for r in state.research.values() if r.status == "incomplete"]
    assert len(state.research) == 8
    assert len(complete) == 2 and len(incomplete) == 6
    # budget goes to the most prominent elements (screen time desc)
    researched_ids = {r.element_id for r in complete}
    assert "e3" in researched_ids and "e1" in researched_ids  # 15s hoodie, 12s song


async def test_pipeline_resumes_skipping_complete_stages(tmp_path):
    ctx = demo_context(tmp_path)
    p = Pipeline(build_demo_pipeline())
    await p.run(ctx)
    ctx.state.detections = []  # would change results if scan re-ran
    state = await p.run(ctx)  # all stages complete -> no-op
    assert len(state.elements) == 8
