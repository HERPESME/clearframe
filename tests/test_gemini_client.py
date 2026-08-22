from pathlib import Path

from clearframe.integrations.gemini_client import FixtureGeminiClient, parse_scan_payload

FIXTURES = Path("src/clearframe/integrations/fixtures")


async def test_fixture_scan_returns_seven_elements():
    result = await FixtureGeminiClient(FIXTURES).scan("demo://salted-scene", 62.0)
    assert len(result.detections) == 7
    labels = [d.label for d in result.detections]
    assert "Blinding Lights - The Weeknd" in labels


async def test_fixture_audit_scan_finds_missed_element():
    client = FixtureGeminiClient(FIXTURES)
    first = await client.scan("demo://salted-scene", 62.0)
    audit = await client.audit_scan(
        "demo://salted-scene", 62.0, [d.label for d in first.detections]
    )
    assert len(audit.detections) == 1
    assert audit.detections[0].id == "e7"
    assert "broadcast" in audit.detections[0].label.lower()


def test_parser_skips_invalid_entries():
    payload = {"elements": [{"label": "broken"}], "unscanned_ranges": []}
    assert parse_scan_payload(payload).detections == []
