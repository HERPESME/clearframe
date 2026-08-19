"""Parallel Task API client: deep rights research with citations (Basis).

Live client targets https://docs.parallel.ai Task API; fixture client replays
recorded task outputs through the same parser so demo mode exercises the
identical code path.
"""

import asyncio
import json
from pathlib import Path
from typing import Protocol

import httpx

from clearframe.models import (
    BasisCitation,
    CandidateEntity,
    ClearanceWatch,
    LicensingPosture,
    ResearchResult,
    TriagedElement,
)

RESEARCH_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "owner": {
            "type": ["string", "null"],
            "description": "Legal owner / rights holder of the element, or null if not determinable",
        },
        "owner_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "licensing_contact": {
            "type": ["string", "null"],
            "description": "Best licensing/clearance contact (email or URL)",
        },
        "licensing_posture": {
            "type": "string",
            "enum": ["permissive", "standard", "litigious", "unknown"],
        },
        "litigation_history": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Known IP enforcement actions or lawsuits by this rights holder",
        },
        "estimated_license_cost_band": {
            "type": ["string", "null"],
            "description": "Typical licensing cost band for independent film use",
        },
    },
    "required": ["owner", "owner_confidence", "licensing_posture", "litigation_history"],
    "additionalProperties": False,
}


def slug(label: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in label.casefold())
    return "-".join(cleaned.split())


def build_research_input(element: TriagedElement, production_title: str) -> str:
    return (
        f"You are researching rights clearance for the film production '{production_title}'. "
        f"An element appearing on screen must be cleared: '{element.label}' "
        f"({element.category.value}). Description: {element.description or 'n/a'}. "
        "Determine: (1) who legally owns the rights to this element, (2) the best "
        "licensing/clearance contact, (3) the rights holder's licensing posture "
        "(permissive / standard / litigious) based on their enforcement history, "
        "(4) known IP litigation or enforcement actions by this rights holder, and "
        "(5) the typical license cost band for independent film use."
    )


def parse_task_output(element_id: str, output: dict) -> ResearchResult:
    content = output.get("content") or {}
    basis: list[BasisCitation] = []
    for b in output.get("basis") or []:
        citations = b.get("citations") or [{}]
        for c in citations:
            excerpts = c.get("excerpts") or []
            basis.append(
                BasisCitation(
                    field=b.get("field", ""),
                    url=c.get("url", ""),
                    excerpt=excerpts[0] if excerpts else "",
                    reasoning=b.get("reasoning", ""),
                    confidence=b.get("confidence", ""),
                )
            )

    owner = content.get("owner")
    try:
        posture = LicensingPosture(content.get("licensing_posture", "unknown"))
    except ValueError:
        posture = LicensingPosture.UNKNOWN
    status = "complete" if owner else "incomplete"
    if status == "incomplete":
        posture = LicensingPosture.UNKNOWN

    return ResearchResult(
        element_id=element_id,
        owner=owner,
        owner_confidence=content.get("owner_confidence", "low"),
        licensing_contact=content.get("licensing_contact"),
        licensing_posture=posture,
        litigation_history=list(content.get("litigation_history") or []),
        estimated_license_cost_band=content.get("estimated_license_cost_band"),
        basis=basis,
        status=status,
    )


def parse_findall_result(payload: dict, limit: int | None = None) -> list[CandidateEntity]:
    """Map a FindAll run result (v1beta/findall/runs/{id}/result) to candidates.

    Each candidate's entity kind comes from the "kind" match condition we attach
    to every run; candidates without that enrichment fall back to match_status.
    Live runs return dozens of *generated* (unvetted) candidates beyond the
    matched ones — matched rank first and `limit` caps the total so leads stay
    reviewable.
    """
    raw = payload.get("candidates") or []
    ordered = [c for c in raw if c.get("match_status") == "matched"] + [
        c for c in raw if c.get("match_status") != "matched"
    ]
    if limit is not None:
        ordered = ordered[:limit]
    candidates: list[CandidateEntity] = []
    for c in ordered:
        output = c.get("output") or {}
        kind = (output.get("kind") or {}).get("value") or c.get("match_status") or "candidate"
        if kind in {"generated", "unmatched"}:
            kind = "candidate"
        candidates.append(
            CandidateEntity(
                name=c.get("name", ""),
                kind=kind,
                url=c.get("url", ""),
                note=c.get("description", ""),
            )
        )
    return candidates


def _incomplete(element_id: str) -> ResearchResult:
    return ResearchResult(
        element_id=element_id,
        owner=None,
        owner_confidence="low",
        licensing_contact=None,
        licensing_posture=LicensingPosture.UNKNOWN,
        litigation_history=[],
        estimated_license_cost_band=None,
        basis=[],
        status="incomplete",
    )


class ParallelClient(Protocol):
    async def research(
        self,
        element: TriagedElement,
        production_title: str,
        processor: str | None = None,
    ) -> ResearchResult: ...

    async def find_all(
        self, element: TriagedElement, production_title: str
    ) -> list[CandidateEntity]: ...

    async def create_monitor(
        self, element_id: str, query: str, frequency: str, webhook_url: str
    ) -> ClearanceWatch | None: ...


