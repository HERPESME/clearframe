from clearframe.models import (
    ClearanceCategory,
    ElementType,
    Prominence,
    RiskBand,
    TimeRange,
    TriagedElement,
)
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.territory import assess, worst_band


def make_element(category=ClearanceCategory.COPYRIGHT_ART, label="Street mural"):
    return TriagedElement(
        id="e5",
        label=label,
        element_type=ElementType.ARTWORK,
        description="",
        time_ranges=[TimeRange(start_s=30, end_s=36)],
        prominence=Prominence(
            screen_time_s=6, frame_coverage=0.3, centrality=0.5, plot_integral=False
        ),
        category=category,
    )


def test_broad_panorama_territory_steps_artwork_down():
    row = assess(make_element(), RiskBand.MEDIUM, "DE")
    assert row.band == RiskBand.LOW
    assert "UrhG" in row.authority


def test_narrow_panorama_territory_steps_artwork_up():
    row = assess(make_element(), RiskBand.MEDIUM, "FR")
    assert row.band == RiskBand.HIGH
    assert "non-commercial" in row.rationale


def test_us_covers_buildings_only_so_artwork_holds_baseline():
    row = assess(make_element(), RiskBand.MEDIUM, "US")
    assert row.band == RiskBand.MEDIUM
    assert "architecture only" in row.rationale


def test_trademark_does_not_vary_by_panorama():
    el = make_element(category=ClearanceCategory.TRADEMARK, label="Coca-Cola can")
    for territory in ("US", "DE", "FR"):
        assert assess(el, RiskBand.MEDIUM, territory).band == RiskBand.MEDIUM


def test_strong_publicity_territories_step_faces_up():
    el = make_element(category=ClearanceCategory.RIGHT_OF_PUBLICITY, label="Passerby")
    assert assess(el, RiskBand.LOW, "DE").band == RiskBand.MEDIUM
    assert assess(el, RiskBand.LOW, "JP").band == RiskBand.LOW


def test_unknown_territory_falls_back_to_baseline():
    row = assess(make_element(), RiskBand.HIGH, "ZZ")
    assert row.band == RiskBand.HIGH and row.authority == ""


def test_bands_never_run_off_the_ends():
    assert assess(make_element(), RiskBand.LOW, "DE").band == RiskBand.LOW
    assert assess(make_element(), RiskBand.CRITICAL, "FR").band == RiskBand.CRITICAL


def test_worst_band_is_what_a_worldwide_release_underwrites():
    el = make_element()
    rows = [assess(el, RiskBand.MEDIUM, t) for t in ("US", "DE", "FR")]
    assert worst_band(rows) == RiskBand.HIGH


async def test_pipeline_bands_the_mural_differently_per_territory(tmp_path):
    state = await Pipeline(build_demo_pipeline()).run(demo_context(tmp_path))
    bands = {r.territory: r.band for r in state.territory_risk["e5"]}
    assert bands["US"] == RiskBand.MEDIUM
    assert bands["DE"] == RiskBand.LOW
    assert bands["FR"] == RiskBand.HIGH
    assert state.territories == ["US", "DE", "FR"]
