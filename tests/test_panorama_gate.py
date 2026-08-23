"""Freedom of panorama covers works permanently sited in a public place.

Not a tattoo on a face. Not a print on a t-shirt. Not a sticker on an indoor
water heater. Not a ring. Those are all COPYRIGHT_ART, and the whole category
was being run through the panorama branch — so a producer's dossier said a face
tattoo stepped DOWN a band in Germany under UrhG §59, the exception for works
permanently in public ways.

The rationale even disclosed the condition it never applied: "Risk steps down
IF this work is permanently installed and filmed from a place accessible to the
public — confirm both before relying on it." The test lived in prose instead of
in code, and it moved the band either way: -1 in DE/IN, +1 in FR.

Siting is an observation about the footage, so the scan reports it. Unknown
siting gets NO shift: a discount for not knowing is the covered-direction error
this product must never make.
"""

import pytest

from clearframe.models import (
    ClearanceCategory,
    ElementType,
    Prominence,
    RiskBand,
    TimeRange,
    TriagedElement,
)
from clearframe.territory import assess


def el(kind: ElementType, category: ClearanceCategory, siting: str = "unknown"):
    return TriagedElement(
        id="1", label="thing", element_type=kind, description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=4.0)],
        prominence=Prominence(screen_time_s=3.0, frame_coverage=0.2,
                              centrality=0.6, plot_integral=False),
        category=category, siting=siting,
    )


MURAL = lambda: el(ElementType.ARTWORK, ClearanceCategory.COPYRIGHT_ART, "public_permanent")
TATTOO = lambda: el(ElementType.TATTOO, ClearanceCategory.COPYRIGHT_ART)
TSHIRT = lambda: el(ElementType.ARTWORK, ClearanceCategory.COPYRIGHT_ART, "portable_or_interior")
VAGUE = lambda: el(ElementType.ARTWORK, ClearanceCategory.COPYRIGHT_ART, "unknown")


def test_a_mural_permanently_sited_in_public_still_gets_panorama():
    """The case the branch was written for, unchanged."""
    de = assess(MURAL(), RiskBand.HIGH, "DE")
    assert de.band is RiskBand.MEDIUM          # steps down
    assert "panorama" in de.rationale.lower()
    assert "UrhG §59" in de.authority


def test_a_tattoo_is_never_a_panorama_case():
    """A tattoo is on a person, not permanently sited anywhere."""
    for terr in ("US", "DE", "FR", "IN"):
        r = assess(TATTOO(), RiskBand.HIGH, terr)
        assert r.band is RiskBand.HIGH, terr
        assert "panorama" not in r.rationale.lower(), (terr, r.rationale)


def test_a_t_shirt_print_is_never_a_panorama_case():
    for terr in ("DE", "FR"):
        r = assess(TSHIRT(), RiskBand.HIGH, terr)
        assert r.band is RiskBand.HIGH, terr
        assert "panorama" not in r.rationale.lower()


def test_unknown_siting_gets_no_discount():
    """Being wrong in the covered direction is the one failure to avoid."""
    de = assess(VAGUE(), RiskBand.HIGH, "DE")
    assert de.band is RiskBand.HIGH
    # But the user is told the exception might apply if they can establish it.
    assert "permanently" in de.rationale.lower()


def test_unknown_siting_gets_no_penalty_either():
    """France steps up only for a work the exception could have covered."""
    fr = assess(VAGUE(), RiskBand.MEDIUM, "FR")
    assert fr.band is RiskBand.MEDIUM


def test_a_publicly_sited_work_in_france_still_steps_up():
    fr = assess(MURAL(), RiskBand.MEDIUM, "FR")
    assert fr.band is RiskBand.HIGH
    assert "non-commercial" in fr.rationale
