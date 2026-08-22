"""clearframe-mcp: the clearance pipeline as MCP tools.

Any MCP client (Gemini Enterprise, Claude, IDEs) can drive a full clearance
workflow: run the pipeline, inspect evidence, record role-gated decisions, and
generate the E&O dossier. Shares the same stores, pipeline, and review service
as the CLI and web app — one set of rules, three transports.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from clearframe.config import ClearFrameConfig, validate_live
from clearframe.dossier import pending_ids
from clearframe.models import Production, RiskBand, research_is_incomplete
from clearframe.pipeline import (
    Pipeline,
    build_context,
    build_demo_pipeline,
    demo_context,
)
from clearframe.review import generate_dossier_async, record_decision
from clearframe.store import LicenceStore, LocalJsonStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_server(out_root: Path) -> MCPServer:
    out_root = Path(out_root)
    store = LocalJsonStore(out_root / "state")
    ledger = LicenceStore(out_root / "state")

    server = MCPServer(
        name="clearframe",
        title="ClearFrame Rights Clearance",
        instructions=(
            "Autonomous rights-clearance for film/TV footage. Typical flow: "
            "run_clearance -> list_findings -> get_finding (evidence) -> "
            "record_decision per finding (role legal/producer) -> generate_dossier."
        ),
        version="0.1.0",
    )

    def _state(production_id: str):
        try:
            return store.load(production_id)
        except FileNotFoundError:
            raise ValueError(f"Unknown production: {production_id}")

    @server.tool()
    async def run_clearance(
        footage_uri: str,
        title: str,
        production_id: str = "demo",
        duration_s: float = 0.0,
        fps: float = 24.0,
    ) -> dict:
        """Run the clearance pipeline on footage and return a findings summary.

        Use footage_uri "demo://salted-scene" for the credential-free demo
        production; a local path or gs:// URI runs live (requires
        GOOGLE_CLOUD_PROJECT and PARALLEL_API_KEY in the environment).
        """
        if footage_uri.startswith("demo://"):
            ctx = demo_context(out_root)
        else:
            cfg = ClearFrameConfig.from_env(os.environ).model_copy(
                update={"mode": "live"}
            )
            missing = validate_live(cfg)
            if missing:
                raise ValueError(
                    "Live mode needs credentials. Missing environment variables: "
                    + ", ".join(missing)
                )
            production = Production(
                id=production_id,
                title=title,
                footage_uri=footage_uri,
                fps=fps,
                duration_s=duration_s,
            )
            ctx = build_context(cfg, production, out_root)
        ctx.store = store
        try:
            ctx.state = store.load(ctx.state.production.id)  # resume if persisted
        except FileNotFoundError:
            pass
        state = await Pipeline(build_demo_pipeline()).run(ctx)

        bands = {b.value: 0 for b in RiskBand}
        for risk in state.risk.values():
            bands[risk.band.value] += 1
        return {
            "production_id": state.production.id,
            "title": state.production.title,
            "findings": len(state.elements),
            "bands": bands,
            "research_incomplete": sum(
                1 for el in state.elements if research_is_incomplete(state.research.get(el.id))
            ),
            "pending_decisions": pending_ids(state),
        }

    @server.tool()
    def get_status(production_id: str) -> dict:
        """Pipeline stage status and pending review decisions for a production."""
        state = _state(production_id)
        return {
            "production_id": production_id,
            "stage_status": state.stage_status,
            "pending": pending_ids(state),
            "decisions_recorded": len(state.decisions),
        }

    @server.tool()
    def list_findings(production_id: str) -> dict:
        """All clearable findings with risk band/score, owner, and decision state, highest risk first."""
        state = _state(production_id)
        findings = []
        for el in sorted(
            state.elements, key=lambda e: state.risk[e.id].score, reverse=True
        ):
            research = state.research.get(el.id)
            decision = state.decisions.get(el.id)
            findings.append(
                {
                    "id": el.id,
                    "label": el.label,
                    "category": el.category.value,
                    "band": state.risk[el.id].band.value,
                    "score": state.risk[el.id].score,
                    "owner": research.owner if research else None,
                    "decision": decision.action if decision else None,
                    "identity": (
                        state.corroboration[el.id].verdict.value
                        if el.id in state.corroboration
                        else None
                    ),
                    "resolved_by": (
                        state.routes[el.id].tier.value if el.id in state.routes else None
                    ),
                    "depiction": el.depiction.value if el.depiction else None,
                    "coverage": (
                        state.coverage[el.id].status.value
                        if el.id in state.coverage
                        else None
                    ),
                }
            )
        return {"production_id": production_id, "findings": findings}

    @server.tool()
    def get_finding(production_id: str, element_id: str) -> dict:
        """Full evidence for one finding: detection, research with citations, risk factors, remediation options."""
        state = _state(production_id)
        element = next((el for el in state.elements if el.id == element_id), None)
        if element is None:
            raise ValueError(f"Unknown element: {element_id}")
        research = state.research.get(element_id)
        decision = state.decisions.get(element_id)
        opinion = state.court.get(element_id)
        return {
            "element": element.model_dump(mode="json"),
            "research": research.model_dump(mode="json") if research else None,
            "risk": state.risk[element_id].model_dump(mode="json"),
            "remediation": [
                o.model_dump(mode="json") for o in state.remediation.get(element_id, [])
            ],
            "court": opinion.model_dump(mode="json") if opinion else None,
            "decision": decision.model_dump(mode="json") if decision else None,
            "corroboration": (
                state.corroboration[element_id].model_dump(mode="json")
                if element_id in state.corroboration
                else None
            ),
            # Which rung of the escalation ladder answered this, and under what
            # authority. A finding resolved for free is a documented position,
            # so a client must be able to read the reasoning, not just the tier.
            "route": (
                state.routes[element_id].model_dump(mode="json")
                if element_id in state.routes
                else None
            ),
            # Not an infringement — a contract exposure. Category exclusivity
            # means a rival mark in shot can void a sponsorship fee even though
            # showing it is lawful, and nothing else here would flag it.
            # What the PLATFORM does, which is not what a court would do.
            "platform_outcome": next(
                (
                    o.model_dump(mode="json")
                    for o in state.platform_outcomes
                    if o.element_id == element_id
                ),
                None,
            ),
            "sponsor_conflicts": [
                c.model_dump(mode="json")
                for c in state.sponsor_conflicts
                if c.element_id == element_id
            ],
            "freshness": [
                s.model_dump(mode="json") for s in state.freshness.get(element_id, [])
            ],
            "territory_risk": [
                t.model_dump(mode="json")
                for t in state.territory_risk.get(element_id, [])
            ],
            "coverage": (
                state.coverage[element_id].model_dump(mode="json")
                if element_id in state.coverage
                else None
            ),
        }

    @server.tool(name="record_decision")
    def record_decision_tool(
        production_id: str,
        element_id: str,
        action: str,
        note: str = "",
        role: str = "legal",
    ) -> dict:
        """Record a review decision (action: approve_risk | license | blur | reshoot | escalate).

        Role must be 'legal' or 'producer'; editors are read-only. Every
        decision is appended to the production's audit trail.
        """
        try:
            state = record_decision(
                store,
                production_id,
                element_id,
                action,
                note,
                role=role,
                reviewer=f"mcp:{role}",
                at=_now(),
            )
        except FileNotFoundError:
            raise ValueError(f"Unknown production: {production_id}")
        except Exception as exc:
            raise ValueError(str(exc))
        return {"ok": True, "pending": pending_ids(state)}

    @server.tool()
    def verify_identities(production_id: str) -> dict:
        """Identity-corroboration report: which findings a second, independent
        detector confirmed, and which are disputed.

        A CONFLICTED finding is never auto-researched — researching a disputed
        mark would attribute rights to the wrong holder. Resolve identity first,
        then re-run clearance.
        """
        state = _state(production_id)
        rows = []
        for el in state.elements:
            c = state.corroboration.get(el.id)
            if c is None:
                continue
            rows.append(
                {
                    "id": el.id,
                    "label": el.label,
                    "verdict": c.verdict.value,
                    "detector": c.detector,
                    "detected_label": c.detected_label,
                    "confidence": c.confidence,
                    "note": c.note,
                }
            )
        conflicts = [r for r in rows if r["verdict"] == "CONFLICTED"]
        return {
            "production_id": production_id,
            "findings": rows,
            "conflicts": len(conflicts),
            "blocked_from_research": [r["id"] for r in conflicts],
        }

    @server.tool()
    def territory_report(production_id: str) -> dict:
        """Per-territory clearance exposure for the release plan.

        Clearance is jurisdictional: freedom-of-panorama rules mean the same
        artwork in frame can be LOW in one territory and HIGH in another.
        Returns each finding banded per territory with the governing authority.
        """
        state = _state(production_id)
        rows = []
        for el in state.elements:
            bands = state.territory_risk.get(el.id, [])
            if not bands:
                continue
            rows.append(
                {
                    "id": el.id,
                    "label": el.label,
                    "baseline": state.risk[el.id].band.value,
                    "by_territory": {
                        t.territory: {
                            "band": t.band.value,
                            "rationale": t.rationale,
                            "authority": t.authority,
                        }
                        for t in bands
                    },
                }
            )
        return {
            "production_id": production_id,
            "territories": state.territories,
            "findings": rows,
        }

    @server.tool()
    async def check_freshness(production_id: str) -> dict:
        """Re-run the live Parallel Search pass over every identified rights
        holder and report enforcement activity found right now.

        Deep research is a snapshot; this is the live check a reviewer runs
        before signing off. Costs cents per finding, not dollars.
        """
        from clearframe.review import refresh_freshness

        state, checked = await refresh_freshness(store, out_root, production_id, at=_now())
        return {
            "production_id": production_id,
            "checked": checked,
            "material_signals": {
                eid: sum(1 for s in sigs if s.material)
                for eid, sigs in state.freshness.items()
                if any(s.material for s in sigs)
            },
        }

    @server.tool()
    def list_licences() -> dict:
        """The rights ledger: clearances this deployment already holds."""
        licences = ledger.load()
        return {
            "count": len(licences),
            "licences": [lic.model_dump(mode="json") for lic in licences],
        }

    @server.tool()
    def check_coverage(production_id: str) -> dict:
        """Which findings are already licensed, and exactly where the gaps are.

        COVERED      a matching grant reaches this use
        PARTIAL      a grant exists but misses territory, term or media scope
        NOT_COVERED  rights holder identified, nothing on file
        UNKNOWN      ownership or identity unresolved, so coverage is unknowable
        """
        state = _state(production_id)
        rows = []
        for el in state.elements:
            cov = state.coverage.get(el.id)
            if cov is None:
                continue
            rows.append(
                {
                    "id": el.id,
                    "label": el.label,
                    "status": cov.status.value,
                    "licence_id": cov.licence_id,
                    "gaps": cov.gaps,
                    "note": cov.note,
                }
            )
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "production_id": production_id,
            "territories": state.territories,
            "distribution": state.production.distribution,
            "summary": counts,
            "findings": rows,
            "needs_clearance": [r["id"] for r in rows if r["status"] != "COVERED"],
        }

    @server.tool()
    async def generate_dossier(production_id: str) -> dict:
        """Generate the E&O clearance dossier and export artifacts (requires every finding decided)."""
        from clearframe.stages.dossier import ReviewPendingError

        try:
            artifacts = await generate_dossier_async(
                store, out_root, production_id, at=_now()
            )
        except FileNotFoundError:
            raise ValueError(f"Unknown production: {production_id}")
        except ReviewPendingError as exc:
            raise ValueError(str(exc))
        return {"production_id": production_id, "artifacts": artifacts, "out_dir": str(out_root)}

    return server
