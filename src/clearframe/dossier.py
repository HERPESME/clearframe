"""Clearance dossier assembly — the E&O-ready report built from reviewed findings."""

from pydantic import BaseModel

from clearframe.models import (
    AuditEvent,
    CourtOpinion,
    Decision,
    Production,
    ProductionState,
    RemediationOption,
    ResearchResult,
    RiskAssessment,
    RiskBand,
    TimeRange,
    TriagedElement,
    research_is_incomplete,
)


def pending_ids(state: ProductionState) -> list[str]:
    """Elements that still lack a review decision."""
    return [el.id for el in state.elements if el.id not in state.decisions]

DISCLAIMER = (
    "This clearance report is automated decision support generated from AI video "
    "analysis and open-web rights research. It is NOT legal advice; all findings "
    "require review by qualified clearance counsel before reliance."
)


class DossierEntry(BaseModel):
    element: TriagedElement
    research: ResearchResult | None
    risk: RiskAssessment
    options: list[RemediationOption]
    decision: Decision | None
    court: CourtOpinion | None = None


class ClearanceDossier(BaseModel):
    production: Production
    generated_at: str
    entries: list[DossierEntry]
    summary: dict[str, int]
    unscanned_ranges: list[TimeRange]
    audit: list[AuditEvent] = []
    disclaimer: str = DISCLAIMER


def build_dossier(state: ProductionState, generated_at: str) -> ClearanceDossier:
    entries = [
        DossierEntry(
            element=el,
            research=state.research.get(el.id),
            risk=state.risk[el.id],
            options=state.remediation.get(el.id, []),
            decision=state.decisions.get(el.id),
            court=state.court.get(el.id),
        )
        for el in state.elements
    ]
    entries.sort(key=lambda e: e.risk.score, reverse=True)

    summary = {band.value: 0 for band in RiskBand}
    for e in entries:
        summary[e.risk.band.value] += 1
    summary["incomplete_research"] = sum(
        1 for e in entries if research_is_incomplete(e.research)
    )
    summary["pending_decisions"] = sum(1 for e in entries if e.decision is None)

    return ClearanceDossier(
        production=state.production,
        generated_at=generated_at,
        entries=entries,
        summary=summary,
        unscanned_ranges=state.unscanned_ranges,
        audit=state.audit_log,
    )


def auto_decisions(state: ProductionState) -> dict[str, Decision]:
    """Demo/auto-approve decision map by risk band (reviewer 'auto-demo')."""
    decisions: dict[str, Decision] = {}
    for el in state.elements:
        research = state.research.get(el.id)
        risk = state.risk[el.id]
        if research_is_incomplete(research):
            action, note = "escalate", "Rights holder could not be identified; escalate to counsel."
        elif risk.band == RiskBand.LOW:
            action, note = "approve_risk", "Low risk accepted per de-minimis/low-prominence policy."
        else:
            action, note = "license", "Pursue license via drafted outreach."
        decisions[el.id] = Decision(
            element_id=el.id, action=action, reviewer="auto-demo", role="legal", note=note
        )
    return decisions
