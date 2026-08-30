"""Sponsor conflict: a competitor's mark in frame is a contract problem.

Not a copyright or trademark question at all — a breach-of-contract one. Brand
deals routinely carry category exclusivity, so a rival logo in shot can void
the fee even though showing it is perfectly lawful. Nothing else in the
pipeline would ever flag it, because nothing is being infringed.
"""

import pytest

from clearframe.conflicts import find_sponsor_conflicts
from clearframe.knowledge import load_knowledge
from clearframe.models import (
    ClearanceCategory,
    ElementType,
    Prominence,
    TimeRange,
    TriagedElement,
)

KB = load_knowledge()


def el(label, eid="e1", category=ClearanceCategory.TRADEMARK):
    return TriagedElement(
        id=eid,
        label=label,
        element_type=ElementType.LOGO if category is ClearanceCategory.TRADEMARK
        else ElementType.TEXT,
        description="",
        time_ranges=[TimeRange(start_s=0.0, end_s=5.0)],
        prominence=Prominence(
            screen_time_s=5.0, frame_coverage=0.1, centrality=0.4, plot_integral=False
        ),
        category=category,
    )


def test_a_rival_in_the_same_sector_is_a_conflict():
    conflicts = find_sponsor_conflicts([el("Pepsi can")], ["Coca-Cola"], KB)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.element_id == "e1"
    assert c.detected_owner == "PepsiCo, Inc."
    assert c.conflicts_with == "Coca-Cola"
    assert c.sector == "beverage"


def test_the_sponsors_own_mark_is_the_placement_not_a_conflict():
    assert find_sponsor_conflicts([el("Coca-Cola can")], ["Coca-Cola"], KB) == []


def test_a_sibling_brand_of_the_same_owner_is_not_a_conflict():
    """Sprite and Coca-Cola are both The Coca-Cola Company. Flagging that would
    be noise, and noise is what makes a warning system get ignored."""
    assert find_sponsor_conflicts([el("Sprite bottle")], ["Coca-Cola"], KB) == []


def test_a_different_sector_is_not_a_conflict():
    assert find_sponsor_conflicts([el("Nike hoodie swoosh")], ["Coca-Cola"], KB) == []


def test_uncatalogued_marks_are_not_guessed_at():
    """We cannot tell whether 'Zorblax' competes with anything, and inventing
    a conflict is worse than missing one here — this is a contract warning, and
    a false one costs the user a real conversation with their sponsor."""
    assert find_sponsor_conflicts([el("Zorblax Cola")], ["Coca-Cola"], KB) == []


def test_an_unknown_sponsor_name_yields_nothing_rather_than_erroring():
    assert find_sponsor_conflicts([el("Pepsi can")], ["Zorblax Inc"], KB) == []


def test_no_sponsors_means_no_checks():
    assert find_sponsor_conflicts([el("Pepsi can")], [], KB) == []


def test_multiple_sponsors_and_multiple_rivals():
    elements = [
        el("Pepsi can", "a"),
        el("Burger King sign", "b"),
        el("Nike hoodie swoosh", "c"),
    ]
    conflicts = find_sponsor_conflicts(elements, ["Coca-Cola", "McDonald's"], KB)
    assert {c.element_id for c in conflicts} == {"a", "b"}


def test_only_brand_categories_are_checked():
    """A mural is not a sponsor conflict however prominent it is."""
    art = el("Pepsi can", category=ClearanceCategory.COPYRIGHT_ART)
    art = art.model_copy(update={"element_type": ElementType.ARTWORK})
    assert find_sponsor_conflicts([art], ["Coca-Cola"], KB) == []


def test_the_conflict_explains_itself():
    (c,) = find_sponsor_conflicts([el("Pepsi can")], ["Coca-Cola"], KB)
    assert "exclusivity" in c.note.lower()
    assert "PepsiCo" in c.note and "Coca-Cola" in c.note
