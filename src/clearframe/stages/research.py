"""Stage: dispatch each finding to the cheapest rung that can answer it.

Before the ladder this stage sent every element to Parallel's Task API. On a
21.8-second clip that was sixteen deep runs, six of which returned no owner,
and twenty minutes of wall clock. Seven of the sixteen were human faces, and
no amount of web research produces a release form.

`routing.py` decides the rung; this stage carries it out:

  LOCAL    answer synthesised from the local rights table       0 ms   $0
  STATUTE  answer is a documented legal position, not a lookup  0 ms   $0
  SEARCH   Parallel Search — posture, contact, live citations   ~2 s   $0.005
  DEEP     Parallel Task — full ownership investigation         minutes

Two properties are load-bearing:

* Cheap rungs still produce a real `ResearchResult` with citations, because
  E&O carriers do not accept fair use offered in place of clearance. A finding
  resolved for free is a documented position, never a silent skip.
* SEARCH and DEEP fan out concurrently and SEARCH does not wait behind DEEP,
  so posture for the cheap findings lands seconds into the stage while the
  handful of deep runs are still going.
"""

import asyncio

from clearframe.corroboration import blocks_research
from clearframe.freshness import is_material
from clearframe.integrations.parallel_client import _incomplete
from clearframe.knowledge import load_knowledge
from clearframe.models import (
    BasisCitation,
    ClearanceCategory,
    LicensingPosture,
    ResearchResult,
    ResearchRoute,
    ResearchTier,
    TriagedElement,
    UseContext,
    WebFinding,
)
from clearframe.pipeline import PipelineContext
from clearframe.planner import EST_COST, plan_research
from clearframe.routing import route_all, summarise_routes

# How to describe the work to a researcher. Rogers v. Grimaldi protects films
# and not adverts, so a search framed around the wrong medium returns guidance
# that does not apply to the user's actual exposure.
USE_CONTEXT_MEDIUM: dict[UseContext, str] = {
    UseContext.EXPRESSIVE: "a film or television production",
    UseContext.SPONSORED: "sponsored online video content with a paid brand placement",
    UseContext.ADVERTISING: "a commercial advertisement or brand campaign",
    UseContext.NEWS: "a news or journalistic report",
    UseContext.EDUCATIONAL: "educational or critical commentary",
}

ENUMERABLE = {
    ClearanceCategory.COPYRIGHT_ART,
    ClearanceCategory.TRADEMARK,
    ClearanceCategory.MUSIC_SYNC,
}


def _local_result(el: TriagedElement, r: ResearchRoute, verified_on: str) -> ResearchResult:
    return ResearchResult(
        element_id=el.id,
        owner=r.owner,
        owner_confidence="high",
        licensing_contact=None,
        licensing_posture=r.posture or LicensingPosture.UNKNOWN,
        litigation_history=[r.basis] if r.basis else [],
        estimated_license_cost_band=None,
        basis=[
            BasisCitation(
                field="owner",
                url="",
                excerpt=r.basis,
                reasoning=(
                    f"Local rights knowledge base, verified {verified_on}. Ownership "
                    "is a corporate fact that does not change between pipeline runs."
                ),
                confidence="high",
            )
        ],
        status="complete",
    )


def _statute_result(el: TriagedElement, r: ResearchRoute) -> ResearchResult:
    """A finding resolved by law rather than by lookup.

    Marked complete because the investigation IS finished: we determined that
    research is not the instrument this needs. What to do about it lives on the
    route's `disposition` and is printed in the dossier, so nothing disappears.
    """
    return ResearchResult(
        element_id=el.id,
        owner=None,
        owner_confidence="low",
        licensing_contact=None,
        licensing_posture=LicensingPosture.UNKNOWN,
        litigation_history=[],
        estimated_license_cost_band=None,
        basis=[
            BasisCitation(
                field="clearance_route",
                url="",
                excerpt=r.basis,
                reasoning=f"{r.rationale} Required action: {r.disposition}",
                confidence="high",
            )
        ],
        status="complete",
    )


def _search_result(
    el: TriagedElement, r: ResearchRoute, findings: list[WebFinding]
) -> ResearchResult:
    material = [f for f in findings if is_material(f)]
    if material:
        posture = LicensingPosture.LITIGIOUS
    elif findings:
        posture = LicensingPosture.STANDARD
    else:
        posture = LicensingPosture.UNKNOWN

    basis: list[BasisCitation] = []
    if r.owner:
        basis.append(
            BasisCitation(
                field="owner",
                url="",
                excerpt=r.owner,
                reasoning="Resolved from the local rights knowledge base.",
                confidence="high",
            )
        )
    basis.extend(
        BasisCitation(
            field="licensing_posture",
            url=f.url,
            excerpt=f.excerpt,
            reasoning=(
                "Enforcement signal found by live Parallel Search."
                if is_material(f)
                else "Live Parallel Search result on the rights holder."
            ),
            confidence="medium",
        )
        for f in findings[:4]
    )

    return ResearchResult(
        element_id=el.id,
        owner=r.owner,
        owner_confidence="high" if r.owner else "low",
        licensing_contact=None,
        licensing_posture=posture,
        litigation_history=[f.title for f in material][:4],
        estimated_license_cost_band=None,
        basis=basis,
        # Without an owner AND without a single search result there is nothing
        # to stand on; say so rather than reporting an empty answer as done.
        status="complete" if (r.owner or findings) else "incomplete",
    )


