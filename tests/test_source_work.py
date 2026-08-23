"""When the footage IS someone else's work, its parts are not separate findings.

Uploading a clip of an existing anime produced eight findings and five separate
multi-minute investigations into C.C., Lelouch, Nunnally, Zero's Mask and
Arthur — five characters from one work, one rights holder, inside footage that
is itself that work. Six of the seven deep runs returned nothing, and the one
that succeeded answered all of them.

The correct output is not eight findings. It is one: this is Code Geass, clear
the work. Everything inside it is subsumed — you either hold a licence to the
film or you do not, and no amount of research into a supporting character
changes that.
"""

import pytest

from clearframe.knowledge import load_knowledge
from clearframe.models import (
    ClearanceCategory,
    ElementType,
    Prominence,
    ResearchTier,
    SourceWork,
    TimeRange,
    TriagedElement,
)
from clearframe.routing import route
from clearframe.sourcework import subsumed_by, summarise_source_work

KB = load_knowledge()

GEASS = SourceWork(
    title="Code Geass: Lelouch of the Rebellion",
    rights_holder="Sunrise / Bandai Namco Filmworks Inc.",
    confidence="high",
    basis="Named characters C.C. and Lelouch Lamperouge, and Zero's mask.",
)


def el(category, label, element_type=None):
    types = {
        ClearanceCategory.TRADEMARK: ElementType.LOGO,
        ClearanceCategory.COPYRIGHT_ART: ElementType.ARTWORK,
        ClearanceCategory.MUSIC_SYNC: ElementType.MUSIC,
        ClearanceCategory.RIGHT_OF_PUBLICITY: ElementType.FACE,
        ClearanceCategory.LOCATION: ElementType.LOCATION,
        ClearanceCategory.TEXT_ON_SCREEN: ElementType.TEXT,
    }
    return TriagedElement(
        id="e1", label=label,
        element_type=element_type or types[category], description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=9.0)],
        prominence=Prominence(screen_time_s=8.0, frame_coverage=0.3,
                              centrality=0.7, plot_integral=True),
        category=category,
    )


# ----------------------------------------------------- what gets subsumed
def test_a_character_belongs_to_the_work_not_to_itself():
    e = el(ClearanceCategory.COPYRIGHT_ART, "C.C.", ElementType.CHARACTER)
    assert subsumed_by(e, GEASS) is True


def test_set_dressing_inside_the_work_is_subsumed_too():
    """A painting on the wall of an anime is drawn by the same studio. It is
    not a separate artwork to clear."""
    assert subsumed_by(el(ClearanceCategory.COPYRIGHT_ART, "Framed Painting"), GEASS) is True


def test_a_real_brand_inside_the_work_is_NOT_subsumed():
    """Pizza Hut paid for that placement in Japan. It is a live third-party
    mark and stays its own finding — this is the Code Geass fact pattern
    exactly, and the reason the sponsorship never travelled."""
    assert subsumed_by(el(ClearanceCategory.TRADEMARK, "Pizza Hut"), GEASS) is False


def test_music_is_never_subsumed():
    """Sync and master are separate paper from the film licence, and often a
    separate holder."""
    e = el(ClearanceCategory.MUSIC_SYNC, "Incidental score")
    assert subsumed_by(e, GEASS) is False


def test_a_real_person_is_never_subsumed():
    e = el(ClearanceCategory.RIGHT_OF_PUBLICITY, "Background passerby")
    assert subsumed_by(e, GEASS) is False


def test_nothing_is_subsumed_without_an_identified_work():
    e = el(ClearanceCategory.COPYRIGHT_ART, "C.C.", ElementType.CHARACTER)
    assert subsumed_by(e, None) is False


def test_a_low_confidence_guess_does_not_subsume_anything():
    """Wrongly deciding the footage is someone else's work would suppress every
    finding in it. That needs certainty, not a hunch."""
    hunch = GEASS.model_copy(update={"confidence": "low"})
    e = el(ClearanceCategory.COPYRIGHT_ART, "C.C.", ElementType.CHARACTER)
    assert subsumed_by(e, hunch) is False


# ------------------------------------------------------------- the routing
def test_a_subsumed_finding_costs_nothing_to_resolve():
    e = el(ClearanceCategory.COPYRIGHT_ART, "C.C.", ElementType.CHARACTER)
    r = route(e, KB, source_work=GEASS)
    assert r.tier is ResearchTier.LOCAL
    assert r.est_cost_usd == 0.0
    assert r.owner == GEASS.rights_holder


def test_the_disposition_points_at_the_work_not_the_part():
    e = el(ClearanceCategory.COPYRIGHT_ART, "Lelouch", ElementType.CHARACTER)
    r = route(e, KB, source_work=GEASS)
    assert "Code Geass" in r.disposition
    assert "licence" in r.disposition.lower() or "license" in r.disposition.lower()


def test_the_brand_inside_it_still_gets_researched():
    r = route(el(ClearanceCategory.TRADEMARK, "Pizza Hut"), KB, source_work=GEASS)
    assert r.tier is not ResearchTier.LOCAL or r.owner != GEASS.rights_holder


def test_without_a_source_work_routing_is_unchanged():
    e = el(ClearanceCategory.COPYRIGHT_ART, "C.C.", ElementType.CHARACTER)
    assert route(e, KB).tier is ResearchTier.DEEP


# ------------------------------------------------------------- the summary
def test_the_summary_leads_with_the_work():
    elements = [
        el(ClearanceCategory.COPYRIGHT_ART, "C.C.", ElementType.CHARACTER),
        el(ClearanceCategory.TRADEMARK, "Pizza Hut"),
    ]
    s = summarise_source_work(GEASS, elements)
    assert "Code Geass" in s["headline"]
    assert s["subsumed"] == 1
    assert s["independent"] == 1
    assert "licence" in s["action"].lower() or "license" in s["action"].lower()


def test_no_work_means_no_summary():
    assert summarise_source_work(None, []) is None
