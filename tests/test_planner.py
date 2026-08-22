from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.planner import EST_COST, plan_research


async def test_planner_assigns_tiers_by_policy(tmp_path):
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline()).run(ctx)
    plan = state.research_plan
    assert len(plan) == 8
    assert plan["e1"].processor == "pro"  # music: split ownership chains
    assert plan["e5"].processor == "ultra"  # unknown-artist mural: deep dig
    assert plan["e2"].processor == "lite"  # famous mark, trivial ownership
    assert plan["e3"].processor == "lite"
    assert plan["e6"].processor == "base"
    assert all(p.rationale for p in plan.values())
    total = sum(p.est_cost_usd for p in plan.values())
    assert total == sum(EST_COST[p.processor] for p in plan.values())


def test_plan_research_unknown_artwork_gets_ultra():
    from clearframe.models import (
        ClearanceCategory,
        ElementType,
        Prominence,
        TimeRange,
        TriagedElement,
    )

    el = TriagedElement(
        id="x",
        label="Street mural (unknown artist)",
        element_type=ElementType.ARTWORK,
        description="",
        category=ClearanceCategory.COPYRIGHT_ART,
        time_ranges=[TimeRange(start_s=0, end_s=1)],
        prominence=Prominence(
            screen_time_s=1, frame_coverage=0.1, centrality=0.1, plot_integral=False
        ),
    )
    plan = plan_research([el])
    assert plan["x"].processor == "ultra"
