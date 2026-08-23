"""Two passes name the same thing differently, and triage matched exact strings.

Adding a second independent scan pass raised recall, and immediately produced
duplicates the old dedupe could not see. On a live Hangover Part II run:

    Stu's Face Tattoo      DEEP     "replicating Mike Tyson's famous tattoo"
    Face Tattoo            STATUTE  (plainer description)

    National Water Heater  DEEP
    National               SEARCH

One object, two findings, two different routes and two different answers — and
in the tattoo's case the two halves disagreed about whether it was the Whitmill
fact pattern. `triage` grouped on `(element_type, label.casefold())`, which is
exact string equality; the passes rarely phrase a label the same way twice.

Matching is deliberately conservative. Under-merging leaves a duplicate finding
— annoying, and it costs a research run. Over-merging DELETES a finding, which
is the failure this product exists to prevent. So a merge needs the same
element type and a `labels_match`, and anything short of that stays separate.
"""

from clearframe.models import DetectedElement, ElementType, Prominence, TimeRange
from clearframe.triage import triage


def det(label, kind=ElementType.TATTOO, description="", ranges=((1.0, 5.0),)):
    return DetectedElement(
        id=label[:4], label=label, element_type=kind, description=description,
        time_ranges=[TimeRange(start_s=a, end_s=b) for a, b in ranges],
        prominence=Prominence(screen_time_s=4.0, frame_coverage=0.2,
                              centrality=0.5, plot_integral=False),
    )


def test_two_phrasings_of_one_finding_become_one():
    out = triage([
        det("Stu's Face Tattoo", description="replicating Mike Tyson's tattoo"),
        det("Face Tattoo", description="a tribal tattoo"),
    ])
    assert len(out) == 1


def test_the_richer_description_survives_the_merge():
    """Routing reads the description — the Whitmill test lives in it."""
    out = triage([
        det("Face Tattoo", description="a tribal tattoo"),
        det("Stu's Face Tattoo", description="replicating Mike Tyson's famous tattoo"),
    ])
    assert "replicating" in out[0].description


def test_a_qualified_label_merges_with_its_bare_form():
    out = triage([
        det("National Water Heater", ElementType.LOGO),
        det("National", ElementType.LOGO),
    ])
    assert len(out) == 1


def test_different_things_are_never_merged():
    out = triage([
        det("Dog T-Shirt", ElementType.ARTWORK),
        det("Duck Figurine", ElementType.ARTWORK),
    ])
    assert len(out) == 2


def test_a_weak_resemblance_is_not_enough():
    """'Character's Watch' and 'IWC Schaffhausen Watch' share only 'watch'.

    They probably are one object, and they stay two findings anyway. A
    duplicate costs a research run; a wrong merge costs a finding.
    """
    out = triage([
        det("IWC Schaffhausen Watch", ElementType.LOGO),
        det("Character's Watch", ElementType.LOGO),
    ])
    assert len(out) == 2


def test_the_same_label_under_different_types_stays_separate():
    out = triage([
        det("Nike", ElementType.LOGO),
        det("Nike", ElementType.ARTWORK),
    ])
    assert len(out) == 2
