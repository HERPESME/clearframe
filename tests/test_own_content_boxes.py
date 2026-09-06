"""The production's own graphics are recorded, not boxed.

A deployed run reported the film's own subtitles as a clearance finding —
`TEXT / "On-screen subtitles"`, seventeen boxed appearances across a 41.5s clip
— and the player drew a rectangle on every one of them.

The routing already knew. `_route_text` calls `is_own_content`, lands on
STATUTE, and writes the basis *"Own work — no third-party right implicated"* and
the disposition *"No action. Recorded so the dossier is complete, not because it
is a risk."* Then seventeen boxes went on screen anyway. The system reached the
right conclusion and drew the opposite of it.

A box exists so a reviewer can find and verify something they must act on.
`overlay.py` already refuses one that covers the whole frame, "because it
restates that the element is in the shot — which the finding already said". A
box on your own subtitles restates something nobody has to do anything about,
and it sits over the words it is describing.

The finding STAYS in the report. That is what the disposition already promises,
and a dossier that silently omits something plainly on screen is the worse
failure — the same asymmetry `cast.py` is careful about.
"""

from clearframe.models import (
    BBox,
    ClearanceCategory,
    DetectedElement,
    ElementType,
    Production,
    ProductionState,
    Prominence,
    TimeRange,
)
from clearframe.overlay import box_at, visible_at
from clearframe.triage import triage

_SUBTITLE_BAR = {"ymin": 0.894, "xmin": 0.349, "ymax": 0.941, "xmax": 0.586}
_ON_THE_HEATER = {"ymin": 0.254, "xmin": 0.526, "ymax": 0.278, "xmax": 0.636}


def _det(label, kind, box, description=""):
    return DetectedElement(
        id=label[:6],
        label=label,
        element_type=kind,
        description=description,
        time_ranges=[TimeRange(start_s=8.5, end_s=10.0, bbox=BBox(**box))],
        prominence=Prominence(screen_time_s=1.5, frame_coverage=0.02,
                              centrality=0.5, plot_integral=False),
    )


def _subtitles():
    return _det(
        "On-screen subtitles", ElementType.TEXT, _SUBTITLE_BAR,
        "White text with a black outline, providing subtitles for the dialogue.",
    )


def test_the_films_own_subtitles_are_marked_as_its_own_content():
    out = triage([_subtitles()])

    assert out[0].own_content is True
    assert out[0].category is ClearanceCategory.TEXT_ON_SCREEN


def test_a_photographed_brand_is_not_own_content():
    """The distinction is authored-in-post versus photographed. A sign, a
    packet, a headline is somebody else's text that the camera recorded."""
    out = triage([_det("National", ElementType.LOGO, _ON_THE_HEATER,
                       "The brand name on a yellowed water heater.")])

    assert out[0].own_content is False


def test_own_content_draws_no_box():
    out = triage([_subtitles()])

    assert box_at(out[0], 9.2) is None, "seventeen rectangles on the film's own text"


def test_own_content_is_still_listed_as_a_finding():
    """No box is not the same as no finding. The route says 'Recorded so the
    dossier is complete', and it has to actually be recorded."""
    out = triage([_subtitles()])

    assert len(out) == 1
    assert visible_at(out[0], 9.2) is True


def test_own_content_is_never_sent_to_grounding():
    """Two reasons. It spends a model call on a rectangle nobody will draw, and
    — the real one — a grounded box can no longer land on a subtitle."""
    from clearframe.grounding import elements_at, plan_seconds

    state = ProductionState(
        production=Production(id="p1", title="t", footage_uri="c.mp4",
                              duration_s=41.5, fps=30.0),
        elements=triage([
            _subtitles(),
            _det("National", ElementType.LOGO, _ON_THE_HEATER, "on a water heater"),
        ]),
    )

    assert [e.label for e in elements_at(state, 9.2)] == ["National"]
    assert plan_seconds(state) == plan_seconds(
        state.model_copy(update={"elements": [state.elements[1]]})
    )


def test_the_scope_is_the_same_one_routing_already_uses():
    """`_OWN_CONTENT` holds `lower`, `third`, `super` and `bug` — ordinary
    words. `_route_text` only ever consults it for TEXT_ON_SCREEN, and widening
    that here would strip the rectangle off a location called "Lower East Side".
    This test is the guard on the blast radius, not on the vocabulary."""
    out = triage([_det("Lower East Side", ElementType.LOCATION, _ON_THE_HEATER)])

    assert out[0].own_content is False
    assert box_at(out[0], 9.2) is not None
