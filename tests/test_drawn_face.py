"""One drawn character, typed two ways, answered two ways.

A live run of a Code Geass clip produced this pair:

    id 2       CHARACTER  "Pizza Hut Delivery Driver"  LOCAL    element of the work
    id 2345-a  FACE       "Pizza Hut Delivery Driver"  STATUTE  obtain a personal release

Identical labels, overlapping appearances, one cartoon. The player drew two
boxes for him, and the dossier carried two contradictory answers to the only
question that matters: is this covered by a licence to Code Geass, or does a
delivery driver who does not exist need to sign a release?

`triage` could not join them. Grouping requires the same element type, and the
one cross-type bridge is TEXT — added for a brand a pass read as lettering.
CHARACTER and FACE are both rights-bearing types, so neither yields.

The resolution belongs upstream, in `sourcework.corrected_types`, which
already coerces the OTHER direction: a CHARACTER in a live-action work is a
real actor. The mirror is that a FACE in a DRAWN work is a drawn character —
there is nobody to consent, and the right that exists is copyright in the
design.

Deliberately narrow. Only a FACE whose label matches a CHARACTER **in the same
scan** is coerced, because that is a contradiction between two passes about
one object, and resolving it invents nothing. A lone FACE in an animation is
left alone: a drawn work can contain a photograph of a real person, and
CHARACTER is subsumable by a licence to the work, so a blanket rule could
suppress a release that was genuinely needed.
"""

from clearframe.models import (
    DetectedElement,
    ElementType,
    Prominence,
    SourceWork,
    TimeRange,
)
from clearframe.sourcework import corrected_types

DRAWN = SourceWork(
    title="Code Geass: Lelouch of the Rebellion",
    rights_holder="Sunrise", confidence="high",
    basis="Character designs and art style are characteristic of the series.",
    medium="animation",
)
LIVE = DRAWN.model_copy(update={"title": "The Hangover Part II", "medium": "live_action"})


def det(label, kind, start=1.0, end=5.0):
    return DetectedElement(
        id=f"{label[:6]}-{kind.value[:3]}", label=label, element_type=kind,
        description="", time_ranges=[TimeRange(start_s=start, end_s=end)],
        prominence=Prominence(screen_time_s=4.0, frame_coverage=0.3,
                              centrality=0.6, plot_integral=True),
    )


def test_a_face_the_other_pass_called_a_character_is_a_character():
    out = corrected_types([
        det("Pizza Hut Delivery Driver", ElementType.CHARACTER),
        det("Pizza Hut Delivery Driver", ElementType.FACE),
    ], DRAWN)
    assert [d.element_type for d in out] == [ElementType.CHARACTER, ElementType.CHARACTER]


def test_the_two_then_become_one_finding():
    """The point of the fix — one object, one route, one answer."""
    from clearframe.triage import triage

    out = triage(corrected_types([
        det("Pizza Hut Delivery Driver", ElementType.CHARACTER, 2.9, 8.8),
        det("Pizza Hut Delivery Driver", ElementType.FACE, 3.0, 8.4),
    ], DRAWN))
    assert len(out) == 1
    assert out[0].element_type is ElementType.CHARACTER
    assert out[0].category.value == "COPYRIGHT_ART"


def test_a_near_miss_label_still_counts():
    """The passes phrase things differently; that is why they disagree at all."""
    out = corrected_types([
        det("Pizza Hut delivery driver", ElementType.CHARACTER),
        det("The Pizza Hut Delivery Driver", ElementType.FACE),
    ], DRAWN)
    assert [d.element_type for d in out] == [ElementType.CHARACTER, ElementType.CHARACTER]


def test_a_lone_face_in_a_drawn_work_is_left_alone():
    """A drawn work can contain a photograph, and CHARACTER is subsumable.

    Coercing this would risk suppressing a release that was genuinely needed,
    which is the one direction this product must never be wrong in.
    """
    out = corrected_types([det("Woman in a photograph", ElementType.FACE)], DRAWN)
    assert out[0].element_type is ElementType.FACE


def test_an_unrelated_character_does_not_coerce_a_face():
    out = corrected_types([
        det("Lelouch Lamperouge", ElementType.CHARACTER),
        det("Pizza Hut Delivery Driver", ElementType.FACE),
    ], DRAWN)
    assert [d.element_type for d in out] == [ElementType.CHARACTER, ElementType.FACE]


def test_live_action_still_goes_the_other_way():
    out = corrected_types([
        det("Stu Price", ElementType.CHARACTER),
        det("Stu Price", ElementType.FACE),
    ], LIVE)
    assert [d.element_type for d in out] == [ElementType.FACE, ElementType.FACE]


def test_an_unknown_medium_changes_nothing():
    vague = DRAWN.model_copy(update={"medium": "unknown"})
    out = corrected_types([
        det("Pizza Hut Delivery Driver", ElementType.CHARACTER),
        det("Pizza Hut Delivery Driver", ElementType.FACE),
    ], vague)
    assert [d.element_type for d in out] == [ElementType.CHARACTER, ElementType.FACE]
