"""Live Gemini video-scan client (Vertex AI via google-genai).

Sends footage to Gemini with a structured-output schema and parses the
response through the same parser as the fixture client. Error policy per
spec §6: one re-prompt with validator feedback, then fail loud.
"""

import asyncio
import json
import logging
from pathlib import Path

from clearframe.integrations.gemini_client import (
    SCAN_PROMPT,
    SCAN_RESPONSE_SCHEMA,
    SCRIPT_RESPONSE_SCHEMA,
    ScanResult,
    parse_scan_payload,
)


class ScanFailedError(Exception):
    """Gemini could not produce a valid scan after a retry."""


_TRANSIENT_MARKERS = (
    "connection reset",
    "connection aborted",
    "readerror",
    "read timeout",
    "connecttimeout",
    "connecterror",
    "remoteprotocolerror",
    "server disconnected",
    "broken pipe",
    "temporarily unavailable",
    "503",
    "504",
    "429",
)


def _is_transient(exc: Exception) -> bool:
    """Is this worth trying again, or would a retry fail identically?

    Deliberately conservative: a 4xx, a safety block or an unknown model is
    deterministic, and retrying it spends money to reach the same answer.
    """
    text = f"{type(exc).__name__} {exc}".casefold()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _default_client_factory(project: str, location: str):
    from google import genai

    return genai.Client(vertexai=True, project=project, location=location)


def _video_part(footage_uri: str):
    from google.genai import types

    if footage_uri.startswith("gs://"):
        return types.Part.from_uri(file_uri=footage_uri, mime_type="video/mp4")
    path = Path(footage_uri)
    if not path.exists():
        raise FileNotFoundError(f"Footage file not found: {footage_uri}")
    return types.Part.from_bytes(data=path.read_bytes(), mime_type="video/mp4")


class LiveGeminiClient:
    def __init__(
        self,
        project: str,
        location: str,
        model: str = "gemini-3-pro-preview",
        fallback_model: str = "gemini-2.5-pro",
        client_factory=None,
        transport_attempts: int = 3,
        transport_backoff_s: float = 2.0,
    ):
        self.project = project
        self.location = location
        self.model = model
        self.fallback_model = fallback_model
        self.transport_attempts = transport_attempts
        self.transport_backoff_s = transport_backoff_s
        self._client_factory = client_factory or (
            lambda: _default_client_factory(project, location)
        )
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    @staticmethod
    def _scan_config(schema: dict | None = None):
        """Structured-output config with explicit safety settings.

        Footage analysis must not refuse on mild depicted content (a fight
        scene is normal dailies) but blocks extreme outputs — BLOCK_ONLY_HIGH
        across the four harm categories.
        """
        try:
            from google.genai import types as genai_types
        except ImportError:
            # Test fakes don't need a real config object.
            return {"response_mime_type": "application/json"}
        categories = (
            "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_DANGEROUS_CONTENT",
            "HARM_CATEGORY_HARASSMENT",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        )
        return genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema or SCAN_RESPONSE_SCHEMA,
            safety_settings=[
                genai_types.SafetySetting(category=c, threshold="BLOCK_ONLY_HIGH")
                for c in categories
            ],
        )

    def _generate(self, contents, schema: dict | None = None) -> str:
        from_config = self._scan_config(schema)

        client = self._client_or_create()
        models_to_try = [self.model, self.fallback_model]
        last_error: Exception | None = None
        for model in models_to_try:
            try:
                return self._call_with_retry(client, model, contents, from_config)
            except Exception as exc:  # model-not-found falls through to fallback
                if "not found" in str(exc).lower() or "404" in str(exc):
                    last_error = exc
                    continue
                raise
        raise ScanFailedError(f"No usable Gemini model: {last_error}")

    def _call_with_retry(self, client, model, contents, config) -> str:
        """Retry transient transport failures on the one call the run depends on.

        Footage goes up inline, so the scan is by far the largest request the
        pipeline makes and the likeliest to meet a reset mid-upload. A live run
        died at `httpx.ReadError: [Errno 54] Connection reset by peer` and took
        the whole pipeline with it — including the Video Intelligence and
        fingerprint work already completed alongside it.

        Only transport errors are retried. A 4xx, a safety block or a bad model
        is deterministic: retrying it burns money to fail identically.
        """
        import time

        for attempt in range(self.transport_attempts):
            try:
                resp = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                return resp.text or ""
            except Exception as exc:
                if attempt == self.transport_attempts - 1 or not _is_transient(exc):
                    raise
                delay = self.transport_backoff_s * (2**attempt)
                logging.getLogger("clearframe.scan").warning(
                    "transient Gemini transport failure (%s); retrying in %.1fs",
                    exc,
                    delay,
                )
                time.sleep(delay)
        raise ScanFailedError("unreachable")

    async def audit_scan(
        self, footage_uri: str, duration_s: float, found_labels: list[str]
    ) -> ScanResult:
        from clearframe.integrations.gemini_client import AUDIT_PROMPT_TEMPLATE

        prompt = AUDIT_PROMPT_TEMPLATE.format(found=", ".join(found_labels) or "nothing")
        return await self._scan_with_prompt(footage_uri, prompt)

    async def scan(self, footage_uri: str, duration_s: float) -> ScanResult:
        return await self._scan_with_prompt(footage_uri, SCAN_PROMPT)

    async def scan_script(self, text: str):
        from clearframe.integrations.gemini_client import (
            SCRIPT_PROMPT,
            parse_script_payload,
        )

        def _run():
            raw = self._generate(
                [SCRIPT_PROMPT + "\n\nSCREENPLAY:\n" + text],
                schema=SCRIPT_RESPONSE_SCHEMA,
            )
            return parse_script_payload(json.loads(raw))

        return await asyncio.to_thread(_run)

    async def _scan_with_prompt(self, footage_uri: str, prompt: str) -> ScanResult:
        video = _video_part(footage_uri)
        base_contents = [video, prompt]

        def attempt(contents) -> tuple[ScanResult | None, str]:
            text = self._generate(contents)
            try:
                return parse_scan_payload(json.loads(text)), ""
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                return None, f"{type(exc).__name__}: {exc}"

        result, error = await asyncio.to_thread(attempt, base_contents)
        if result is not None:
            return result

        retry_contents = [
            video,
            prompt
            + "\n\nYour previous response could not be parsed as valid JSON matching "
            f"the schema. Parser error: {error}. Respond again with ONLY the JSON object.",
        ]
        result, error = await asyncio.to_thread(attempt, retry_contents)
        if result is not None:
            return result
        raise ScanFailedError(f"Gemini scan failed after retry: {error}")
