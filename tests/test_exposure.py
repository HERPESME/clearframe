"""On-screen exposure that is not intellectual property at all.

A creator filming at home who leaves a delivery label, a bank statement or a
laptop screen in frame has a real problem that no clearance tool looks for,
because nothing is being infringed. It is the purest unknown-unknown in the
threat surface — and it comes free from a scan we already run.

Data-protection authorities have issued explicit guidance that publishing
children's images without parental consent breaches the GDPR, so minors are
treated as the top severity everywhere rather than scaled by jurisdiction.
"""

import pytest

from clearframe.exposure import assess_exposure, assess_all_exposures, summarise_exposures
from clearframe.models import (
    BBox,
    ExposureFinding,
    ExposureKind,
    RiskBand,
    TimeRange,
)


def ex(kind, start=45.0, end=52.0, description="", bbox=None):
    return ExposureFinding(
        id="x1",
        kind=kind,
        description=description or f"{kind.value} visible on screen",
        time_ranges=[TimeRange(start_s=start, end_s=end)],
        bbox=bbox,
    )


# ------------------------------------------------------------------ severity
def test_a_minor_is_the_top_severity_in_every_jurisdiction():
    """DPAs have issued explicit guidance on children's images. This does not
    get scaled down because the release territory is permissive."""
    for territory in ("US", "GB", "DE", "IN", "ZZ"):
        assessed = assess_exposure(ex(ExposureKind.MINOR), territory)
        assert assessed.band is RiskBand.CRITICAL, territory


def test_identifying_data_outranks_an_unread_screen():
    home = assess_exposure(ex(ExposureKind.PERSONAL_DATA), "GB")
    screen = assess_exposure(ex(ExposureKind.SCREEN_CONTENT), "GB")
    assert home.score > screen.score


def test_a_gdpr_territory_raises_the_band_over_a_us_release():
    """The same frame, different regime: in the US an address on screen is
    embarrassing; in the EU it is processing of personal data."""
    uk = assess_exposure(ex(ExposureKind.PERSONAL_DATA), "GB")
    us = assess_exposure(ex(ExposureKind.PERSONAL_DATA), "US")
    assert uk.score > us.score
    assert "GDPR" in uk.regime


def test_the_regime_is_named_per_territory():
    assert "DPDP" in assess_exposure(ex(ExposureKind.PERSONAL_DATA), "IN").regime
    assert "LGPD" in assess_exposure(ex(ExposureKind.PERSONAL_DATA), "BR").regime


def test_an_unknown_territory_degrades_without_raising():
    a = assess_exposure(ex(ExposureKind.DOCUMENT), "ZZ")
    assert a.band in set(RiskBand)
    assert a.regime


# -------------------------------------------------------------------- remedy
def test_every_remedy_carries_a_timecode_to_act_on():
    for kind in ExposureKind:
        a = assess_exposure(ex(kind, 45.0, 52.0), "GB")
        assert "00:45" in a.remedy and "00:52" in a.remedy, kind


def test_a_boxed_exposure_says_it_can_be_masked_in_place():
    boxed = ex(ExposureKind.VEHICLE_PLATE,
               bbox=BBox(ymin=0.4, xmin=0.3, ymax=0.5, xmax=0.6))
    assert "mask" in assess_exposure(boxed, "GB").remedy.lower()


def test_an_unboxed_exposure_does_not_promise_a_box():
    plain = assess_exposure(ex(ExposureKind.VEHICLE_PLATE), "GB")
    assert "mask the region" not in plain.remedy.lower()


# --------------------------------------------------------------------- batch
def test_assess_all_ranks_worst_first():
    findings = [
        ex(ExposureKind.SCREEN_CONTENT),
        ex(ExposureKind.MINOR),
        ex(ExposureKind.PERSONAL_DATA),
    ]
    ranked = assess_all_exposures(findings, ["GB"])
    scores = [a.score for a in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0].kind is ExposureKind.MINOR


def test_the_worst_territory_governs_a_multi_territory_release():
    """A worldwide release must be underwritten at the strictest standard."""
    one = assess_all_exposures([ex(ExposureKind.PERSONAL_DATA)], ["US"])[0]
    both = assess_all_exposures([ex(ExposureKind.PERSONAL_DATA)], ["US", "DE"])[0]
    assert both.score >= one.score
    assert both.territory == "DE"


def test_summary_counts_by_band_and_names_the_worst():
    findings = [ex(ExposureKind.MINOR), ex(ExposureKind.SCREEN_CONTENT)]
    s = summarise_exposures(assess_all_exposures(findings, ["GB"]))
    assert s["total"] == 2
    assert s["CRITICAL"] == 1
    assert s["worst_kind"] == "MINOR"


def test_nothing_found_summarises_cleanly():
    s = summarise_exposures([])
    assert s["total"] == 0 and s["worst_kind"] is None


def test_a_tie_on_severity_still_reports_the_strictest_regime():
    """Found by reading a live run. MINOR is deliberately not scaled by
    jurisdiction, so every territory scored 100 and `max` returned whichever
    came first — reporting "State right of publicity" for a child in a release
    that included Germany and India. The severity was right and the regime was
    misleading, which is worse than useless: it names the wrong instrument."""
    a = assess_all_exposures([ex(ExposureKind.MINOR)], ["US", "DE", "IN"])[0]
    assert a.score == 100
    assert a.territory == "DE", a.territory
    assert "GDPR" in a.regime


def test_the_strictest_regime_wins_regardless_of_territory_order():
    for order in (["US", "DE"], ["DE", "US"], ["IN", "US"], ["US", "IN"]):
        a = assess_all_exposures([ex(ExposureKind.MINOR)], order)[0]
        assert a.territory != "US", order
