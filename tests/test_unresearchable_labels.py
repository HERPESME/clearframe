"""A label that names no rights subject cannot be answered by research.

Five of eight findings on a live Hangover Part II clip went to multi-minute
Parallel Task runs: "Wristwatch", "Aviator Sunglasses", "Dog T-Shirt", "Water
Heater Sticker", "Phil's Ring". None returned an owner, and none could have —
there is nothing in those strings to look up. This is the "Flower Vase" defect
from the first live validation, recurring with a different vocabulary.

Three different answers are needed, because the objects differ:

  a watch, sunglasses, a ring   a useful article; no author exists to find
  a t-shirt graphic, a sticker  real artwork whose author was never named
  a tattoo                      settled category guidance, in litigation.json

The last one is the point. `cases_for()` fed liability.py and nothing else,
so the most-litigated tattoo in film history took a four-minute web search
that returned nothing, while the case describing it sat in the local table.
"""

from clearframe.knowledge import load_knowledge
from clearframe.models import (
    ClearanceCategory, ElementType, Prominence, ResearchTier, TimeRange,
    TriagedElement,
)
from clearframe.routing import route

KB = load_knowledge()


def art(label, kind=ElementType.ARTWORK, description=""):
    return TriagedElement(
        id="1", label=label, element_type=kind, description=description,
        time_ranges=[TimeRange(start_s=1.0, end_s=11.0)],
        prominence=Prominence(screen_time_s=10.0, frame_coverage=0.1,
                              centrality=0.6, plot_integral=True),
        category=ClearanceCategory.COPYRIGHT_ART,
    )


def tier(el):
    return route(el, KB).tier


# ---------------------------------------------------------- useful articles
def test_a_watch_has_no_author_to_find():
    assert tier(art("Wristwatch")) is ResearchTier.STATUTE
    assert tier(art("Aviator Sunglasses")) is ResearchTier.STATUTE
    assert tier(art("Phil's Ring")) is ResearchTier.STATUTE


# ------------------------------------------------- artwork nobody named
#
# NOT downgraded, deliberately. A first attempt gave "Dog T-Shirt" and "Water
# Heater Sticker" a $0 disposition pointing at wardrobe paperwork, and an
# existing test stopped it: Ringgold v. BET turned on a poster hanging on a
# wall, so quietly downgrading an authored image is the exact failure this
# product exists to prevent. An unidentifiable artwork keeps its expensive
# attempt — the deep run may return nothing, but the alternative is deciding
# on its behalf that nobody owns it.


def test_an_unnamed_graphic_keeps_its_expensive_attempt():
    assert tier(art("Dog T-Shirt")) is ResearchTier.DEEP
    assert tier(art("Water Heater Sticker")) is ResearchTier.DEEP


def test_a_named_artist_still_earns_a_deep_run():
    assert tier(art("Street mural by Banksy")) is ResearchTier.DEEP


# ------------------------------------------------------------------ tattoos
def test_a_tattoo_is_answered_from_the_case_table_not_the_open_web():
    r = route(art("Stu's Face Tattoo", ElementType.TATTOO), KB)
    assert r.tier is ResearchTier.STATUTE
    assert r.est_cost_usd == 0
    assert "Solid Oak" in r.basis or "Alexander" in r.basis
    assert "release" in r.disposition.lower()


def test_a_tattoo_replicated_onto_another_person_is_the_whitmill_case():
    """Whitmill: copying a tattoo onto someone else is materially riskier.

    The scan reported this one as "a replica of Mike Tyson's famous tattoo",
    which is the fact pattern that produced a federal suit and a settlement
    weeks before release.
    """
    r = route(
        art("Stu's Face Tattoo", ElementType.TATTOO,
            description="A large tribal tattoo on Stu's face, a replica of "
                        "Mike Tyson's famous tattoo."),
        KB,
    )
    assert r.tier is ResearchTier.DEEP
    assert "Whitmill" in r.basis


# ---------------------------------------------------- marks that name no mark
#
# "Wristwatch" was typed LOGO by the scan, so it went through the trademark
# router, missed the catalogue, and bought a multi-minute ownership
# investigation. A product type is not a mark: there is no proprietor of
# "wristwatch" to find, and no amount of searching invents one.
#
# This is separate from a catalogue MISS. "Calvin Klein" is a real mark that
# happens to be absent from our 161 entries, and that genuinely needs research.


def logo(label):
    return TriagedElement(
        id="1", label=label, element_type=ElementType.LOGO, description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=11.0)],
        prominence=Prominence(screen_time_s=10.0, frame_coverage=0.1,
                              centrality=0.6, plot_integral=True),
        category=ClearanceCategory.TRADEMARK,
    )


def test_a_product_type_is_not_a_mark():
    r = route(logo("Wristwatch"), KB)
    assert r.tier is ResearchTier.STATUTE
    assert r.est_cost_usd == 0


def test_an_uncatalogued_real_brand_still_gets_researched():
    """A catalogue miss is not the same as a label with no mark in it."""
    assert route(logo("Calvin Klein"), KB).tier is ResearchTier.DEEP
    assert route(logo("National"), KB).tier is ResearchTier.DEEP


def test_a_catalogued_mark_is_unaffected():
    """A background Nike swoosh resolves from the catalogue, not the open web.

    Low prominence deliberately: anything at or above the HIGH band escalates
    to DEEP regardless of category, which is the documented rule and not what
    this test is about.
    """
    background = logo("Nike").model_copy(
        update={
            "prominence": Prominence(
                screen_time_s=1.5, frame_coverage=0.02,
                centrality=0.2, plot_integral=False,
            )
        }
    )
    assert route(background, KB).tier in (ResearchTier.LOCAL, ResearchTier.SEARCH)
