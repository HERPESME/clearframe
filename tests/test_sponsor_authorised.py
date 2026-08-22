"""A sponsor's own mark is authorised — telling them to go ask themselves is wrong.

If Domino's commissions the advert, the Domino's logo in frame is not an
unlicensed use. Before this the pipeline scored it HIGH 55, spent a Parallel
Task run on it, and produced the disposition "approach Domino's Pizza, Inc." —
addressed to the agency whose client is paying them to feature it.

It must still APPEAR: the dossier has to be complete, and the production
agreement still has to cover the declared territories and media, which is a
coverage question rather than a clearance one. What changes is the route, the
posture and the required action.
"""

import pytest

from clearframe.knowledge import load_knowledge
from clearframe.models import (
    ClearanceCategory,
    DepictionTone,
    ElementType,
    LicensingPosture,
    Prominence,
    ResearchTier,
    TimeRange,
    TriagedElement,
    UseContext,
)
from clearframe.routing import route

KB = load_knowledge()


def el(label="Domino's Pizza box and logo", category=ClearanceCategory.TRADEMARK,
       depiction=None):
    return TriagedElement(
        id="e1", label=label,
        element_type=ElementType.LOGO if category is ClearanceCategory.TRADEMARK
        else ElementType.TEXT,
        description="Hero product, centre frame",
        time_ranges=[TimeRange(start_s=2.0, end_s=25.0)],
        prominence=Prominence(screen_time_s=23.0, frame_coverage=0.5,
                              centrality=0.9, plot_integral=True),
        category=category, depiction=depiction,
    )


def test_the_sponsors_own_mark_resolves_locally_instead_of_a_deep_run():
    r = route(el(), KB, use_context=UseContext.ADVERTISING, sponsors=["Domino's Pizza"])
    assert r.tier is ResearchTier.LOCAL
    assert r.est_cost_usd == 0.0
    assert r.owner == "Domino's Pizza, Inc."


def test_it_is_marked_permissive_because_they_are_paying_to_be_there():
    r = route(el(), KB, sponsors=["Domino's Pizza"])
    assert r.posture is LicensingPosture.PERMISSIVE


def test_the_required_action_is_the_contract_not_a_clearance_request():
    r = route(el(), KB, sponsors=["Domino's Pizza"])
    assert "approach" not in r.disposition.lower()
    assert "agreement" in r.disposition.lower() or "contract" in r.disposition.lower()
    assert "territor" in r.disposition.lower()


def test_the_finding_is_never_suppressed():
    """A dossier that silently omits the hero product is incomplete, and an
    underwriter will notice."""
    r = route(el(), KB, sponsors=["Domino's Pizza"])
    assert r.element_id == "e1"
    assert r.rationale


def test_a_sibling_brand_of_the_same_owner_is_also_authorised():
    """Sponsor Coca-Cola, and a Sprite can appears. Same house."""
    r = route(el("Sprite bottle"), KB, sponsors=["Coca-Cola"])
    assert r.tier is ResearchTier.LOCAL


def test_a_rival_mark_is_emphatically_not_authorised():
    r = route(el("Pepsi can"), KB, use_context=UseContext.ADVERTISING,
              sponsors=["Coca-Cola"])
    assert r.tier is not ResearchTier.LOCAL
    assert r.posture is not LicensingPosture.PERMISSIVE


def test_an_unrelated_mark_is_unaffected():
    r = route(el("Nike hoodie swoosh"), KB, sponsors=["Domino's Pizza"])
    assert r.tier is not ResearchTier.LOCAL


def test_declaring_no_sponsors_leaves_everything_exactly_as_before():
    with_none = route(el(), KB, use_context=UseContext.ADVERTISING)
    assert with_none.tier is ResearchTier.DEEP


def test_an_unflattering_depiction_of_your_own_sponsor_still_escalates():
    """Authorisation covers showing the mark, not disparaging it. If the scan
    reads the depiction as damaging, that is a conversation to have with the
    client before delivery, not something to wave through."""
    r = route(el(depiction=DepictionTone.DISPARAGING), KB,
              sponsors=["Domino's Pizza"])
    assert r.tier is not ResearchTier.LOCAL


def test_an_uncatalogued_sponsor_name_changes_nothing():
    r = route(el(), KB, sponsors=["Zorblax Pizza"])
    assert r.tier is not ResearchTier.LOCAL
