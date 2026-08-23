"""A paint-out is priced per shot, and the finding has more than one.

The dossier showed "$300-$800/shot" for a tattoo appearing in seven separate
shots. The label is honest and the number is useless: the figure a producer
budgets against is the total, and we already counted the appearances.
"""

from clearframe.models import (
    ClearanceCategory, ElementType, Prominence, RiskAssessment, RiskBand,
    TimeRange, TriagedElement,
)
from clearframe.models import Production, ResearchResult
from clearframe.remediation import draft_options


def el(appearances: int, coverage: float = 0.03):
    return TriagedElement(
        id="1", label="Stu's Face Tattoo", element_type=ElementType.TATTOO,
        description="",
        time_ranges=[
            TimeRange(start_s=float(i * 5 + 1), end_s=float(i * 5 + 3))
            for i in range(appearances)
        ],
        prominence=Prominence(screen_time_s=10.0, frame_coverage=coverage,
                              centrality=0.6, plot_integral=True),
        category=ClearanceCategory.COPYRIGHT_ART,
    )


def risk(band=RiskBand.MEDIUM):
    return RiskAssessment(element_id="1", score=41, band=band, factors={},
                          de_minimis=False)


PROD = Production(id="p", title="t", footage_uri="c.mp4", duration_s=41.5)

NO_RESEARCH = ResearchResult(
    element_id="1", owner=None, owner_confidence="low", licensing_contact=None,
    licensing_posture="unknown", litigation_history=[],
    estimated_license_cost_band=None, basis=[], status="incomplete",
)


def opts(element, risk_, _unused=None):
    return draft_options(element, NO_RESEARCH, risk_, PROD)


def blur(options):
    return next(o for o in options if o.kind == "blur")


def test_the_total_scales_with_the_number_of_shots():
    one = blur(opts(el(1), risk(), None))
    seven = blur(opts(el(7), risk(), None))
    assert one.est_cost_band == "$300-$800"
    assert seven.est_cost_band == "$2,100-$5,600"


def test_the_per_shot_rate_is_still_shown():
    """A producer negotiating with a VFX house needs the unit price too."""
    detail = blur(opts(el(7), risk(), None)).detail
    assert "7 shot(s)" in detail
    assert "$300-$800 per shot" in detail


def test_a_bigger_element_costs_more_per_shot():
    small = blur(opts(el(2, coverage=0.03), risk(), None))
    big = blur(opts(el(2, coverage=0.4), risk(), None))
    assert small.est_cost_band == "$600-$1,600"
    assert big.est_cost_band == "$1,600-$5,000"
