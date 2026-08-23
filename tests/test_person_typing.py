"""A real actor is not a drawn character, whatever the scan says.

`ElementType.CHARACTER` exists for a specific legal reason: a drawn character
has no right of publicity, because there is nobody to consent. The right that
does exist is copyright in the design, owned by the studio and cleared by a
licence to the work. That is why CHARACTER maps to COPYRIGHT_ART and FACE maps
to RIGHT_OF_PUBLICITY.

Applied to a live actor it inverts: Bradley Cooper stops needing a personal
release and becomes a drawing somebody owns. On a live clip of The Hangover
Part II that is exactly what happened — three actors came back as CHARACTER,
were categorised COPYRIGHT_ART, and were then banded under freedom-of-panorama
rules for permanently-sited sculptures.

The scan prompt already says "use FACE only for a REAL PERSON captured on
camera". It is ignored intermittently: across three identical runs of the same
clip, one typed all three actors CHARACTER, one typed them FACE, one found no
people at all. A prompt is not a contract, so the guard is in code.

We only correct where we can prove it: a work the scan identified as
live_action cannot contain a drawn character playing its lead.
"""

from clearframe.models import (
    DetectedElement,
    ElementType,
    Prominence,
    SourceWork,
    TimeRange,
)
from clearframe.sourcework import corrected_types

LIVE = SourceWork(
    title="The Hangover Part II",
    rights_holder="Warner Bros. Pictures",
    confidence="high",
    basis="The actors and the face tattoo are characteristic of the film.",
    medium="live_action",
)
DRAWN = LIVE.model_copy(update={"title": "Code Geass", "medium": "animation"})


def det(label: str, kind: ElementType) -> DetectedElement:
    return DetectedElement(
        id="1", label=label, element_type=kind, description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=4.0)],
        prominence=Prominence(screen_time_s=3.0, frame_coverage=0.2,
                              centrality=0.6, plot_integral=True),
    )


def test_an_actor_in_a_live_action_film_is_a_person():
    out = corrected_types([det("Phil Wenneck", ElementType.CHARACTER)], LIVE)
    assert out[0].element_type is ElementType.FACE


def test_a_drawn_character_in_a_drawn_work_is_left_alone():
    out = corrected_types([det("Lelouch Lamperouge", ElementType.CHARACTER)], DRAWN)
    assert out[0].element_type is ElementType.CHARACTER


def test_an_unknown_medium_changes_nothing():
    """We correct only what we can prove."""
    vague = LIVE.model_copy(update={"medium": "unknown"})
    out = corrected_types([det("Someone", ElementType.CHARACTER)], vague)
    assert out[0].element_type is ElementType.CHARACTER

    out = corrected_types([det("Someone", ElementType.CHARACTER)], None)
    assert out[0].element_type is ElementType.CHARACTER


def test_nothing_else_is_touched():
    """A tattoo in a live-action film is still a tattoo."""
    items = [
        det("Stu's Face Tattoo", ElementType.TATTOO),
        det("Calvin Klein", ElementType.LOGO),
        det("Dog T-Shirt", ElementType.ARTWORK),
    ]
    out = corrected_types(items, LIVE)
    assert [e.element_type for e in out] == [
        ElementType.TATTOO, ElementType.LOGO, ElementType.ARTWORK,
    ]


def test_the_correction_reaches_the_clearance_category():
    """The point of the fix: a release, not a copyright licence."""
    from clearframe.triage import triage

    out = triage(corrected_types([det("Stu Price", ElementType.CHARACTER)], LIVE))
    assert out[0].category.value == "RIGHT_OF_PUBLICITY"
