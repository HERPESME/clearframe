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

from clearframe.models import (
    BBox,
    ClearanceCategory,
    DetectedElement,
    ElementType,
    Prominence,
    TimeRange,
)
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


# --- Two more pairs that survived the labels_match rule, measured on a live
# --- Hangover Part II run. Both are one object; both were routed twice.

def boxed(label, kind, appearances, description=""):
    """A detection whose boxes live on the appearances, as a live scan returns."""
    return DetectedElement(
        id=label[:6], label=label, element_type=kind, description=description,
        time_ranges=[
            TimeRange(start_s=a, end_s=b, bbox=BBox(**box)) for a, b, box in appearances
        ],
        prominence=Prominence(screen_time_s=3.0, frame_coverage=0.2,
                              centrality=0.5, plot_integral=False),
    )


# Stu's face at 5-8s, measured by each pass. The labels share only {face,
# tattoo} — 2 of 4 tokens, 0.5 against a 0.6 threshold — so labels_match says
# no. Asked to place both on the frame at 6s, the grounding pass returned the
# byte-identical rectangle for each.
_TYSON = (5.105, 7.941, {"ymin": .427, "xmin": .511, "ymax": .622, "xmax": .810})
_STU = (5.2, 7.9, {"ymin": .272, "xmin": .655, "ymax": .498, "xmax": .816})


def test_one_tattoo_measured_twice_in_the_same_place_is_one_finding():
    out = triage([
        boxed("Mike Tyson face tattoo", ElementType.TATTOO, [_TYSON],
              description="a tattoo around the left eye, resembling Mike Tyson's"),
        boxed("Stu's Face Tattoo", ElementType.TATTOO, [_STU],
              description="modeled after Mike Tyson's famous face tattoo"),
    ])
    assert len(out) == 1


def test_two_marks_in_one_shot_in_different_places_stay_separate():
    """The objection to time-overlap matching, encoded so it cannot regress.

    A waistband and a wrist are on screen together for the whole of one shot.
    Same type, labels that share nothing — and they are two findings.
    """
    out = triage([
        boxed("Calvin Klein", ElementType.LOGO,
              [(22.923, 25.425, {"ymin": .930, "xmin": .605, "ymax": .984, "xmax": .801})]),
        boxed("IWC Watch", ElementType.LOGO,
              [(23.0, 25.5, {"ymin": .44, "xmin": .57, "ymax": .56, "xmax": .70})]),
    ])
    assert len(out) == 2


def test_the_same_place_at_a_different_time_stays_separate():
    out = triage([
        boxed("Poster", ElementType.ARTWORK, [(1.0, 4.0, dict(zip(
            ("ymin", "xmin", "ymax", "xmax"), (.2, .2, .6, .6))))]),
        boxed("Mirror", ElementType.ARTWORK, [(30.0, 33.0, dict(zip(
            ("ymin", "xmin", "ymax", "xmax"), (.2, .2, .6, .6))))]),
    ])
    assert len(out) == 2


# --- A mark the second pass read as lettering rather than recognising.

def test_a_brand_read_as_text_merges_with_the_mark_it_names():
    """"Calvin Klein" arrived twice: once LOGO, once TEXT, one waistband.

    The two boxes do not even overlap — the passes put the waistband at
    slightly different heights — so only the identical label and the shared
    moment connect them. TEXT is the type that yields, because
    TEXT_ON_SCREEN is what the scan produces when it reads letters instead of
    recognising the thing wearing them.
    """
    out = triage([
        boxed("Calvin Klein", ElementType.LOGO,
              [(22.923, 25.425, {"ymin": .930, "xmin": .605, "ymax": .984, "xmax": .801})],
              description="the 'Calvin Klein' brand name on the waistband"),
        boxed("Calvin Klein", ElementType.TEXT,
              [(23.3, 25.1, {"ymin": .887, "xmin": .496, "ymax": .917, "xmax": .709})],
              description="the brand name 'Calvin Klein' partially visible"),
    ])
    assert len(out) == 1
    assert out[0].element_type is ElementType.LOGO
    assert out[0].category is ClearanceCategory.TRADEMARK