class ResearchStage:
    name = "research"

    def __init__(self, max_research: int = 25):
        self.max_research = max_research

    async def run(self, ctx: PipelineContext) -> None:
        elements = ctx.state.elements
        kb = load_knowledge()
        by_id = {el.id: el for el in elements}

        # `preview` already routed everything so the producer could see the
        # rungs before the expensive one started. Reuse those decisions rather
        # than recomputing: identical inputs, but a single recorded answer.
        use_context = ctx.state.production.use_context
        routes = ctx.state.routes or route_all(
            elements,
            kb,
            ctx.state.corroboration,
            use_context=use_context,
            sponsors=ctx.state.production.sponsors,
        )

        # A CONFLICTED identity is routed BLOCKED by the router; keep the
        # explicit check so the invariant holds even if routing changes.
        for el in elements:
            if blocks_research(ctx.state.corroboration.get(el.id)):
                routes[el.id] = routes[el.id].model_copy(
                    update={"tier": ResearchTier.BLOCKED}
                )
                ctx.emit(
                    {
                        "type": "research_blocked",
                        "element_id": el.id,
                        "label": el.label,
                        "reason": "identity conflict",
                    }
                )

        deep_ids = [eid for eid, r in routes.items() if r.tier is ResearchTier.DEEP]
        # The spend cap applies only to the expensive rung; the cheap ones are
        # free and must never be dropped for budget.
        ranked = sorted(
            deep_ids, key=lambda i: by_id[i].prominence.screen_time_s, reverse=True
        )
        funded, overflow = ranked[: self.max_research], ranked[self.max_research :]

        plan = plan_research([by_id[i] for i in funded])
        ctx.state.research_plan = plan
        for eid in funded:
            routes[eid] = routes[eid].model_copy(
                update={"est_cost_usd": EST_COST[plan[eid].processor]}
            )
        for eid in overflow:
            routes[eid] = routes[eid].model_copy(
                update={
                    "tier": ResearchTier.BLOCKED,
                    "rationale": (
                        "Beyond the research spend cap for this run. Reported as "
                        "RESEARCH INCOMPLETE rather than silently dropped."
                    ),
                }
            )

        ctx.state.routes = routes
        summary = summarise_routes(routes)
        ctx.emit(
            {
                "type": "research_planned",
                "total_est_cost_usd": round(summary["est_cost_usd"], 2),
                "deep_runs": summary["deep_runs"],
                "routes": summary["counts"],
            }
        )

        research: dict[str, ResearchResult] = {}

        # ---- free rungs: instant, no network -----------------------------
        for eid, r in routes.items():
            el = by_id[eid]
            if r.tier is ResearchTier.LOCAL:
                research[eid] = _local_result(el, r, kb.verified_on)
            elif r.tier is ResearchTier.STATUTE:
                research[eid] = _statute_result(el, r)
            elif r.tier is ResearchTier.BLOCKED:
                research[eid] = _incomplete(eid)
            if eid in research:
                ctx.emit(
                    {
                        "type": "research_resolved",
                        "element_id": eid,
                        "label": el.label,
                        "tier": r.tier.value,
                        "owner": research[eid].owner,
                    }
                )

        # ---- paid rungs: SEARCH and DEEP fan out together ----------------
        async def _do_search(eid: str) -> tuple[str, ResearchResult]:
            el, r = by_id[eid], routes[eid]
            ctx.emit(
                {"type": "research_start", "element_id": eid, "label": el.label,
                 "processor": "search"}
            )
            # The medium is not decoration: an advert and a feature are
            # different legal questions, and asking about the wrong one returns
            # research that does not apply.
            objective = (
                f"Current licensing posture, enforcement behaviour and rights-clearance "
                f"contact for '{el.label}'"
                + (f", owned by {r.owner}" if r.owner else "")
                + f", as it appears on screen in {USE_CONTEXT_MEDIUM[use_context]}."
            )
            findings = await ctx.parallel.search(
                objective, [el.label, f"{r.owner or el.label} licensing clearance"],
                max_results=5,
            )
            return eid, _search_result(el, r, findings)

        async def _do_deep(eid: str) -> tuple[str, ResearchResult]:
            el = by_id[eid]
            ctx.emit(
                {"type": "research_start", "element_id": eid, "label": el.label,
                 "processor": plan[eid].processor}
            )
            result = await ctx.parallel.research(
                el, ctx.state.production.title, processor=plan[eid].processor
            )
            # Ownership known locally must survive a deep run that came back empty.
            if result.owner is None and routes[eid].owner:
                result = result.model_copy(
                    update={"owner": routes[eid].owner, "owner_confidence": "high"}
                )
            return eid, result

        search_ids = [eid for eid, r in routes.items() if r.tier is ResearchTier.SEARCH]
        paid = await asyncio.gather(
            *(_do_search(i) for i in search_ids), *(_do_deep(i) for i in funded)
        )
        for eid, result in paid:
            research[eid] = result
            ctx.emit(
                {
                    "type": "research_done",
                    "element_id": eid,
                    "status": result.status,
                    "owner": result.owner,
                }
            )

        for el in elements:
            research.setdefault(el.id, _incomplete(el.id))
        ctx.state.research = research

        # ---- FindAll: enumerate candidates where ownership stayed open ----
        for el in elements:
            r = routes[el.id]
            if r.tier is ResearchTier.BLOCKED:
                continue
            wants = r.enumerate_candidates or research[el.id].status == "incomplete"
            if not wants or el.category not in ENUMERABLE:
                continue
            if research[el.id].owner:
                continue
            candidates = await ctx.parallel.find_all(el, ctx.state.production.title)
            if candidates:
                ctx.state.candidates[el.id] = candidates
                ctx.emit(
                    {
                        "type": "candidates_found",
                        "element_id": el.id,
                        "label": el.label,
                        "count": len(candidates),
                    }
                )
