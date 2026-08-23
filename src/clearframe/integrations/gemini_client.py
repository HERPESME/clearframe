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
    BBox,
    DetectedElement,
    ExposureFinding,
    SourceWork,
    ScriptMention,
    TimeRange,
)

SCAN_PROMPT = (
    "You are a film clearance coordinator reviewing raw footage frame by frame. "
    "Identify EVERY element that may require legal clearance before distribution: "
    "brand logos, trademarks, artwork (posters, murals, paintings, photographs), "
    "audible music, recognizable faces of non-cast individuals, tattoos, "
    "drawn or animated characters, "
    "distinctive locations/storefronts, and readable on-screen text. For each "
    "element report: a short label, its type (LOGO, ARTWORK, MUSIC, FACE, "
    "CHARACTER, TATTOO, LOCATION, TEXT), a one-sentence description, every "
    "time range in which it "
    "appears (seconds), and prominence estimates: total screen time in seconds, "
    "fraction of frame covered (0-1), how central it is to the composition (0-1), "
    "and whether it is integral to the plot. "
    "For anything with a visible position in frame, give a `bbox` INSIDE EACH "
    "time range — an object with named edges ymin, xmin, ymax, xmax normalised "
    "0-1000, measured where the element sits during THAT appearance. An element "
    "appearing in four shots needs four boxes: a box measured in one shot and "
    "reused for another is worse than none, because it points a reviewer at "
    "empty screen. If an element moves a lot within one range, split it into "
    "shorter ranges with their own boxes. Omit bbox for audio. "
    "For brands, businesses, places and people, also report how the element is "
    "PORTRAYED as `depiction`: FAVOURABLE (shown positively, reads as an "
    "endorsement), NEUTRAL (simply present), UNFLATTERING (associated with "
    "failure, mess or mishap), or DISPARAGING (associated with harm, crime, "
    "illness or contempt). Judge only what is shown on screen; if the portrayal "
    "is not clear, use NEUTRAL. This matters because rights holders object to "
    "how a brand is depicted far more often than to its mere presence. "
    "Use FACE only for a REAL PERSON captured on camera; use CHARACTER for a "
    "drawn, animated, rendered or otherwise fictional character. The two need "
    "opposite instruments: a real person signs a release, while a character's "
    "design is owned by a studio and must be licensed. "
    "If this footage appears to BE an existing published work — a scene from a "
    "released film, series, advert or game, rather than original material that "
    "merely contains third-party items — say so as `source_work` with its title, "
    "the studio or rights holder if you know it, your confidence (high/medium/"
    "low) and the evidence. Only claim it when you actually recognise the work; "
    "a wrong identification would suppress every finding inside it. "
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

_MEDIUM_DESCRIPTION = {
    "EXPRESSIVE": "a film, television or narrative short",
    "SPONSORED": "sponsored online video with a paid brand placement",
    "ADVERTISING": "a commercial advertisement or brand campaign",
    "NEWS": "a news or journalistic report",
    "EDUCATIONAL": "educational or critical commentary",
}

_MAX_SCRIPT_MENTIONS = 40


def build_scan_context(production, script_mentions) -> str:
    """Production context to hand the scan alongside the footage.

    Gemini already receives the whole mp4, so it hears the dialogue and reads
    on-screen text natively — that was never the gap. The gap was that it knew
    nothing ABOUT the production: not the title, not that this is an advert
    rather than a film, not who is paying for it, not what the script said.

    Context sharpens two judgements the scan is otherwise guessing at: how
    prominent something is to the story, and how it is portrayed.

    It must never license an omission. Detection breadth is this product's
    safety claim, and a hint about what matters is one careless sentence away
    from becoming permission to skip things — so the closing instruction below
    is load-bearing and has a test guarding it.
    """
    lines: list[str] = []

    if getattr(production, "use_context", None) is not None:
        medium = _MEDIUM_DESCRIPTION.get(production.use_context.value)
        if medium and production.use_context.value != "EXPRESSIVE":
            lines.append(f"- This work is {medium}.")

    sponsors = list(getattr(production, "sponsors", []) or [])
    if sponsors:
        lines.append(
            f"- Paying sponsors: {', '.join(sponsors)}. Their marks are authorised "
            "here, but you must still report them — the report has to be complete."
        )

    labels = [m.label for m in (script_mentions or [])][:_MAX_SCRIPT_MENTIONS]
    if labels:
        lines.append(
            f"- Named in the script: {', '.join(labels)}. Anything on screen that is "
            "NOT on this list matters more, not less — unscripted set dressing is "
            "what nobody budgeted clearance for."
        )

    if not lines:
        return ""

    title = getattr(production, "title", "") or "this production"
    return (
        f'\n\nPRODUCTION CONTEXT for "{title}":\n'
        + "\n".join(lines)
        + "\n\nUse this only to judge prominence and depiction more accurately. "
        "Report everything you observe regardless of the context above; it must "
        "not cause you to omit anything."
    )


def scan_prompt_with(context: str) -> str:
    """SCAN_PROMPT plus context. Empty context returns the prompt unchanged."""
    return SCAN_PROMPT + context if context else SCAN_PROMPT


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
                        "enum": [
                            "LOGO", "ARTWORK", "MUSIC", "FACE", "CHARACTER",
                            "TATTOO", "LOCATION", "TEXT",
                        ],
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
                        "enum": [
                            "LOGO", "ARTWORK", "MUSIC", "FACE", "CHARACTER",
                            "TATTOO", "LOCATION", "TEXT",
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
                                # Per APPEARANCE. An element in four shots
                                # needs four boxes; one reused across all of
                                # them points a reviewer at empty screen.
                                "bbox": {
                                    "type": "object",
                                    "properties": {
                                        "ymin": {"type": "number"},
                                        "xmin": {"type": "number"},
                                        "ymax": {"type": "number"},
                                        "xmax": {"type": "number"},
                                    },
                                    "required": ["ymin", "xmin", "ymax", "xmax"],
                                },
                            },
                            "required": ["start_s", "end_s"],
                        },
                    },
                    # Named, not ordered. An anonymous 4-array gave the model
                    # no structural cue and it answered [xmin, ymin, xmax,
                    # ymax] — the commoner convention — while the prompt asked
                    # for y-first. Word order in a prompt is not a contract.
                    "bbox": {
                        "type": "object",
                        "properties": {
                            "ymin": {"type": "number"},
                            "xmin": {"type": "number"},
                            "ymax": {"type": "number"},
                            "xmax": {"type": "number"},
                        },
                        "required": ["ymin", "xmin", "ymax", "xmax"],
                    },
                    "at_s": {"type": "number"},
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
        "source_work": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "rights_holder": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "basis": {"type": "string"},
            },
            "required": ["title", "confidence", "basis"],
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
    # Set when the footage IS an existing published work rather than original
    # material containing third-party items. See clearframe/sourcework.py.
    source_work: SourceWork | None = None
    # Not clearance items — things on screen that should probably not be
    # published at all. Optional so every prior fixture still parses.
    exposures: list[ExposureFinding] = []


