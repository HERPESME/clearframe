"""Second-opinion detector: closed-vocabulary logo/text recognition.

Google Cloud Video Intelligence `LOGO_RECOGNITION` tracks 100k+ catalogued
brands across a video and returns per-track confidence, time segments, and
normalized boxes. Unlike a generative model it cannot invent a brand outside
its catalogue, which is exactly the property identity corroboration needs.

Same shape as every other integration here: one protocol, a live client and a
fixture client sharing a single parser, so demo mode exercises the identical
code path.
"""

import json
from pathlib import Path
from typing import Protocol

from clearframe.models import BBox, DetectorHit

# Video Intelligence returns durations as {"seconds": int, "nanos": int}.
def _offset_s(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
    # protobuf Duration objects expose .seconds / .nanos
    seconds = getattr(value, "seconds", None)
    if seconds is None:
        return None
    return float(seconds) + float(getattr(value, "nanos", 0)) / 1e9


def _box(raw) -> BBox | None:
    """Video Intelligence normalized_bounding_box -> our BBox (already 0-1)."""
    if not raw:
        return None
    get = raw.get if isinstance(raw, dict) else lambda k, d=0.0: getattr(raw, k, d)
    try:
        return BBox(
            ymin=max(0.0, min(1.0, float(get("top", 0.0)))),
            xmin=max(0.0, min(1.0, float(get("left", 0.0)))),
            ymax=max(0.0, min(1.0, float(get("bottom", 0.0)))),
            xmax=max(0.0, min(1.0, float(get("right", 0.0)))),
        )
    except (TypeError, ValueError):
        return None


def parse_logo_annotations(payload: dict) -> list[DetectorHit]:
    """Map a Video Intelligence annotate response to detector hits.

    Shape: annotation_results[].logo_recognition_annotations[]
             .entity.description, .tracks[].segment, .tracks[].confidence
    """
    hits: list[DetectorHit] = []
    for result in payload.get("annotation_results") or []:
        for ann in result.get("logo_recognition_annotations") or []:
            label = ((ann.get("entity") or {}).get("description") or "").strip()
            if not label:
                continue
            for track in ann.get("tracks") or []:
                segment = track.get("segment") or {}
                objects = track.get("timestamped_objects") or []
                bbox = _box((objects[0] or {}).get("normalized_bounding_box")) if objects else None
                hits.append(
                    DetectorHit(
                        label=label,
                        confidence=max(0.0, min(1.0, float(track.get("confidence", 0.0)))),
                        start_s=_offset_s(segment.get("start_time_offset")),
                        end_s=_offset_s(segment.get("end_time_offset")),
                        bbox=bbox,
                    )
                )
    return hits


class CorroborationClient(Protocol):
    name: str

    async def detect(self, footage_uri: str, duration_s: float) -> list[DetectorHit]: ...


class FixtureVisionClient:
    name = "cloud-video-intelligence"

    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = Path(fixtures_dir)

    async def detect(self, footage_uri: str, duration_s: float) -> list[DetectorHit]:
        path = self.fixtures_dir / "corroboration" / "demo_scene_logos.json"
        if not path.exists():
            return []
        return parse_logo_annotations(json.loads(path.read_text()))


class LiveVideoIntelligenceClient:
    """Cloud Video Intelligence LOGO_RECOGNITION.

    Best-effort by design: if the API is not enabled, not permitted, or the
    call fails, corroboration degrades to SINGLE_SOURCE rather than blocking
    the pipeline — an unavailable second opinion is not a contradiction.
    """

    name = "cloud-video-intelligence"

    def __init__(self, client_factory=None):
        self._client_factory = client_factory
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                from google.cloud import videointelligence

                self._client = videointelligence.VideoIntelligenceServiceClient()
        return self._client

    async def detect(self, footage_uri: str, duration_s: float) -> list[DetectorHit]:
        import asyncio

        def _run() -> list[DetectorHit]:
            from google.cloud import videointelligence

            client = self._client_or_create()
            features = [videointelligence.Feature.LOGO_RECOGNITION]
            request: dict = {"features": features}
            if footage_uri.startswith("gs://"):
                request["input_uri"] = footage_uri
            else:
                request["input_content"] = Path(footage_uri).read_bytes()
            operation = client.annotate_video(request=request)
            response = operation.result(timeout=600)
            # proto-plus -> plain dict so the fixture and live paths share a parser
            from google.protobuf.json_format import MessageToDict

            payload = MessageToDict(
                response._pb if hasattr(response, "_pb") else response,
                preserving_proto_field_name=True,
            )
            return parse_logo_annotations(payload)

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            import logging

            logging.getLogger("clearframe.corroboration").warning(
                "logo corroboration unavailable (%s); identities stay single-source", exc
            )
            return []
