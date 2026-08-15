from pathlib import Path

from clearframe.drift import compute_drift
from clearframe.integrations.gemini_client import FixtureGeminiClient
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context

FIXTURES = Path("src/clearframe/integrations/fixtures")


async def test_fixture_script_scan_returns_mentions():
    mentions = await FixtureGeminiClient(FIXTURES).scan_script("any text")
    assert len(mentions) == 3
    assert any("Blinding Lights" in m.label for m in mentions)


async def test_pipeline_computes_drift(tmp_path):
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline()).run(ctx)
    assert len(state.script_mentions) == 3
    assert state.drift is not None
    # hoodie, mural, TV broadcast were never in the script; faces excluded
    assert set(state.drift.unscripted_element_ids) == {"e3", "e5", "e7"}
    assert state.drift.scripted_not_seen == []


def test_compute_drift_reports_scripted_but_unseen():
    from clearframe.models import (
        ClearanceCategory,
        ElementType,
        Prominence,
        ScriptMention,
        TimeRange,
        TriagedElement,
    )

    mentions = [
        ScriptMention(label="Vintage jukebox", element_type=ElementType.ARTWORK, scene="INT. BAR")
    ]
    elements = [
        TriagedElement(
            id="a",
            label="Neon beer sign",
            element_type=ElementType.LOGO,
            description="",
            category=ClearanceCategory.TRADEMARK,
            time_ranges=[TimeRange(start_s=0, end_s=1)],
            prominence=Prominence(
                screen_time_s=1, frame_coverage=0.1, centrality=0.5, plot_integral=False
            ),
        )
    ]
    drift = compute_drift(mentions, elements)
    assert drift.unscripted_element_ids == ["a"]
    assert drift.scripted_not_seen == ["Vintage jukebox"]