class FixtureParallelClient:
    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = Path(fixtures_dir)

    async def research(
        self,
        element: TriagedElement,
        production_title: str,
        processor: str | None = None,
    ) -> ResearchResult:
        path = self.fixtures_dir / "research" / f"{slug(element.label)}.json"
        if not path.exists():
            return _incomplete(element.id)
        return parse_task_output(element.id, json.loads(path.read_text()))

    async def find_all(
        self, element: TriagedElement, production_title: str
    ) -> list[CandidateEntity]:
        path = self.fixtures_dir / "findall" / f"{slug(element.label)}.json"
        if not path.exists():
            return []
        return parse_findall_result(json.loads(path.read_text()))

    async def create_monitor(
        self, element_id: str, query: str, frequency: str, webhook_url: str
    ) -> ClearanceWatch | None:
        return ClearanceWatch(
            element_id=element_id,
            monitor_id=f"mon-{element_id}",
            query=query,
            frequency=frequency,
        )


class LiveParallelClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.parallel.ai",
        processor: str = "pro",
        poll_interval_s: float = 10.0,
        timeout_s: float = 600.0,
        attempts: int = 2,
        backoff_s: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.processor = processor
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self.attempts = attempts
        self.backoff_s = backoff_s
        self._headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    async def research(
        self,
        element: TriagedElement,
        production_title: str,
        processor: str | None = None,
    ) -> ResearchResult:
        for attempt in range(self.attempts):
            try:
                return await self._research_once(element, production_title, processor)
            except (httpx.HTTPError, KeyError, ValueError):
                if attempt + 1 < self.attempts:
                    await asyncio.sleep(self.backoff_s)
        return _incomplete(element.id)

    async def _research_once(
        self,
        element: TriagedElement,
        production_title: str,
        processor: str | None = None,
    ) -> ResearchResult:
        async with httpx.AsyncClient(timeout=60.0) as client:
            created = await client.post(
                f"{self.base_url}/v1/tasks/runs",
                headers=self._headers,
                json={
                    "input": build_research_input(element, production_title),
                    "processor": processor or self.processor,
                    "task_spec": {
                        "output_schema": {
                            "type": "json",
                            "json_schema": RESEARCH_OUTPUT_SCHEMA,
                        }
                    },
                },
            )
            created.raise_for_status()
            run_id = created.json()["run_id"]

            waited = 0.0
            while waited < self.timeout_s:
                status_resp = await client.get(
                    f"{self.base_url}/v1/tasks/runs/{run_id}", headers=self._headers
                )
                status_resp.raise_for_status()
                status = status_resp.json().get("status")
                if status == "completed":
                    result = await client.get(
                        f"{self.base_url}/v1/tasks/runs/{run_id}/result",
                        headers=self._headers,
                    )
                    result.raise_for_status()
                    return parse_task_output(
                        element.id, result.json().get("output") or {}
                    )
                if status in {"failed", "cancelled"}:
                    return _incomplete(element.id)
                await asyncio.sleep(self.poll_interval_s)
                waited += self.poll_interval_s
        return _incomplete(element.id)

    async def find_all(
        self, element: TriagedElement, production_title: str
    ) -> list[CandidateEntity]:
        # FindAll is run-based (live-verified 2026-08-19): create a run, poll
        # status.status until completed, then fetch /result for candidates.
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                created = await client.post(
                    f"{self.base_url}/v1beta/findall/runs",
                    headers=self._headers,
                    json={
                        "objective": (
                            f"Find every plausible rights holder, registry, or "
                            f"attribution source for '{element.label}' "
                            f"({element.category.value}) appearing in the film "
                            f"'{production_title}'."
                        ),
                        "entity_type": "organizations or people",
                        "match_conditions": [
                            {
                                "name": "kind",
                                "description": (
                                    "What kind of entity this is with respect to the "
                                    "element (e.g. artist, rights holder, registry, "
                                    "property owner, archive, licensing agency)."
                                ),
                            }
                        ],
                        "generator": "base",
                        "match_limit": 10,
                    },
                )
                created.raise_for_status()
                findall_id = created.json()["findall_id"]

                waited = 0.0
                while waited < self.timeout_s:
                    status_resp = await client.get(
                        f"{self.base_url}/v1beta/findall/runs/{findall_id}",
                        headers=self._headers,
                    )
                    status_resp.raise_for_status()
                    status = (status_resp.json().get("status") or {}).get("status")
                    if status == "completed":
                        result = await client.get(
                            f"{self.base_url}/v1beta/findall/runs/{findall_id}/result",
                            headers=self._headers,
                        )
                        result.raise_for_status()
                        return parse_findall_result(result.json(), limit=10)
                    if status in {"failed", "cancelled"}:
                        return []
                    await asyncio.sleep(self.poll_interval_s)
                    waited += self.poll_interval_s
                return []
        except (httpx.HTTPError, KeyError, ValueError):
            return []

    async def create_monitor(
        self, element_id: str, query: str, frequency: str, webhook_url: str
    ) -> ClearanceWatch | None:
        # Monitors are a gated beta product (live-checked 2026-08-19: this key
        # gets 401 "Product(s) unavailable to provided credential"). When the
        # remote monitor can't be created, fall back to a local standing watch —
        # the webhook receiver and reopen-review flow work identically; only the
        # external change-detection trigger is missing.
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1beta/monitors",
                    headers=self._headers,
                    json={
                        "type": "web_change",
                        "frequency": frequency,
                        "settings": {"query": query},
                        "webhook": {"url": webhook_url},
                    },
                )
                resp.raise_for_status()
                return ClearanceWatch(
                    element_id=element_id,
                    monitor_id=resp.json().get("monitor_id", f"mon-{element_id}"),
                    query=query,
                    frequency=frequency,
                )
        except (httpx.HTTPError, KeyError, ValueError):
            return ClearanceWatch(
                element_id=element_id,
                monitor_id=f"local-{element_id}",
                query=query,
                frequency=frequency,
            )
