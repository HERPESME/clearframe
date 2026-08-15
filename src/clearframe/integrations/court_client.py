"""The Clearance Court: adversarial legal debate over contested findings.

Two opposing agents — Studio Counsel (argues the use is risky/infringing) and
the Fair Use Advocate (argues de minimis / expressive-work defenses) — each
brief the case with precedent; a Judge weighs the briefs and issues a reasoned
opinion. The opinion NEVER changes the deterministic risk score; it attaches
legal reasoning for the human reviewer.

Fixture client replays authored case files (real case law). Live client runs
three Gemini persona calls per case; enriching briefs with Parallel-researched
precedent is a live-mode upgrade once API keys exist.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from clearframe.integrations.parallel_client import slug
from clearframe.models import (
    Brief,
    CourtOpinion,
    Production,
    ResearchResult,
    RiskAssessment,
    TriagedElement,
)


@dataclass
class CourtCase:
    element: TriagedElement
    research: ResearchResult | None
    risk: RiskAssessment
    production: Production


class CourtClient(Protocol):
    async def try_case(self, case: CourtCase) -> CourtOpinion | None: ...


def parse_case_file(element_id: str, payload: dict) -> CourtOpinion:
    briefs = [Brief.model_validate(b) for b in payload.get("briefs", [])]
    opinion = payload.get("opinion") or {}
    return CourtOpinion(
        element_id=element_id,
        holding=opinion.get("holding", "escalate"),
        confidence=opinion.get("confidence", "low"),
        reasoning=opinion.get("reasoning", ""),
        briefs=briefs,
    )


class FixtureCourtClient:
    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = Path(fixtures_dir)

    async def try_case(self, case: CourtCase) -> CourtOpinion | None:
        path = self.fixtures_dir / "court" / f"{slug(case.element.label)}.json"
        if not path.exists():
            return None
        try:
            return parse_case_file(case.element.id, json.loads(path.read_text()))
        except (json.JSONDecodeError, ValidationError):
            return None


COUNSEL_PROMPT = (
    "You are STUDIO COUNSEL for the production '{production}'. Argue why the "
    "on-screen element '{label}' ({category}, prominence: {prominence}) is a "
    "clearance risk that must be licensed, removed, or altered. Rights research "
    "found: {research}. Cite real, accurately-named case law and statutes with "
    "correct citations. Return JSON: {{\"argument\": str, \"precedents\": "
    "[{{\"case_name\", \"citation\", \"holding\", \"relevance\"}}]}}."
)

ADVOCATE_PROMPT = (
    "You are the FAIR USE ADVOCATE for the production '{production}'. Argue the "
    "strongest good-faith defense for the on-screen element '{label}' "
    "({category}, prominence: {prominence}) — de minimis, incidental use, "
    "Rogers v. Grimaldi expressive-work protection, or fair use, as applicable. "
    "Be candid where the defense is weak. Rights research found: {research}. "
    "Cite real case law accurately. Return JSON: {{\"argument\": str, "
    "\"precedents\": [{{\"case_name\", \"citation\", \"holding\", \"relevance\"}}]}}."
)

JUDGE_PROMPT = (
    "You are the JUDGE of a studio clearance court. Weigh these two briefs about "
    "'{label}' and issue a practical ruling for the producer. Counsel argues:\n"
    "{counsel}\n\nAdvocate argues:\n{advocate}\n\n"
    "Return JSON: {{\"holding\": \"clear_required\"|\"defensible\"|\"escalate\", "
    "\"confidence\": \"low\"|\"medium\"|\"high\", \"reasoning\": str}} — "
    "reason from the briefs' precedents AND practical cost (license cost vs "
    "litigation exposure vs VFX/reshoot cost)."
)

BRIEF_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "argument": {"type": "string"},
        "precedents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "case_name": {"type": "string"},
                    "citation": {"type": "string"},
                    "holding": {"type": "string"},
                    "relevance": {"type": "string"},
                },
                "required": ["case_name", "citation", "holding", "relevance"],
            },
        },
    },
    "required": ["argument", "precedents"],
}

RULING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "holding": {
            "type": "string",
            "enum": ["clear_required", "defensible", "escalate"],
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "reasoning": {"type": "string"},
    },
    "required": ["holding", "confidence", "reasoning"],
}


class LiveCourtClient:
    """Gemini-persona court. TODO(keys-day): enrich briefs with Parallel
    precedent research tasks before adjudication."""

    def __init__(self, project: str, location: str, model: str, client_factory=None):
        self.project = project
        self.location = location
        self.model = model
        self._client_factory = client_factory
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                from google import genai

                self._client = genai.Client(
                    vertexai=True, project=self.project, location=self.location
                )
        return self._client

    def _ask_json(self, prompt: str, schema: dict) -> dict:
        try:
            from google.genai import types as genai_types

            config = genai_types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=schema
            )
        except ImportError:
            config = {"response_mime_type": "application/json"}
        resp = self._client_or_create().models.generate_content(
            model=self.model, contents=[prompt], config=config
        )
        return json.loads(resp.text or "{}")

    async def try_case(self, case: CourtCase) -> CourtOpinion | None:
        import asyncio

        el = case.element
        research_summary = (
            f"owner={case.research.owner}, posture={case.research.licensing_posture.value}, "
            f"history={'; '.join(case.research.litigation_history) or 'none'}"
            if case.research and case.research.owner
            else "rights holder could not be identified"
        )
        prominence = (
            f"{el.prominence.screen_time_s}s screen time, "
            f"{el.prominence.frame_coverage:.0%} coverage, "
            f"plot_integral={el.prominence.plot_integral}"
        )
        fmt = dict(
            production=case.production.title,
            label=el.label,
            category=el.category.value,
            prominence=prominence,
            research=research_summary,
        )

        def _run() -> CourtOpinion:
            counsel = self._ask_json(COUNSEL_PROMPT.format(**fmt), BRIEF_SCHEMA)
            advocate = self._ask_json(ADVOCATE_PROMPT.format(**fmt), BRIEF_SCHEMA)
            ruling = self._ask_json(
                JUDGE_PROMPT.format(
                    label=el.label,
                    counsel=json.dumps(counsel),
                    advocate=json.dumps(advocate),
                ),
                RULING_SCHEMA,
            )
            return parse_case_file(
                el.id,
                {
                    "briefs": [
                        {"side": "counsel", **counsel},
                        {"side": "advocate", **advocate},
                    ],
                    "opinion": ruling,
                },
            )

        try:
            return await asyncio.to_thread(_run)
        except Exception:
            return None  # court is best-effort; a failed case never blocks the pipeline
