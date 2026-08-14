from clearframe.models import (
    ClearanceCategory,
    ElementType,
    LicensingPosture,
    Production,
    Prominence,
    ResearchResult,
    RiskAssessment,
    RiskBand,
    TimeRange,
    TriagedElement,
)
from clearframe.remediation import draft_options

PROD = Production(id="p1", title="Golden Hour", footage_uri="demo://x", duration_s=62)


def _el(cat=ClearanceCategory.TRADEMARK, t=ElementType.LOGO):
    return TriagedElement(
        id="e1",
        label="Nike hoodie swoosh",
        element_type=t,
        description="",
        category=cat,
        time_ranges=[TimeRange(start_s=8, end_s=18)],
        prominence=Prominence(
            screen_time_s=15, frame_coverage=0.12, centrality=0.7, plot_integral=False
        ),
    )


def _res():
    return ResearchResult(
        element_id="e1",
        owner="Nike, Inc.",
        owner_confidence="high",
        licensing_contact="tm@nike.com",
        licensing_posture=LicensingPosture.LITIGIOUS,
        litigation_history=[],
        estimated_license_cost_band="denied",
        basis=[],
        status="complete",
    )


def _risk(band=RiskBand.HIGH, dm=False):
    return RiskAssessment(element_id="e1", score=50, band=band, factors={}, de_minimis=dm)


def test_license_email_contains_production_and_timecode():
    opts = draft_options(_el(), _res(), _risk(), PROD)
    lic = next(o for o in opts if o.kind == "license")
    assert "Golden Hour" in lic.detail and "01:00:08:00" in lic.detail


def test_music_never_gets_blur():
    el = _el(cat=ClearanceCategory.MUSIC_SYNC, t=ElementType.MUSIC)
    kinds = [o.kind for o in draft_options(el, _res(), _risk(RiskBand.CRITICAL), PROD)]
    assert "blur" not in kinds and "reshoot" in kinds


def test_de_minimis_gets_fair_use_memo():
    kinds = [o.kind for o in draft_options(_el(), _res(), _risk(RiskBand.LOW, dm=True), PROD)]
    assert "fair_use_memo" in kinds
