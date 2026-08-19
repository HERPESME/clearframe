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

    async def flaky(element, production_title, processor=None):
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

    async def always_fail(element, production_title, processor=None):
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


# FindAll result shape per docs.parallel.ai (v1beta/findall/runs/{id}/result):
# candidates carry name/url/description/match_status plus per-condition output;
# our runs request a "kind" condition so the entity kind comes back enriched.
FINDALL_RESULT = {
    "candidates": [
        {
            "candidate_id": "c-1",
            "name": "Precita Eyes Muralists Association",
            "url": "https://www.precitaeyes.org/",
            "description": "Registers and documents community murals.",
            "match_status": "matched",
            "output": {"kind": {"value": "mural arts registry", "is_matched": True}},
        },
        {
            "candidate_id": "c-2",
            "name": "Building owner of record",
            "url": "https://sfassessor.org/",
            "description": "Assessor records identify who to ask.",
            "match_status": "matched",
            "output": {},
        },
    ]
}


def test_parse_findall_result_maps_real_api_shape():
    from clearframe.integrations.parallel_client import parse_findall_result

    candidates = parse_findall_result(FINDALL_RESULT)
    assert len(candidates) == 2
    assert candidates[0].name == "Precita Eyes Muralists Association"
    assert candidates[0].kind == "mural arts registry"
    assert candidates[0].url == "https://www.precitaeyes.org/"
    assert candidates[0].note == "Registers and documents community murals."
    # no kind condition in output -> falls back to match_status
    assert candidates[1].kind == "matched"


def test_parse_findall_prefers_matched_and_caps(monkeypatch):
    # Live-observed 2026-08-19: the API returns dozens of *generated* (unvetted)
    # candidates beyond the matched ones — matched must rank first and the total
    # must be capped so the review UI isn't flooded.
    from clearframe.integrations.parallel_client import parse_findall_result

    payload = {
        "candidates": [
            {"name": f"gen-{i}", "match_status": "generated", "url": "", "description": ""}
            for i in range(20)
        ]
        + [
            {"name": "matched-one", "match_status": "matched", "url": "", "description": ""}
        ]
    }
    candidates = parse_findall_result(payload, limit=10)
    assert len(candidates) == 10
    assert candidates[0].name == "matched-one"
    # "generated" is an API status, not an entity kind — normalize for the UI
    assert candidates[1].kind == "candidate"


async def test_fixture_findall_uses_shared_parser():
    from clearframe.models import ClearanceCategory

    fixtures = Path("src/clearframe/integrations/fixtures")
    el = make_element("Street mural, unknown artist", id="e5")
    el = el.model_copy(update={"category": ClearanceCategory.COPYRIGHT_ART})
    candidates = await FixtureParallelClient(fixtures).find_all(el, "Golden Hour")
    assert len(candidates) == 3
    assert {c.kind for c in candidates} >= {"mural arts registry", "property owner"}


async def test_live_monitor_falls_back_to_local_watch_when_product_unavailable(monkeypatch):
    import httpx

    from clearframe.integrations.parallel_client import LiveParallelClient

    client = LiveParallelClient(api_key="k")

    async def unavailable(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(
            401,
            json={"code": 7, "message": "Product(s) unavailable to provided credential"},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", unavailable)
    watch = await client.create_monitor("e3", "Nike lawsuits", "weekly", "https://x/webhook")
    assert watch is not None
    assert watch.monitor_id == "local-e3"
    assert watch.element_id == "e3"
