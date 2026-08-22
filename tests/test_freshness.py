import httpx
import pytest

from clearframe.freshness import is_material, material_count, to_signals
from clearframe.integrations.parallel_client import (
    SEARCH_BETA_HEADER,
    LiveParallelClient,
    parse_search_results,
)
from clearframe.models import WebFinding
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context

REAL_SHAPE = {
    "search_id": "srch_x",
    "results": [
        {
            "url": "https://billboard.example/sync-suits",
            "title": "Majors escalate sync enforcement",
            "excerpts": ["Universal Music Group has filed suit against several production companies."],
        },
        {
            "url": "https://news.example/campaign",
            "title": "Nike unveils autumn brand campaign",
            "excerpts": ["A new global marketing push centred on running."],
        },
    ],
    "usage": {"requests": 1},
}


def test_parses_real_search_shape():
    findings = parse_search_results(REAL_SHAPE)
    assert len(findings) == 2
    assert findings[0].url == "https://billboard.example/sync-suits"
    assert "filed suit" in findings[0].excerpt


def test_limit_caps_results():
    assert len(parse_search_results(REAL_SHAPE, limit=1)) == 1


def test_materiality_separates_enforcement_from_marketing():
    enforcement, marketing = to_signals(
        "e1", "UMG", parse_search_results(REAL_SHAPE)
    )
    assert enforcement.material is True
    assert marketing.material is False
    assert material_count([enforcement, marketing]) == 1


def test_materiality_is_case_insensitive():
    assert is_material(WebFinding(title="CEASE AND DESIST issued", url="u", excerpt=""))
    assert not is_material(WebFinding(title="Quarterly earnings", url="u", excerpt=""))


async def test_live_search_sends_beta_header_and_parses(monkeypatch):
    seen = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return REAL_SHAPE

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen["url"] = url
            seen["headers"] = headers
            seen["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    findings = await LiveParallelClient(api_key="k").search(
        "objective", ["nike lawsuit"], max_results=2
    )
    assert seen["url"].endswith("/v1beta/search")
    assert seen["headers"]["parallel-beta"] == SEARCH_BETA_HEADER
    assert seen["headers"]["x-api-key"] == "k"
    assert seen["json"]["objective"] == "objective"
    assert len(findings) == 2


async def test_live_search_degrades_to_empty_on_failure(monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert await LiveParallelClient(api_key="k").search("o", ["q"]) == []


async def test_pipeline_attaches_freshness_only_to_identified_owners(tmp_path):
    state = await Pipeline(build_demo_pipeline()).run(demo_context(tmp_path))
    assert "e3" in state.freshness  # Nike — owner identified, fixture present
    assert material_count(state.freshness["e3"]) == 2
    # the unidentified mural has no owner to check freshness against
    assert "e5" not in state.freshness
