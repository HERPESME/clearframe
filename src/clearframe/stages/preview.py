"""Stage: emit the complete footage-derived report before research begins.

Measured on a live 30-second clip: script through drift completed in about 90
seconds, and the run took 9m43s. The extra eight minutes were Parallel Task
runs on the two or three findings whose ownership genuinely needed an open-web
investigation — irreducible, and correct to spend.

But everything an editor needs to start working is already known at 90 seconds:
what is in the footage, when, where in frame, how exposed the production is by
prominence, which jurisdiction bands it worst, and what must be done about the
findings that need no research at all. The only missing column is who owns it.

So the report ships at 90 seconds and ownership arrives behind it. Risk here is
`provisional` — the same arithmetic as the final score with the posture factor
pinned at its worst case, so it is an upper bound that can only fall once
research lands, never a reassuring guess that later turns out worse.

This stage also fixes the routes, so the answer to "which rung is this going
to" is available before the expensive rung starts. Research reuses them.
"""

from clearframe.conflicts import find_sponsor_conflicts
from clearframe.exposure import assess_all_exposures, summarise_exposures
from clearframe.platform import detectability, load_platforms, platform_for, project_all
from clearframe.knowledge import load_knowledge
from clearframe.models import PreviewFinding, ResearchTier
from clearframe.pipeline import PipelineContext
from clearframe.routing import route_all, summarise_routes
from clearframe.scoring import band_for, provisional_score
from clearframe.territory import assess as assess_territory


class PreviewStage:
    name = "preview"

    async def run(self, ctx: PipelineContext) -> None:
        elements = ctx.state.elements
        if not elements:
            ctx.emit({"type": "preview_ready", "count": 0, "findings": []})
            return

        use_context = ctx.state.production.use_context
        knowledge = load_knowledge()
        routes = route_all(
            elements, knowledge, ctx.state.corroboration, use_context=use_context
        )
        ctx.state.routes = routes

        conflicts = find_sponsor_conflicts(
            elements, ctx.state.production.sponsors, knowledge
        )
        ctx.state.sponsor_conflicts = conflicts
        for c in conflicts:
            ctx.emit(
                {
                    "type": "sponsor_conflict",
                    "element_id": c.element_id,
                    "label": c.label,
                    "conflicts_with": c.conflicts_with,
                    "sector": c.sector,
                }
            )

        territories = ctx.state.production.release_territories or []
        findings: list[PreviewFinding] = []
        for el in elements:
            score = provisional_score(el, use_context)
            band = band_for(score)
            corroboration = ctx.state.corroboration.get(el.id)
            route = routes[el.id]
            findings.append(
                PreviewFinding(
                    element_id=el.id,
                    label=el.label,
                    category=el.category,
                    time_ranges=el.time_ranges,
                    bbox=el.bbox,
                    at_s=el.at_s,
                    provisional_score=score,
                    provisional_band=band,
                    identity=corroboration.verdict if corroboration else None,
                    depiction=el.depiction,
                    territory=[assess_territory(el, band, t) for t in territories],
                    route_tier=route.tier,
                    disposition=route.disposition,
                    awaiting_research=route.tier
                    in (ResearchTier.SEARCH, ResearchTier.DEEP),
                )
            )

        findings.sort(key=lambda f: f.provisional_score, reverse=True)
        ctx.state.preview = findings

        # What the PLATFORM does, which is not what a court would do. Belongs
        # in the preliminary report because it needs no research at all — the
        # fingerprint and the timecodes are already in hand.
        policy = platform_for(ctx.state.production.platform, load_platforms())
        outcomes = project_all(elements, policy, ctx.state.audio_matches)
        ctx.state.platform_outcomes = outcomes
        actionable = [o for o in outcomes if detectability(o) >= 50]
        if actionable:
            ctx.emit(
                {
                    "type": "platform_exposure",
                    "platform": policy.name,
                    "likely": len(actionable),
                    "findings": [
                        {
                            "element_id": o.element_id,
                            "action": o.action.value,
                            "confidence": o.confidence,
                            "remedy": o.remedy,
                        }
                        for o in actionable
                    ],
                }
            )

        assessed = assess_all_exposures(ctx.state.exposures, territories)
        ctx.state.assessed_exposures = assessed
        if assessed:
            ctx.emit(
                {
                    "type": "exposures_assessed",
                    **summarise_exposures(assessed),
                    "findings": [
                        {
                            "id": a.id,
                            "kind": a.kind.value,
                            "band": a.band.value,
                            "remedy": a.remedy,
                        }
                        for a in assessed
                    ],
                }
            )

        summary = summarise_routes(routes)
        ctx.emit(
            {
                "type": "preview_ready",
                "count": len(findings),
                "awaiting_research": sum(1 for f in findings if f.awaiting_research),
                "resolved_now": len(summary["resolved_without_research"]),
                "findings": [
                    {
                        "element_id": f.element_id,
                        "label": f.label,
                        "category": f.category.value,
                        "band": f.provisional_band.value,
                        "score": f.provisional_score,
                        "tier": f.route_tier.value,
                        "identity": f.identity.value if f.identity else None,
                        "depiction": f.depiction.value if f.depiction else None,
                        "start_s": f.time_ranges[0].start_s if f.time_ranges else None,
                        "awaiting_research": f.awaiting_research,
                    }
                    for f in findings
                ],
            }
        )
