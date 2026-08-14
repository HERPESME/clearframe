from pathlib import Path

from clearframe.integrations.gemini_client import FixtureGeminiClient, parse_scan_payload

FIXTURES = Path("src/clearframe/integrations/fixtures")


async def test_fixture_scan_returns_six_elements():
    result = await FixtureGeminiClient(FIXTURES).scan("demo://salted-scene", 62.0)
    assert len(result.detections) == 6
    labels = [d.label for d in result.detections]
    assert "Blinding Lights - The Weeknd" in labels


def test_parser_skips_invalid_entries():
    payload = {"elements": [{"label": "broken"}], "unscanned_ranges": []}
    assert parse_scan_payload(payload).detections == []
