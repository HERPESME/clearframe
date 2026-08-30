"""What it costs to ignore this — which is not the same as what it costs to clear it.

Until now the dossier priced two things: a licence, and a blur. Both are the
cost of doing the right thing. Neither tells a director what happens if they
ship it anyway, and that is the number the case law is actually about.

The lesson from those cases is that damages are rarely the point. Woods did not
win a damages award against 12 Monkeys — he won an INJUNCTION against a film
already in theatres, and took a high six-figure settlement to lift it. Whitmill
was denied an injunction and Warner Bros. settled anyway, weeks before release.
The exposure is delay and leverage, not a judgment.

So this module reports a range with a citation, a flag for whether a claim can
stop a release, and the escalation — because the only variable a director
controls is WHEN they find out.
"""

import pytest

from clearframe.knowledge import load_knowledge
from clearframe.liability import STATUTORY_MAX, STATUTORY_MIN, STATUTORY_WILLFUL, estimate
from clearframe.models import (
    ClearanceCategory,
    ElementType,
    LicensingPosture,
    Prominence,
    RemediationOption,
    ResearchResult,
    TimeRange,
    TriagedElement,
)

KB = load_knowledge()


def el(category, label="x"):
    types = {
        ClearanceCategory.TRADEMARK: ElementType.LOGO,
        ClearanceCategory.COPYRIGHT_ART: ElementType.ARTWORK,
        ClearanceCategory.MUSIC_SYNC: ElementType.MUSIC,
        ClearanceCategory.RIGHT_OF_PUBLICITY: ElementType.FACE,
        ClearanceCategory.LOCATION: ElementType.LOCATION,
        ClearanceCategory.TEXT_ON_SCREEN: ElementType.TEXT,
    }
    return TriagedElement(
        id="e1", label=label, element_type=types[category], description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=9.0)],
        prominence=Prominence(screen_time_s=8.0, frame_coverage=0.3,
                              centrality=0.7, plot_integral=True),
        category=category,
    )


def research(cost="$500-$5k"):
    return ResearchResult(
        element_id="e1", owner="Someone Ltd", owner_confidence="high",
        licensing_contact=None, licensing_posture=LicensingPosture.STANDARD,
        litigation_history=[], estimated_license_cost_band=cost, basis=[],
        status="complete",
    )


def blur(band="$800-$2500/shot"):
    return [RemediationOption(kind="blur", summary="Blur", detail="", est_cost_band=band)]


# ------------------------------------------------- statutory damages, honestly
@pytest.mark.parametrize(
    "category", [ClearanceCategory.COPYRIGHT_ART, ClearanceCategory.MUSIC_SYNC]
)
def test_copyright_claims_carry_the_statutory_range(category):
    e = estimate(el(category), research(), blur(), KB)
    assert e.statutory_min_usd == STATUTORY_MIN == 750
    assert e.statutory_max_usd == STATUTORY_MAX == 30_000
    assert e.statutory_willful_usd == STATUTORY_WILLFUL == 150_000
    assert "504(c)" in e.statutory_basis


@pytest.mark.parametrize(
    "category",
    [
        ClearanceCategory.TRADEMARK,
        ClearanceCategory.TEXT_ON_SCREEN,
        ClearanceCategory.LOCATION,
        ClearanceCategory.RIGHT_OF_PUBLICITY,
    ],
)
def test_non_copyright_claims_do_not_borrow_a_copyright_number(category):
    """Quoting $150,000 statutory for a logo would be wrong: §504(c) is a
    COPYRIGHT remedy. Trademark gives profits and damages, publicity is state
    law, a location is contract. Inventing a scary number is worse than none."""
    e = estimate(el(category), research(), blur(), KB)
    assert e.statutory_min_usd is None
    assert e.statutory_max_usd is None
    assert "504(c)" not in e.statutory_basis
    assert e.statutory_basis  # it still explains what the remedy IS


# --------------------------------------------------------- injunction risk
def test_artwork_carries_documented_injunction_precedent():
    """Woods v. Universal stopped a film that was already in theatres."""
    e = estimate(el(ClearanceCategory.COPYRIGHT_ART), research(), blur(), KB)
    assert e.injunction_risk == "documented"
    assert "Woods" in e.injunction_basis


def test_a_category_with_no_injunction_precedent_says_so():
    e = estimate(el(ClearanceCategory.LOCATION), research(), blur(), KB)
    assert e.injunction_risk in {"no precedent on file", "sought and denied"}
    assert e.injunction_basis


def test_trademark_injunctions_were_sought_and_denied():
    e = estimate(el(ClearanceCategory.TRADEMARK), research(), blur(), KB)
    assert e.injunction_risk == "sought and denied"


# ------------------------------------------------------------- the escalation
def test_the_escalation_prices_all_three_moments():
    e = estimate(el(ClearanceCategory.COPYRIGHT_ART), research(), blur(), KB)
    joined = " ".join(e.escalation).lower()
    assert "$500-$5k" in " ".join(e.escalation)          # clear it now
    assert "$800-$2500/shot" in " ".join(e.escalation)   # fix it at lock
    assert "leverage" in joined or "delivery" in joined  # find it too late


def test_it_carries_the_licence_and_the_fix_separately():
    e = estimate(el(ClearanceCategory.COPYRIGHT_ART), research(), blur(), KB)
    assert e.clear_now == "$500-$5k"
    assert e.fix_in_post == "$800-$2500/shot"


def test_an_unpriced_finding_says_unknown_rather_than_zero():
    e = estimate(el(ClearanceCategory.COPYRIGHT_ART), research(cost=None), [], KB)
    assert e.clear_now is None
    assert e.fix_in_post is None
    assert "not established" in " ".join(e.escalation).lower() or e.headline


def test_no_research_at_all_still_produces_an_estimate():
    e = estimate(el(ClearanceCategory.MUSIC_SYNC), None, [], KB)
    assert e.element_id == "e1"
    assert e.headline


# ----------------------------------------------------------------- headline
def test_the_headline_is_one_plain_sentence():
    e = estimate(el(ClearanceCategory.COPYRIGHT_ART), research(), blur(), KB)
    assert e.headline.endswith(".")
    assert len(e.headline) < 200
    assert "$" in e.headline or "release" in e.headline.lower()


def test_you_do_not_vfx_paint_out_a_song():
    e = estimate(el(ClearanceCategory.MUSIC_SYNC), research(), [], KB)
    fix = e.escalation[1].lower()
    assert "paint-out" not in fix
    assert "mute" in fix or "replace" in fix
