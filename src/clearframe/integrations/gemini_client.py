"""Gemini video-scan client: detects clearable elements in footage.

The live client (Phase 2) sends footage to Gemini on Vertex AI with a
structured-output schema; the fixture client replays a recorded scan through
the same parser so demo mode exercises the identical code path.
"""

import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from clearframe.models import (
    DetectedElement,
    ExposureFinding,
    ScriptMention,
    TimeRange,
)

SCAN_PROMPT = (
    "You are a film clearance coordinator reviewing raw footage frame by frame. "
    "Identify EVERY element that may require legal clearance before distribution: "
    "brand logos, trademarks, artwork (posters, murals, paintings, photographs), "
    "audible music, recognizable faces of non-cast individuals, tattoos, "
    "distinctive locations/storefronts, and readable on-screen text. For each "
    "element report: a short label, its type (LOGO, ARTWORK, MUSIC, FACE, TATTOO, "
    "LOCATION, TEXT), a one-sentence description, every time range in which it "
    "appears (seconds), and prominence estimates: total screen time in seconds, "
    "fraction of frame covered (0-1), how central it is to the composition (0-1), "
    "and whether it is integral to the plot. "
    "For brands, businesses, places and people, also report how the element is "
    "PORTRAYED as `depiction`: FAVOURABLE (shown positively, reads as an "
    "endorsement), NEUTRAL (simply present), UNFLATTERING (associated with "
    "failure, mess or mishap), or DISPARAGING (associated with harm, crime, "
    "illness or contempt). Judge only what is shown on screen; if the portrayal "
    "is not clear, use NEUTRAL. This matters because rights holders object to "
    "how a brand is depicted far more often than to its mere presence. "
    "Separately, report anything visible that should probably not be PUBLISHED "
    "at all, as `exposures` — these are not clearance items and nobody owns "
    "them, which is exactly why they get missed. Kinds: MINOR (an identifiable "
    "child), PERSONAL_DATA (a readable address, phone number, email or account "
    "number), DOCUMENT (a readable letter, statement or identity paper), "
    "SCREEN_CONTENT (a phone or monitor showing private content), "
    "VEHICLE_PLATE, LOCATION_IDENTIFIER (a house number or street sign at a "
    "residence). For each give id, kind, description and time_ranges. Report "
    "only what is actually legible or identifiable on screen. "
    "Report ranges you could not analyze "
    "as unscanned_ranges. Be exhaustive: missing an element creates legal risk."
)

SCRIPT_PROMPT = (
    "You are a script clearance reader. Read this screenplay text and list every "
    "element that will require legal clearance when filmed: brand names/logos, "
    "real songs, artwork/posters, real businesses or locations, and readable "
    "media. For each: a short label, its type (LOGO, ARTWORK, MUSIC, LOCATION, "
    "TEXT), and the scene heading it appears under. Return JSON: "
    '{"mentions": [{"label", "element_type", "scene"}]}.'
)

SCRIPT_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "element_type": {
                        "type": "string",
                        "enum": ["LOGO", "ARTWORK", "MUSIC", "FACE", "TATTOO", "LOCATION", "TEXT"],
                    },
                    "scene": {"type": "string"},
                },
                "required": ["label", "element_type", "scene"],
            },
        }
    },
    "required": ["mentions"],
}

AUDIT_PROMPT_TEMPLATE = (
    "You are the studio's E&O clearance AUDITOR, reviewing another coordinator's "
    "work on this footage. The first pass found these elements: {found}. "
    "Watch the footage again and report ONLY clearable elements the first pass "
    "MISSED — background screens playing copyrighted content, reflections, "
    "quiet audio, partially visible artwork, signage, tattoos, or faces they "
    "overlooked. Use the same JSON format. If nothing was missed, return an "
    "empty elements list. Do not repeat elements already found."
)