def parse_bbox(raw) -> BBox | None:
    """Gemini's box -> our normalised BBox, or None if it is unusable.

    Accepts [ymin, xmin, ymax, xmax] in Gemini's documented 0-1000 scale, the
    same list already normalised 0-1, or a dict. Anything else — wrong arity,
    inverted, zero-area, prose — yields None.

    Returning None rather than raising is the point. A malformed rectangle must
    cost the box, never the detection: losing a real finding over a UI nicety
    would trade away the product's whole safety claim.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        try:
            values = [float(raw[k]) for k in ("ymin", "xmin", "ymax", "xmax")]
        except (KeyError, TypeError, ValueError):
            return None
    elif isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            values = [float(v) for v in raw]
        except (TypeError, ValueError):
            return None
    else:
        return None

    # Some model versions answer 0-1 rather than 0-1000. Dividing an
    # already-normalised box again collapses it into the top-left corner,
    # which renders as a dot and reads as a bug in the player.
    if any(abs(v) > 1.0 for v in values):
        values = [v / 1000.0 for v in values]
    ymin, xmin, ymax, xmax = (max(0.0, min(1.0, v)) for v in values)

    try:
        return BBox(ymin=ymin, xmin=xmin, ymax=ymax, xmax=xmax)
    except ValidationError:
        return None  # inverted or zero-area


def parse_scan_payload(payload: dict) -> ScanResult:
    detections: list[DetectedElement] = []
    skipped = 0
    for entry in payload.get("elements") or []:
        if isinstance(entry, dict):
            # Boxes are parsed separately at both levels so a malformed
            # rectangle can never cost us the element OR the appearance.
            ranges = []
            for r in entry.get("time_ranges") or []:
                if isinstance(r, dict):
                    r = {**r, "bbox": parse_bbox(r.get("bbox"))}
                ranges.append(r)
            entry = {
                **entry,
                "bbox": parse_bbox(entry.get("bbox")),
                "time_ranges": ranges,
            }
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
    work = None
    raw_work = payload.get("source_work")
    if isinstance(raw_work, dict) and (raw_work.get("title") or "").strip():
        try:
            work = SourceWork.model_validate(raw_work)
        except ValidationError:
            work = None

    return ScanResult(
        detections=detections,
        unscanned_ranges=unscanned,
        exposures=exposures,
        source_work=work,
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
    # `context` is keyword-with-default throughout: a caller that does not
    # supply it gets byte-identical behaviour to before it existed.
    async def scan(
        self, footage_uri: str, duration_s: float, context: str = ""
    ) -> ScanResult: ...

    async def audit_scan(
        self,
        footage_uri: str,
        duration_s: float,
        found_labels: list[str],
        context: str = "",
    ) -> ScanResult: ...

    async def scan_script(self, text: str) -> list[ScriptMention]: ...


class FixtureGeminiClient:
    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = Path(fixtures_dir)

    async def scan(
        self, footage_uri: str, duration_s: float, context: str = ""
    ) -> ScanResult:
        payload = json.loads((self.fixtures_dir / "demo_scene.json").read_text())
        return parse_scan_payload(payload)

    async def audit_scan(
        self,
        footage_uri: str,
        duration_s: float,
        found_labels: list[str],
        context: str = "",
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
