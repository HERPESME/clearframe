"""Failing to look is not evidence that there is nothing to find.

`score_element` mapped an incomplete research result to LicensingPosture.UNKNOWN
and then applied UNKNOWN's 0.7 factor — a 30% discount. So a finding whose deep
research came back empty scored *lower* than one where research succeeded and
found a litigious holder, and lower than its own provisional band.

On a live clip that produced the exact inversion this product exists to
prevent: Stu's face tattoo previewed at 58 (HIGH), research returned no owner,
and the final band FELL to 41 (MEDIUM) — while liability.py, reading the same
knowledge base, printed "a claim in this category has stopped a release
before" and cited Woods v. Universal. One run, two modules, opposite
conclusions from the same table.

`provisional_score` already pins posture at worst case, deliberately, so a band
can only fall once research lands. It must fall because something was LEARNED,
never because the lookup failed.

A successful lookup that identifies a holder but cannot determine posture is a
different state and keeps its 0.7 — it found the counterparty.
"""

from clearframe.models import (
    ClearanceCategory, ElementType, LicensingPosture, Prominence, ResearchResult,
    RiskBand, TimeRange, TriagedElement,
)
from clearframe.scoring import provisional_score, score_element


def tattoo():
    return TriagedElement(
        id="1", label="Stu's Face Tattoo", element_type=ElementType.TATTOO,
        description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=11.0)],
        prominence=Prominence(screen_time_s=10.0, frame_coverage=0.03,
                              centrality=0.7, plot_integral=True),
        category=ClearanceCategory.COPYRIGHT_ART,
    )


def research(status, posture=LicensingPosture.UNKNOWN, owner="Someone"):
    return ResearchResult(
        element_id="1", owner=owner if status == "complete" else None,
        owner_confidence="high" if status == "complete" else "low",
        licensing_contact=None, licensing_posture=posture,
        litigation_history=[], estimated_license_cost_band=None,
        basis=[], status=status,
    )


def test_a_failed_lookup_does_not_earn_a_discount():
    r = score_element(tattoo(), research("incomplete"))
    assert r.factors["posture_factor"] == 1.0
    assert r.band is RiskBand.HIGH


def test_no_research_at_all_does_not_earn_a_discount():
    r = score_element(tattoo(), None)
    assert r.factors["posture_factor"] == 1.0


def test_the_band_never_falls_because_the_lookup_failed():
    """The two-phase report's guarantee, restated as arithmetic."""
    provisional = provisional_score(tattoo())
    final = score_element(tattoo(), research("incomplete")).score
    assert final == provisional


def test_a_successful_lookup_that_cannot_determine_posture_keeps_its_discount():
    """It still found the counterparty; that is worth something."""
    r = score_element(tattoo(), research("complete", LicensingPosture.UNKNOWN))
    assert r.factors["posture_factor"] == 0.7


def test_a_successful_lookup_finding_a_permissive_holder_still_discounts_hard():
    r = score_element(tattoo(), research("complete", LicensingPosture.PERMISSIVE))
    assert r.factors["posture_factor"] == 0.4
    assert r.band is RiskBand.MEDIUM


def test_a_litigious_holder_is_still_the_worst_case():
    failed = score_element(tattoo(), research("incomplete")).score
    litigious = score_element(tattoo(), research("complete", LicensingPosture.LITIGIOUS)).score
    assert failed == litigious