def test_genuine_on_screen_text_is_not_swallowed_by_a_mark():
    out = triage([
        boxed("Calvin Klein", ElementType.LOGO,
              [(22.9, 25.4, {"ymin": .93, "xmin": .60, "ymax": .98, "xmax": .80})]),
        boxed("On-screen text", ElementType.TEXT,
              [(22.9, 25.4, {"ymin": .69, "xmin": .29, "ymax": .77, "xmax": .65})]),
    ])
    assert len(out) == 2


def test_a_whole_frame_box_is_not_evidence_that_two_things_are_one():
    """Two actors, one shared instant, and one box around the entire frame.

    Found by replaying a real run's detections through the new rule rather
    than by the suite: "Stu Price (Ed Helms)" and "Alan Garner (Zach
    Galifianakis)" overlap for a tenth of a second at 15.5s, and Stu's box
    there is {0, 0, 1, 1}. A rectangle around the whole picture overlaps every
    other rectangle in it, so colocation became true for any pair that shared
    an instant — and Ed Helms was deleted from the report.

    A box that does not locate its own subject cannot locate anyone else's.
    """
    out = triage([
        boxed("Stu Price (Ed Helms)", ElementType.FACE,
              [(15.5, 18.5, {"ymin": 0.0, "xmin": 0.0, "ymax": 1.0, "xmax": 1.0})]),
        boxed("Alan Garner (Zach Galifianakis)", ElementType.FACE,
              [(13.8, 15.6, {"ymin": .22, "xmin": .36, "ymax": .88, "xmax": .98})]),
    ])
    assert len(out) == 2


def test_two_characters_sharing_a_shot_are_not_one_character():
    """Colocation cannot manufacture agreement out of nothing.

    Found by replaying a live Code Geass run. Two people standing in one frame
    overlap — that is what standing next to someone looks like — so "same type,
    same instant, same place" merged Lelouch with C.C., and merged Arthur (a
    cat) with the pizza delivery guy. Both absorbed findings were DELETED from
    the report, and the survivor took the longer label, so the cat's group came
    out labelled "Pizza Delivery Guy".

    The rule is now what it should always have been: a shared instant and a
    shared place can PROMOTE a label agreement that fell just short of the
    threshold. They cannot substitute for one. Lelouch and C.C. share no token
    at all.
    """
    frame_left = {"ymin": .15, "xmin": .10, "ymax": .90, "xmax": .55}
    frame_right = {"ymin": .18, "xmin": .40, "ymax": .88, "xmax": .85}
    out = triage([
        boxed("Lelouch Lamperouge", ElementType.CHARACTER, [(5.0, 11.4, frame_left)]),
        boxed("C.C.", ElementType.CHARACTER, [(5.0, 11.4, frame_right)]),
    ])
    assert len(out) == 2


def test_a_cat_and_a_delivery_driver_stay_two_findings():
    out = triage([
        boxed("Arthur", ElementType.CHARACTER,
              [(2.0, 9.0, {"ymin": .55, "xmin": .20, "ymax": .95, "xmax": .60})]),
        boxed("Pizza Delivery Guy", ElementType.CHARACTER,
              [(2.0, 9.0, {"ymin": .10, "xmin": .15, "ymax": .90, "xmax": .70})]),
    ])
    assert len(out) == 2


def test_colocation_still_rescues_a_label_that_nearly_matched():
    """The tattoo pair: {face, tattoo} shared, 0.5 against a 0.6 threshold."""
    out = triage([
        boxed("Mike Tyson face tattoo", ElementType.TATTOO, [_TYSON]),
        boxed("Stu's Face Tattoo", ElementType.TATTOO, [_STU]),
    ])
    assert len(out) == 1
