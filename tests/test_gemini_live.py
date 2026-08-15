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
