"""How a brand is SHOWN, not whether it is shown.

The litigation record says brand owners rarely object to presence and reliably
object to portrayal. Wham-O sued over a gag in which a character was hurt by a
Slip 'N Slide. In-Sink-Erator complained when a character's hand was mangled in
a garbage disposal on NBC's Heroes — and NBC digitally erased the mark rather
than litigate, paying the cost in post.

One question added to a scan we already run answers three threat classes:
trademark disparagement, false endorsement, and trade libel against a named
business.
"""

import pytest

from clearframe.knowledge import load_knowledge
from clearframe.models import (
    ClearanceCategory,
    DepictionTone,
    ElementType,
    LicensingPosture,
    Prominence,
    ResearchResult,
    TimeRange,
    TriagedElement,
    UseContext,
)
from clearframe.routing import ResearchTier, route
from clearframe.scoring import score_element

KB = load_knowledge()


def el(depiction=None, category=ClearanceCategory.TRADEMARK, label="Coca-Cola can", **kw):
    types = {
        ClearanceCategory.TRADEMARK: ElementType.LOGO,
        ClearanceCategory.COPYRIGHT_ART: ElementType.ARTWORK,
        ClearanceCategory.MUSIC_SYNC: ElementType.MUSIC,
        ClearanceCategory.RIGHT_OF_PUBLICITY: ElementType.FACE,
        ClearanceCategory.LOCATION: ElementType.LOCATION,
        ClearanceCategory.TEXT_ON_SCREEN: ElementType.TEXT,
    }
    base = dict(
        id="e1", label=label, element_type=types[category], description="",
        time_ranges=[TimeRange(start_s=0.0, end_s=6.0)],
        prominence=Prominence(screen_time_s=6.0, frame_coverage=0.15,
                              centrality=0.4, plot_integral=False),
        category=category, depiction=depiction,
    )
    base.update(kw)
    return TriagedElement(**base)


def research():
    return ResearchResult(
        element_id="e1", owner="The Coca-Cola Company", owner_confidence="high",
        licensing_contact=None, licensing_posture=LicensingPosture.STANDARD,
        litigation_history=[], estimated_license_cost_band=None, basis=[],
        status="complete",
    )


# ------------------------------------------------------- backward compatibility
def test_an_unreported_depiction_changes_nothing():
    """Every existing fixture and stored state has no depiction field."""
    assert el().depiction is None
    assert score_element(el(None), research()).score == score_element(
        el(DepictionTone.NEUTRAL), research()
    ).score


# ------------------------------------------------------------------- scoring
@pytest.mark.parametrize(
    "tone,direction",
    [
        (DepictionTone.FAVOURABLE, "lower"),
        (DepictionTone.NEUTRAL, "same"),
        (DepictionTone.UNFLATTERING, "higher"),
        (DepictionTone.DISPARAGING, "higher"),
    ],
)
def test_portrayal_moves_risk_in_the_right_direction(tone, direction):
    base = score_element(el(DepictionTone.NEUTRAL), research()).score
    got = score_element(el(tone), research()).score
    if direction == "higher":
        assert got > base
    elif direction == "lower":
        assert got < base
    else:
        assert got == base


def test_disparaging_outranks_merely_unflattering():
    unflattering = score_element(el(DepictionTone.UNFLATTERING), research()).score
    disparaging = score_element(el(DepictionTone.DISPARAGING), research()).score
    assert disparaging > unflattering


def test_the_factor_is_recorded_for_reproducibility():
    r = score_element(el(DepictionTone.DISPARAGING), research())
    assert r.factors["depiction_factor"] > 1.0


def test_music_and_artwork_do_not_care_how_they_are_portrayed():
    """A sync licence is required whether the song plays over a wedding or a
    murder. Copyright is not offended by context."""
    for category in (ClearanceCategory.MUSIC_SYNC, ClearanceCategory.COPYRIGHT_ART):
        neutral = score_element(el(DepictionTone.NEUTRAL, category), research()).score
        nasty = score_element(el(DepictionTone.DISPARAGING, category), research()).score
        assert neutral == nasty, category


def test_a_named_business_shown_badly_is_a_trade_libel_exposure():
    """The skit case: a named pizza place that makes a character ill. Not
    copyright, not trademark — trade libel, and the depiction IS the claim."""
    venue = el(DepictionTone.DISPARAGING, ClearanceCategory.LOCATION, "Domino's Pizza storefront")
    neutral = el(DepictionTone.NEUTRAL, ClearanceCategory.LOCATION, "Domino's Pizza storefront")
    assert score_element(venue, research()).score > score_element(neutral, research()).score


# ------------------------------------------------------------------- routing
def test_an_unflattering_catalogued_mark_escalates_beyond_a_posture_check():
    """Ownership is known locally and posture would normally be a two-second
    search. But the question for an unflattering depiction is not 'are they
    litigious' — it is 'will they object to THIS', which needs a contact."""
    calm = route(el(DepictionTone.NEUTRAL), KB)
    nasty = route(el(DepictionTone.DISPARAGING), KB)

    assert calm.tier is ResearchTier.SEARCH
    assert nasty.tier is ResearchTier.DEEP
    assert "depict" in nasty.rationale.lower()
    assert "In-Sink-Erator" in nasty.basis or "Wham-O" in nasty.basis


def test_a_favourable_depiction_does_not_escalate():
    assert route(el(DepictionTone.FAVOURABLE), KB).tier is ResearchTier.SEARCH


def test_depiction_never_resurrects_a_finding_that_needs_no_research():
    """A caption we wrote ourselves is still ours, however it is framed."""
    own = el(DepictionTone.DISPARAGING, ClearanceCategory.TEXT_ON_SCREEN,
             "Narrative text overlay")
    assert route(own, KB).tier is ResearchTier.STATUTE


def test_a_disparaging_mark_in_an_advert_is_the_worst_case():
    """Comparative advertising that denigrates a rival is the one combination
    where both multipliers apply."""
    r = score_element(el(DepictionTone.DISPARAGING), research(),
                      use_context=UseContext.ADVERTISING)
    base = score_element(el(DepictionTone.NEUTRAL), research(),
                         use_context=UseContext.EXPRESSIVE)
    assert r.score > base.score
    assert r.factors["use_context_factor"] > 1.0
    assert r.factors["depiction_factor"] > 1.0
