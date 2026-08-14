"""Gemini video-scan client: detects clearable elements in footage.

The live client (Phase 2) sends footage to Gemini on Vertex AI with a
structured-output schema; the fixture client replays a recorded scan through
the same parser so demo mode exercises the identical code path.
"""

import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from clearframe.models import DetectedElement, TimeRange

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
    "and whether it is integral to the plot. Report ranges you could not analyze "
    "as unscanned_ranges. Be exhaustive: missing an element creates legal risk."
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
    return ScanResult(detections=detections, unscanned_ranges=unscanned)


class GeminiClient(Protocol):
    async def scan(self, footage_uri: str, duration_s: float) -> ScanResult: ...


class FixtureGeminiClient:
    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = Path(fixtures_dir)

    async def scan(self, footage_uri: str, duration_s: float) -> ScanResult:
        payload = json.loads((self.fixtures_dir / "demo_scene.json").read_text())
        return parse_scan_payload(payload)
