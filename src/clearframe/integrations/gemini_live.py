"""Live Gemini video-scan client (Vertex AI via google-genai).

Sends footage to Gemini with a structured-output schema and parses the
response through the same parser as the fixture client. Error policy per
spec §6: one re-prompt with validator feedback, then fail loud.
"""

import asyncio
import json
from pathlib import Path

from clearframe.integrations.gemini_client import (
    SCAN_PROMPT,
    SCAN_RESPONSE_SCHEMA,
    ScanResult,
    parse_scan_payload,
)


class ScanFailedError(Exception):
    """Gemini could not produce a valid scan after a retry."""


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
    ):
        self.project = project
        self.location = location
        self.model = model
        self.fallback_model = fallback_model
        self._client_factory = client_factory or (
            lambda: _default_client_factory(project, location)
        )
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    @staticmethod
    def _scan_config():
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
            response_schema=SCAN_RESPONSE_SCHEMA,
            safety_settings=[
                genai_types.SafetySetting(category=c, threshold="BLOCK_ONLY_HIGH")
                for c in categories
            ],
        )

    def _generate(self, contents) -> str:
        from_config = self._scan_config()

        client = self._client_or_create()
        models_to_try = [self.model, self.fallback_model]
        last_error: Exception | None = None
        for model in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=model, contents=contents, config=from_config
                )
                return resp.text or ""
            except Exception as exc:  # model-not-found falls through to fallback
                if "not found" in str(exc).lower() or "404" in str(exc):
                    last_error = exc
                    continue
                raise
        raise ScanFailedError(f"No usable Gemini model: {last_error}")

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
            raw = self._generate([SCRIPT_PROMPT + "\n\nSCREENPLAY:\n" + text])
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
