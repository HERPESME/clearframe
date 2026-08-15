from pathlib import Path

from clearframe.integrations.parallel_client import (
    FixtureParallelClient,
    parse_task_output,
    slug,
)
from clearframe.models import (
    ClearanceCategory,
    ElementType,
    LicensingPosture,
    Prominence,
    TimeRange,
    TriagedElement,
)

SAMPLE = {
    "content": {
        "owner": "The Weeknd XO, Inc. / Universal Music Group",
        "owner_confidence": "high",
        "licensing_contact": "sync@umusic.com",
        "licensing_posture": "litigious",
        "litigation_history": ["Multiple sync infringement claims 2019-2024"],
        "estimated_license_cost_band": "$50k-$250k",
    },
    "basis": [
        {
            "field": "owner",
            "citations": [
                {
                    "url": "https://www.umusicpub.com/",
                    "excerpts": ["Universal Music Publishing Group administers…"],
                }
            ],
            "reasoning": "Publisher listing confirms administration.",
            "confidence": "high",
        }
    ],
}


def make_element(label, id="e9"):
    return TriagedElement(
        id=id,
        label=label,
        element_type=ElementType.ARTWORK,
        description="",
        category=ClearanceCategory.COPYRIGHT_ART,
        time_ranges=[TimeRange(start_s=0, end_s=1)],
        prominence=Prominence(
            screen_time_s=1, frame_coverage=0.1, centrality=0.1, plot_integral=False
        ),
    )


def test_parse_complete_output():
    r = parse_task_output("e1", SAMPLE)
    assert r.status == "complete" and r.licensing_posture == LicensingPosture.LITIGIOUS
    assert r.basis[0].url.startswith("https://www.umusicpub.com")


def test_parse_missing_owner_marks_incomplete():
    r = parse_task_output("e1", {"content": {"owner": None}, "basis": []})
    assert r.status == "incomplete" and r.licensing_posture == LicensingPosture.UNKNOWN


def test_slug():
    assert slug("Blinding Lights - The Weeknd") == "blinding-lights-the-weeknd"


async def test_fixture_client_missing_file_is_incomplete(tmp_path):
    (tmp_path / "research").mkdir()
    r = await FixtureParallelClient(tmp_path).research(make_element("Unknown Mural"), "Demo")
    assert r.status == "incomplete"


async def test_live_client_retries_transient_errors(monkeypatch):
    import httpx

    from clearframe.integrations.parallel_client import LiveParallelClient

    client = LiveParallelClient(api_key="k", backoff_s=0.0)
    calls = {"n": 0}

    async def flaky(element, production_title):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("transient")
        return "ok"

    monkeypatch.setattr(client, "_research_once", flaky)
    result = await client.research(make_element("X"), "Demo")
    assert result == "ok" and calls["n"] == 2


async def test_live_client_gives_incomplete_after_all_attempts(monkeypatch):
    import httpx

    from clearframe.integrations.parallel_client import LiveParallelClient

    client = LiveParallelClient(api_key="k", backoff_s=0.0)

    async def always_fail(element, production_title):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(client, "_research_once", always_fail)
    result = await client.research(make_element("X", id="e7"), "Demo")
    assert result.status == "incomplete" and result.element_id == "e7"


async def test_real_fixture_dir_loads_weeknd():
    fixtures = Path("src/clearframe/integrations/fixtures")
    el = make_element("Blinding Lights - The Weeknd", id="e1")
    r = await FixtureParallelClient(fixtures).research(el, "Golden Hour")
    assert r.status == "complete"
    assert r.licensing_posture == LicensingPosture.LITIGIOUS
    assert r.basis, "basis citations must be present"