SCAN_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "element_type": {
                        "type": "string",
                        "enum": ["LOGO", "ARTWORK", "MUSIC", "FACE", "TATTOO", "LOCATION", "TEXT"],
                    },
                    "description": {"type": "string"},
                    "time_ranges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_s": {"type": "number"},
                                "end_s": {"type": "number"},
                            },
                            "required": ["start_s", "end_s"],
                        },
                    },
                    "depiction": {
                        "type": "string",
                        "enum": ["FAVOURABLE", "NEUTRAL", "UNFLATTERING", "DISPARAGING"],
                    },
                    "prominence": {
                        "type": "object",
                        "properties": {
                            "screen_time_s": {"type": "number"},
                            "frame_coverage": {"type": "number"},
                            "centrality": {"type": "number"},
                            "plot_integral": {"type": "boolean"},
                        },
                        "required": [
                            "screen_time_s",
                            "frame_coverage",
                            "centrality",
                            "plot_integral",
                        ],
                    },
                },
                "required": ["id", "label", "element_type", "description", "time_ranges", "prominence"],
            },
        },
        "exposures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "MINOR", "PERSONAL_DATA", "DOCUMENT",
                            "SCREEN_CONTENT", "VEHICLE_PLATE", "LOCATION_IDENTIFIER",
                        ],
                    },
                    "description": {"type": "string"},
                    "time_ranges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_s": {"type": "number"},
                                "end_s": {"type": "number"},
                            },
                            "required": ["start_s", "end_s"],
                        },
                    },
                },
                "required": ["id", "kind", "description", "time_ranges"],
            },
        },
        "unscanned_ranges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                },
                "required": ["start_s", "end_s"],
            },
        },
    },
    "required": ["elements", "unscanned_ranges"],
}


class ScanResult(BaseModel):
    detections: list[DetectedElement]
    unscanned_ranges: list[TimeRange]
    # Not clearance items — things on screen that should probably not be
    # published at all. Optional so every prior fixture still parses.
    exposures: list[ExposureFinding] = []


def parse_scan_payload(payload: dict) -> ScanResult:
    detections: list[DetectedElement] = []
    skipped = 0
    for entry in payload.get("elements") or []:
        try:
            detections.append(DetectedElement.model_validate(entry))
        except ValidationError:
            skipped += 1
    unscanned = [
        TimeRange.model_validate(r) for r in payload.get("unscanned_ranges") or []
    ]
    exposures: list[ExposureFinding] = []
    for entry in payload.get("exposures") or []:
        try:
            exposures.append(ExposureFinding.model_validate(entry))
        except ValidationError:
            skipped += 1
    return ScanResult(
        detections=detections, unscanned_ranges=unscanned, exposures=exposures
    )


def parse_script_payload(payload: dict) -> list[ScriptMention]:
    mentions: list[ScriptMention] = []
    for entry in payload.get("mentions") or []:
        try:
            mentions.append(ScriptMention.model_validate(entry))
        except ValidationError:
            continue
    return mentions


class GeminiClient(Protocol):
    async def scan(self, footage_uri: str, duration_s: float) -> ScanResult: ...

    async def audit_scan(
        self, footage_uri: str, duration_s: float, found_labels: list[str]
    ) -> ScanResult: ...

    async def scan_script(self, text: str) -> list[ScriptMention]: ...


class FixtureGeminiClient:
    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = Path(fixtures_dir)

    async def scan(self, footage_uri: str, duration_s: float) -> ScanResult:
        payload = json.loads((self.fixtures_dir / "demo_scene.json").read_text())
        return parse_scan_payload(payload)

    async def audit_scan(
        self, footage_uri: str, duration_s: float, found_labels: list[str]
    ) -> ScanResult:
        path = self.fixtures_dir / "demo_scene_audit.json"
        if not path.exists():
            return ScanResult(detections=[], unscanned_ranges=[])
        return parse_scan_payload(json.loads(path.read_text()))

    async def scan_script(self, text: str) -> list[ScriptMention]:
        path = self.fixtures_dir / "script_scan.json"
        if not path.exists():
            return []
        return parse_script_payload(json.loads(path.read_text()))
