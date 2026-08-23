"""Ground already-known labels against one still frame.

The scan says WHAT is in the footage and roughly when. This asks only WHERE,
on a single frame, for labels we already have — which is a far easier problem
than detection and is why the control experiment came back tight where the
video path did not.

It is deliberately incapable of adding findings. A grounding pass that could
introduce a new element would be a second, unaudited detector whose output
never went through triage, corroboration or routing; anything it names that
the scan did not is dropped.
"""

import json
import pathlib

import pytest

from clearframe.integrations.gemini_client import (
    FixtureGeminiClient,
    parse_ground_payload,
)

FIXTURES = pathlib.Path("src/clearframe/integrations/fixtures")


def test_boxes_come_back_keyed_by_label():
    boxes = parse_ground_payload(
        {"found": [
            {"label": "Nike hoodie swoosh",
             "bbox": {"ymin": 100, "xmin": 200, "ymax": 300, "xmax": 400}},
        ]},
        known=["Nike hoodie swoosh", "Coca-Cola can"],
    )
    assert set(boxes) == {"Nike hoodie swoosh"}
    assert boxes["Nike hoodie swoosh"].ymin == 0.1


def test_a_label_the_scan_never_found_is_dropped():
    """Grounding locates; it does not detect."""
    boxes = parse_ground_payload(
        {"found": [
            {"label": "A brand nobody scanned",
             "bbox": {"ymin": 10, "xmin": 10, "ymax": 90, "xmax": 90}},
        ]},
        known=["Nike hoodie swoosh"],
    )
    assert boxes == {}


def test_labels_are_matched_the_way_the_rest_of_the_codebase_matches_them():
    """The model rarely echoes a label verbatim."""
    boxes = parse_ground_payload(
        {"found": [
            {"label": "Nike swoosh on the hoodie",
             "bbox": {"ymin": 10, "xmin": 10, "ymax": 90, "xmax": 90}},
        ]},
        known=["Nike hoodie swoosh"],
    )
    assert set(boxes) == {"Nike hoodie swoosh"}


def test_an_unusable_box_costs_only_its_own_entry():
    boxes = parse_ground_payload(
        {"found": [
            {"label": "Nike hoodie swoosh", "bbox": {"ymin": 900, "xmin": 10,
                                                     "ymax": 100, "xmax": 90}},
            {"label": "Coca-Cola can", "bbox": {"ymin": 10, "xmin": 10,
                                                "ymax": 90, "xmax": 90}},
        ]},
        known=["Nike hoodie swoosh", "Coca-Cola can"],
    )
    assert set(boxes) == {"Coca-Cola can"}


def test_rubbish_payloads_are_survivable():
    for payload in ({}, {"found": None}, {"found": ["nonsense"]}, {"found": [{}]}):
        assert parse_ground_payload(payload, known=["Anything"]) == {}


@pytest.mark.asyncio
async def test_the_fixture_client_grounds_without_a_network():
    client = FixtureGeminiClient(FIXTURES)
    boxes = await client.ground_frame(b"\xff\xd8fake", ["Nike hoodie swoosh"])
    assert "Nike hoodie swoosh" in boxes


def test_a_box_around_the_whole_frame_is_not_a_location():
    """The one answer the grounding pass gives reliably for people.

    {0, 0, 1, 1} for "Stu Price (Ed Helms)" at 6s and again at 9s, while the
    IWC watch in the same shot came back to the pixel. Dropped here so
    "grounded, and not placed" stays the honest answer rather than a rectangle
    over the whole picture.
    """
    payload = {"found": [
        {"label": "Stu Price", "bbox": {"ymin": 0.0, "xmin": 0.0,
                                        "ymax": 1.0, "xmax": 1.0}},
        {"label": "IWC Watch", "bbox": {"ymin": 0.562, "xmin": 0.318,
                                        "ymax": 0.708, "xmax": 0.498}},
    ]}
    out = parse_ground_payload(payload, ["Stu Price", "IWC Watch"])
    assert set(out) == {"IWC Watch"}
