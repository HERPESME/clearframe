import json
from types import SimpleNamespace

import pytest

pytest.importorskip("google.genai", reason="live client tests need the cloud extra")

from clearframe.integrations.gemini_live import LiveGeminiClient, ScanFailedError

VALID_PAYLOAD = {
    "elements": [
        {
            "id": "e1",
            "label": "Acme soda can",
            "element_type": "LOGO",
            "description": "soda can on table",
            "time_ranges": [{"start_s": 1.0, "end_s": 3.0}],
            "prominence": {
                "screen_time_s": 2.0,
                "frame_coverage": 0.1,
                "centrality": 0.5,
                "plot_integral": False,
            },
        },
        {
            "id": "e2",
            "label": "Mural",
            "element_type": "ARTWORK",
            "description": "wall mural",
            "time_ranges": [{"start_s": 5.0, "end_s": 9.0}],
            "prominence": {
                "screen_time_s": 4.0,
                "frame_coverage": 0.3,
                "centrality": 0.5,
                "plot_integral": False,
            },
        },
    ],
    "unscanned_ranges": [],
}


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def make_client(responses):
    fake = SimpleNamespace(models=FakeModels(responses))
    client = LiveGeminiClient(
        project="p", location="us-central1", client_factory=lambda: fake
    )
    return client, fake


async def test_happy_path_parses_elements():
    client, fake = make_client([SimpleNamespace(text=json.dumps(VALID_PAYLOAD))])
    result = await client.scan("gs://bucket/scene.mp4", 62.0)
    assert [d.id for d in result.detections] == ["e1", "e2"]
    assert len(fake.models.calls) == 1


async def test_invalid_json_retries_with_error_feedback():
    client, fake = make_client(
        [
            SimpleNamespace(text="not json {"),
            SimpleNamespace(text=json.dumps(VALID_PAYLOAD)),
        ]
    )
    result = await client.scan("gs://bucket/scene.mp4", 62.0)
    assert len(result.detections) == 2
    assert len(fake.models.calls) == 2
    retry_contents = str(fake.models.calls[1]["contents"])
    assert "previous response" in retry_contents.lower()


async def test_two_failures_raise_scan_failed():
    client, _ = make_client(
        [SimpleNamespace(text="not json {"), SimpleNamespace(text="still bad")]
    )
    with pytest.raises(ScanFailedError):
        await client.scan("gs://bucket/scene.mp4", 62.0)


async def test_local_path_missing_file_raises(tmp_path):
    client, _ = make_client([SimpleNamespace(text=json.dumps(VALID_PAYLOAD))])
    with pytest.raises(FileNotFoundError):
        await client.scan(str(tmp_path / "missing.mp4"), 10.0)


async def test_scan_config_includes_safety_settings():
    client, fake = make_client([SimpleNamespace(text=json.dumps(VALID_PAYLOAD))])
    await client.scan("gs://bucket/scene.mp4", 62.0)
    config = fake.models.calls[0]["config"]
    assert len(config.safety_settings) == 4
    assert all(str(s.threshold).endswith("BLOCK_ONLY_HIGH") for s in config.safety_settings)


async def test_script_scan_requests_the_script_schema_not_the_video_one():
    """Regression: scan_script routed through _generate, which unconditionally
    pinned SCAN_RESPONSE_SCHEMA. Gemini was therefore forced to answer in the
    video shape ({"elements": [...]}) while parse_script_payload looked for
    {"mentions": [...]}, so live script pre-scan silently returned nothing and
    drift never computed. Verified against the live API 2026-08-22."""
    from clearframe.integrations.gemini_client import SCRIPT_RESPONSE_SCHEMA

    seen = {}

    class _Models:
        def generate_content(self, model, contents, config):
            seen["schema"] = getattr(config, "response_schema", None)
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "mentions": [
                            {
                                "label": "Coca-Cola can",
                                "element_type": "LOGO",
                                "scene": "INT. KITCHEN",
                            }
                        ]
                    }
                )
            )

    client = LiveGeminiClient(
        project="p",
        location="us-central1",
        client_factory=lambda: SimpleNamespace(models=_Models()),
    )
    mentions = await client.scan_script("INT. KITCHEN - DAY\nA COCA-COLA can.")

    assert seen["schema"] == SCRIPT_RESPONSE_SCHEMA
    assert [m.label for m in mentions] == ["Coca-Cola can"]


async def test_video_scan_still_uses_the_video_schema():
    seen = {}

    class _Models:
        def generate_content(self, model, contents, config):
            seen["schema"] = getattr(config, "response_schema", None)
            return SimpleNamespace(text=json.dumps(VALID_PAYLOAD))

    from clearframe.integrations.gemini_client import SCAN_RESPONSE_SCHEMA

    client = LiveGeminiClient(
        project="p",
        location="us-central1",
        client_factory=lambda: SimpleNamespace(models=_Models()),
    )
    result = await client.scan("gs://b/clip.mp4", 10.0)
    assert seen["schema"] == SCAN_RESPONSE_SCHEMA
    assert len(result.detections) == 2
