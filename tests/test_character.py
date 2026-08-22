"""A drawn character is not a person, and cannot sign a release.

Found by uploading an anime clip. The scan reported C.C., Lelouch, Nunnally
and Arthur the cat as FACE, triage mapped every FACE to RIGHT_OF_PUBLICITY,
and the router produced "obtain a personal release" — for drawings, and for a
cat.

Two things are wrong with that. A fictional character has no right of
publicity: there is no person to consent. And the right that DOES exist is
copyright in the character design, owned by the studio — cleared by a licence,
which is a different instrument, a different counterparty and a different cost.

This matters well beyond anime: animation, VFX creatures, game capture and
CGI doubles all put drawn faces on screen.
"""

import pytest

from clearframe.knowledge import load_knowledge
from clearframe.models import (
    ClearanceCategory,
    DetectedElement,
    ElementType,
    Prominence,
    ResearchTier,
    TimeRange,
)
from clearframe.routing import route
from clearframe.triage import triage

KB = load_knowledge()


def detected(element_type, label="C.C."):
    return DetectedElement(
        id="e1", label=label, element_type=element_type,
        description="", time_ranges=[TimeRange(start_s=1.0, end_s=9.0)],
        prominence=Prominence(screen_time_s=8.0, frame_coverage=0.3,
                              centrality=0.7, plot_integral=True),
    )


def test_a_character_is_a_copyright_question_not_a_publicity_one():
    (el,) = triage([detected(ElementType.CHARACTER)])
    assert el.category is ClearanceCategory.COPYRIGHT_ART


def test_a_real_face_is_unchanged():
    """The existing path must not move."""
    (el,) = triage([detected(ElementType.FACE, "Background passerby")])
    assert el.category is ClearanceCategory.RIGHT_OF_PUBLICITY


def test_a_character_is_never_sent_to_get_a_release():
    (el,) = triage([detected(ElementType.CHARACTER)])
    r = route(el, KB)
    assert "release" not in r.disposition.lower()
    assert r.tier is ResearchTier.DEEP  # who owns the design is the question


def test_the_scan_can_report_one():
    from clearframe.integrations.gemini_client import (
        SCAN_PROMPT,
        SCAN_RESPONSE_SCHEMA,
        parse_scan_payload,
    )

    enum = SCAN_RESPONSE_SCHEMA["properties"]["elements"]["items"]["properties"][
        "element_type"
    ]["enum"]
    assert "CHARACTER" in enum
    assert "character" in SCAN_PROMPT.lower()

    payload = {
        "elements": [
            {
                "id": "e1", "label": "Lelouch Lamperouge",
                "element_type": "CHARACTER", "description": "animated character",
                "time_ranges": [{"start_s": 1.0, "end_s": 9.0}],
                "prominence": {"screen_time_s": 8.0, "frame_coverage": 0.3,
                               "centrality": 0.7, "plot_integral": True},
            }
        ],
        "unscanned_ranges": [],
    }
    (d,) = parse_scan_payload(payload).detections
    assert d.element_type is ElementType.CHARACTER


def test_the_prompt_says_which_one_to_use():
    """The distinction is only useful if the model can apply it."""
    from clearframe.integrations.gemini_client import SCAN_PROMPT

    lowered = SCAN_PROMPT.lower()
    assert "real person" in lowered or "actual person" in lowered
    assert "animated" in lowered or "fictional" in lowered
