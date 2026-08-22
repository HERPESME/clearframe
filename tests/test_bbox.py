"""Bounding boxes: asked for, parsed, and never allowed to lose a detection.

The video player overlays `DetectedElement.bbox`. The demo fixture carries
hand-written boxes so the overlay looked right — but the scan never asked
Gemini for one and the response schema had no field for it, so on real footage
every box was None and the player rendered an empty overlay. A live run
confirmed it: 11 detections, 0 boxes.

`models.BBox` documented that "Gemini returns [ymin, xmin, ymax, xmax] scaled
0-1000; the parser divides by 1000". No parser did.
"""

import pytest

from clearframe.integrations.gemini_client import (
    SCAN_PROMPT,
    SCAN_RESPONSE_SCHEMA,
    parse_scan_payload,
)


def element(**kw):
    base = {
        "id": "e1",
        "label": "Bayer Aspirin",
        "element_type": "LOGO",
        "description": "tin on the counter",
        "time_ranges": [{"start_s": 1.0, "end_s": 6.0}],
        "prominence": {
            "screen_time_s": 5.0, "frame_coverage": 0.2,
            "centrality": 0.6, "plot_integral": False,
        },
    }
    base.update(kw)
    return {"elements": [base], "unscanned_ranges": []}


# ------------------------------------------------------------ it is asked for
def test_the_prompt_asks_for_a_box():
    assert "box" in SCAN_PROMPT.lower()


def test_the_schema_has_a_field_for_it():
    props = SCAN_RESPONSE_SCHEMA["properties"]["elements"]["items"]["properties"]
    assert "bbox" in props


# ---------------------------------------------------------------- it is parsed
def test_geminis_thousand_scale_is_normalised():
    """[ymin, xmin, ymax, xmax] scaled 0-1000 — Gemini's documented convention."""
    (d,) = parse_scan_payload(element(bbox=[520, 410, 790, 550])).detections
    assert d.bbox.ymin == pytest.approx(0.52)
    assert d.bbox.xmin == pytest.approx(0.41)
    assert d.bbox.ymax == pytest.approx(0.79)
    assert d.bbox.xmax == pytest.approx(0.55)


def test_an_already_normalised_box_is_left_alone():
    """Some model versions answer 0-1. Dividing again would collapse the box
    into the top-left corner, which renders as a dot and looks like a bug in
    the player rather than in the parser."""
    (d,) = parse_scan_payload(element(bbox=[0.52, 0.41, 0.79, 0.55])).detections
    assert d.bbox.ymin == pytest.approx(0.52)
    assert d.bbox.xmax == pytest.approx(0.55)


def test_out_of_range_values_are_clamped():
    (d,) = parse_scan_payload(element(bbox=[-20, 0, 1200, 1000])).detections
    assert d.bbox.ymin == 0.0 and d.bbox.ymax == 1.0


def test_a_dict_shaped_box_is_accepted_too():
    (d,) = parse_scan_payload(
        element(bbox={"ymin": 0.1, "xmin": 0.2, "ymax": 0.3, "xmax": 0.4})
    ).detections
    assert d.bbox.ymin == pytest.approx(0.1)


# -------------------------------------------- a bad box must not cost a finding
@pytest.mark.parametrize(
    "bad",
    [
        [500, 400, 500, 400],      # degenerate — zero area
        [900, 400, 100, 550],      # inverted
        [1, 2, 3],                 # wrong arity
        "somewhere on the left",   # not a box at all
        None,
    ],
)
def test_an_unusable_box_drops_the_box_and_keeps_the_detection(bad):
    """The recall rule. Losing a real finding because the model returned a
    malformed rectangle would trade the product's whole safety claim for a
    UI nicety."""
    result = parse_scan_payload(element(bbox=bad))
    assert len(result.detections) == 1, f"detection lost over bbox={bad!r}"
    assert result.detections[0].label == "Bayer Aspirin"
    assert result.detections[0].bbox is None


def test_no_box_at_all_still_parses():
    (d,) = parse_scan_payload(element()).detections
    assert d.bbox is None


def test_a_genuinely_invalid_element_is_still_skipped():
    """The guard above must not turn into "accept anything"."""
    broken = element()
    del broken["elements"][0]["label"]
    assert parse_scan_payload(broken).detections == []
