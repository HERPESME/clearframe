from clearframe.models import (
    ClearanceCategory,
    ElementType,
    LicensingPosture,
    Prominence,
    ResearchResult,
    RiskBand,
    TimeRange,
    TriagedElement,
)
from clearframe.scoring import band_for, score_element


def make_element(**kw):
    base = dict(
        id="e1",
        label="x",
        element_type=ElementType.MUSIC,
        description="",
        time_ranges=[TimeRange(start_s=0, end_s=12)],
        category=ClearanceCategory.MUSIC_SYNC,
        prominence=Prominence(
            screen_time_s=12, frame_coverage=0.0, centrality=1.0, plot_integral=True
        ),
    )
    base.update(kw)
    return TriagedElement(**base)


def make_research(posture=LicensingPosture.LITIGIOUS, status="complete"):
    return ResearchResult(
        element_id="e1",
        owner="X Corp",
        owner_confidence="high",
        licensing_contact="a@b.c",
        licensing_posture=posture,
        litigation_history=[],
        estimated_license_cost_band=None,
        basis=[],
        status=status,
    )


def test_prominent_litigious_song_is_critical():
    r = score_element(make_element(), make_research())
    assert r.score == 70 and r.band == RiskBand.CRITICAL


def test_de_minimis_background_face_capped_low():
    el = make_element(
        element_type=ElementType.FACE,
        category=ClearanceCategory.RIGHT_OF_PUBLICITY,
        prominence=Prominence(
            screen_time_s=1.2, frame_coverage=0.03, centrality=0.2, plot_integral=False
        ),
    )
    r = score_element(el, make_research(LicensingPosture.UNKNOWN))
    assert r.de_minimis is True and r.band == RiskBand.LOW


def test_missing_research_is_scored_at_worst_case_not_discounted():
    """Failing to look is not evidence that there is nothing to find.

    This used to assert 0.7 — UNKNOWN's factor — so a finding nobody could
    research scored 30% below its own provisional band. See
    tests/test_failed_research_posture.py for the full case.
    """
    r = score_element(make_element(), None)
    assert r.factors["posture_factor"] == 1.0


def test_band_boundaries():
    assert band_for(19) == RiskBand.LOW and band_for(20) == RiskBand.MEDIUM
    assert band_for(44) == RiskBand.MEDIUM and band_for(45) == RiskBand.HIGH
    assert band_for(69) == RiskBand.HIGH and band_for(70) == RiskBand.CRITICAL
