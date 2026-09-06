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


# ------------------------------------------------- transient transport retry
class _FlakyModels:
    """Fails with a transport error `fail_times` times, then succeeds."""

    def __init__(self, exc, fail_times: int, payload: str):
        self.exc = exc
        self.remaining = fail_times
        self.payload = payload
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.exc
        return type("R", (), {"text": self.payload})()


class _FlakyClient:
    def __init__(self, models):
        self.models = models


def _scan_payload() -> str:
    import json

    return json.dumps(
        {
            "elements": [
                {
                    "id": "e1",
                    "label": "Bayer Aspirin",
                    "element_type": "LOGO",
                    "description": "tin on the counter",
                    "time_ranges": [{"start_s": 1.0, "end_s": 6.0}],
                    "prominence": {
                        "screen_time_s": 5.0,
                        "frame_coverage": 0.2,
                        "centrality": 0.6,
                        "plot_integral": False,
                    },
                }
            ],
            "unscanned_ranges": [],
        }
    )


@pytest.mark.asyncio
async def test_a_reset_mid_upload_does_not_lose_the_run(monkeypatch):
    """A live run died at `httpx.ReadError: [Errno 54] Connection reset by
    peer` during the video upload and took the whole pipeline with it —
    including the Video Intelligence and fingerprint work running alongside.
    Footage goes up inline, so the scan is the largest request we make and the
    likeliest to meet a reset."""
    import httpx

    models = _FlakyModels(
        httpx.ReadError("[Errno 54] Connection reset by peer"), 2, _scan_payload()
    )
    client = LiveGeminiClient(
        project="p",
        location="l",
        client_factory=lambda: _FlakyClient(models),
        transport_backoff_s=0.0,
    )
    monkeypatch.setattr(
        "clearframe.integrations.gemini_live._video_part", lambda uri: "VIDEO"
    )

    result = await client.scan("clip.mp4", 30.0)
    assert [d.label for d in result.detections] == ["Bayer Aspirin"]
    assert models.calls == 3


@pytest.mark.asyncio
async def test_a_deterministic_failure_is_not_retried(monkeypatch):
    """Retrying a 400 or a safety block spends money to fail identically."""
    models = _FlakyModels(ValueError("400 Invalid argument"), 99, "")
    client = LiveGeminiClient(
        project="p",
        location="l",
        client_factory=lambda: _FlakyClient(models),
        transport_backoff_s=0.0,
    )
    monkeypatch.setattr(
        "clearframe.integrations.gemini_live._video_part", lambda uri: "VIDEO"
    )

    with pytest.raises(Exception):
        await client.scan("clip.mp4", 30.0)
    assert models.calls == 1


def test_grounding_does_not_block_the_event_loop():
    """Every other model call offloads to a thread. This one did not.

    `_generate` is a synchronous SDK call taking about eight seconds for a
    still. `scan_script`, `_scan_with_prompt` and the rest wrap it in
    `asyncio.to_thread`; `ground_frame` called it inline inside an `async def`,
    so awaiting it yielded nothing and the server served NOTHING ELSE for the
    whole call — no API, no media, no second grounding request.

    That is most of "I pause and no box ever appears": the request was made,
    and the process that had to answer it was blocked on the one before.
    Warming sixteen frames in the background turned it from a stall into a
    minute-long freeze.
    """
    import asyncio
    import time

    client = LiveGeminiClient(project="p", location="us-central1")
    payload = {"found": [{"label": "Acme soda can",
                          "bbox": {"ymin": 0.1, "xmin": 0.1,
                                   "ymax": 0.3, "xmax": 0.3}}]}

    def blocking_generate(contents, schema=None):
        time.sleep(0.3)
        return json.dumps(payload)

    client._generate = blocking_generate

    async def scenario():
        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                await asyncio.sleep(0.01)
                ticks += 1

        counting = asyncio.create_task(ticker())
        await asyncio.sleep(0.02)  # let it get going
        before = ticks
        boxes = await client.ground_frame(b"jpegbytes", ["Acme soda can"])
        during = ticks - before
        stop = True
        await counting
        return during, boxes

    # Ticks counted DURING the call, not after it. Waiting for the ticker to
    # finish would pass either way, which is how the first version of this
    # test passed against the blocking implementation.
    during, boxes = asyncio.run(scenario())
    assert during >= 5, (
        f"only {during} tick(s) ran during a 0.3s call — the event loop was "
        "blocked, so the server can answer nothing else while grounding"
    )
    assert "Acme soda can" in boxes


def test_a_model_that_404s_is_only_discovered_once():
    """`gemini-3-pro-preview` 404s in this project, deterministically.

    The fallback to 2.5-pro is what actually serves every live run — so
    re-deriving it costs a wasted round trip on every call. Invisible while
    the client lived for one run; 150 wasted calls once pre-grounding started
    measuring a clip's worth of frames.
    """
    from clearframe.integrations.gemini_live import LiveGeminiClient

    tried: list[str] = []

    class Models:
        def generate_content(self, model, contents, config):
            tried.append(model)
            if model == "missing-model":
                raise RuntimeError("404 NOT_FOUND: model not found")

            class R:
                text = "{}"

            return R()

    class Client:
        models = Models()

    client = LiveGeminiClient(
        "proj", "us-central1", model="missing-model",
        fallback_model="serving-model", client_factory=lambda: Client(),
    )

    client._generate(["one"])
    client._generate(["two"])

    assert tried == ["missing-model", "serving-model", "serving-model"]
