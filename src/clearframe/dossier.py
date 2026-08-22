"""Clearance dossier assembly — the E&O-ready report built from reviewed findings."""

from pydantic import BaseModel

from clearframe.models import (
    AuditEvent,
    Corroboration,
    Coverage,
    CoverageStatus,
    CourtOpinion,
    Decision,
    FreshnessSignal,
    IdentityVerdict,
    Production,
    ProductionState,
    RemediationOption,
    ResearchResult,
    ResearchRoute,
    SponsorConflict,
    UseContext,
    ResearchTier,
    RiskAssessment,
    RiskBand,
    TerritoryRisk,
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
    corroboration: Corroboration | None = None
    freshness: list[FreshnessSignal] = []
    territory: list[TerritoryRisk] = []
    coverage: Coverage | None = None
    route: ResearchRoute | None = None


class ClearanceDossier(BaseModel):
    production: Production
    generated_at: str
    entries: list[DossierEntry]
    summary: dict[str, int]
    unscanned_ranges: list[TimeRange]
    audit: list[AuditEvent] = []
    territories: list[str] = []
    sponsor_conflicts: list[SponsorConflict] = []
    use_context: UseContext = UseContext.EXPRESSIVE
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
            corroboration=state.corroboration.get(el.id),
            freshness=state.freshness.get(el.id, []),
            territory=state.territory_risk.get(el.id, []),
            coverage=state.coverage.get(el.id),
            route=state.routes.get(el.id),
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
    # The honesty guardrail. A finding resolved without paying for research is
    # still a finding, and E&O carriers reject "incidental use" asserted without
    # documentation — so what the ladder settled cheaply is counted here and
    # printed with its authority, never dropped.
    summary["resolved_by_statute"] = sum(
        1 for e in entries if e.route is not None and e.route.tier is ResearchTier.STATUTE
    )
    summary["resolved_locally"] = sum(
        1 for e in entries if e.route is not None and e.route.tier is ResearchTier.LOCAL
    )
    summary["deep_research_runs"] = sum(
        1 for e in entries if e.route is not None and e.route.tier is ResearchTier.DEEP
    )
    summary["pending_decisions"] = sum(1 for e in entries if e.decision is None)
    summary["identity_conflicts"] = sum(
        1
        for e in entries
        if e.corroboration is not None
        and e.corroboration.verdict is IdentityVerdict.CONFLICTED
    )
    summary["identity_corroborated"] = sum(
        1
        for e in entries
        if e.corroboration is not None
        and e.corroboration.verdict
        in (IdentityVerdict.CORROBORATED, IdentityVerdict.FINGERPRINTED)
    )
    summary["identity_fingerprinted"] = sum(
        1
        for e in entries
        if e.corroboration is not None
        and e.corroboration.verdict is IdentityVerdict.FINGERPRINTED
    )
    summary["material_freshness_signals"] = sum(
        1 for e in entries for s in e.freshness if s.material
    )
    for status in CoverageStatus:
        summary[f"coverage_{status.value.lower()}"] = sum(
            1 for e in entries if e.coverage is not None and e.coverage.status is status
        )

    return ClearanceDossier(
        production=state.production,
        generated_at=generated_at,
        entries=entries,
        summary=summary,
        unscanned_ranges=state.unscanned_ranges,
        audit=state.audit_log,
        territories=state.territories,
        sponsor_conflicts=state.sponsor_conflicts,
        use_context=state.production.use_context,
    )


def auto_decisions(state: ProductionState) -> dict[str, Decision]:
    """Demo/auto-approve decision map by risk band (reviewer 'auto-demo')."""
    decisions: dict[str, Decision] = {}
    for el in state.elements:
        research = state.research.get(el.id)
        risk = state.risk[el.id]
        corroboration = state.corroboration.get(el.id)
        coverage = state.coverage.get(el.id)
        if coverage is not None and coverage.status is CoverageStatus.COVERED:
            action, note = (
                "approve_risk",
                f"Already licensed — {coverage.note}",
            )
        elif coverage is not None and coverage.status is CoverageStatus.PARTIAL:
            action, note = (
                "license",
                "Licence on file does not reach this use: "
                + "; ".join(coverage.gaps),
            )
        elif corroboration is not None and corroboration.verdict is IdentityVerdict.CONFLICTED:
            action, note = (
                "escalate",
                "Detectors disagree on what this element is; identity must be resolved before clearance.",
            )
        elif research_is_incomplete(research):
            action, note = "escalate", "Rights holder could not be identified; escalate to counsel."
        elif risk.band == RiskBand.LOW:
            action, note = "approve_risk", "Low risk accepted per de-minimis/low-prominence policy."
        else:
            action, note = "license", "Pursue license via drafted outreach."
        decisions[el.id] = Decision(
            element_id=el.id, action=action, reviewer="auto-demo", role="legal", note=note
        )
    return decisions
