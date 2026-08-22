"""Stage 3: planned, capped, concurrent rights-research fan-out.

The Budget Planner assigns each element a Parallel processor tier with a
recorded rationale; a spend cap (`max_research`) bounds the fan-out on long
footage (budget to the most prominent elements first). Overflow surfaces
honestly as RESEARCH_INCOMPLETE instead of being silently dropped.
"""

import asyncio

from clearframe.corroboration import blocks_research
from clearframe.integrations.parallel_client import _incomplete
from clearframe.models import ClearanceCategory
from clearframe.pipeline import PipelineContext
from clearframe.planner import plan_research


class ResearchStage:
    name = "research"

    def __init__(self, max_research: int = 25):
        self.max_research = max_research

    async def run(self, ctx: PipelineContext) -> None:
        elements = ctx.state.elements
        plan = plan_research(elements)
        ctx.state.research_plan = plan
        ctx.emit(
            {
                "type": "research_planned",
                "total_est_cost_usd": round(sum(p.est_cost_usd for p in plan.values()), 2),
            }
        )

        # A disputed identity must not be researched: the whole point of
        # research is "who owns THIS", and we do not yet agree on what THIS is.
        blocked = [
            el for el in elements if blocks_research(ctx.state.corroboration.get(el.id))
        ]
        for el in blocked:
            ctx.emit(
                {
                    "type": "research_blocked",
                    "element_id": el.id,
                    "label": el.label,
                    "reason": "identity conflict",
                }
            )

        researchable = [el for el in elements if el not in blocked]
        ranked = sorted(
            researchable, key=lambda el: el.prominence.screen_time_s, reverse=True
        )
        funded = ranked[: self.max_research]
        skipped = ranked[self.max_research :] + blocked

        async def _one(el):
            ctx.emit(
                {
                    "type": "research_start",
                    "element_id": el.id,
                    "label": el.label,
                    "processor": plan[el.id].processor,
                }
            )
            result = await ctx.parallel.research(
                el, ctx.state.production.title, processor=plan[el.id].processor
            )
            ctx.emit(
                {
                    "type": "research_done",
                    "element_id": el.id,
                    "status": result.status,
                    "owner": result.owner,
                }
            )
            return result

        results = await asyncio.gather(*(_one(el) for el in funded))
        research = {el.id: res for el, res in zip(funded, results)}
        for el in skipped:
            research[el.id] = _incomplete(el.id)
        ctx.state.research = research

        # FindAll enumeration: when deep research can't identify an owner of an
        # IP-bearing element, enumerate candidate rights holders (recall-first)
        # instead of leaving a dead end.
        enumerable = {
            ClearanceCategory.COPYRIGHT_ART,
            ClearanceCategory.TRADEMARK,
            ClearanceCategory.MUSIC_SYNC,
        }
        for el in elements:
            if research[el.id].status != "incomplete" or el.category not in enumerable:
                continue
            if blocks_research(ctx.state.corroboration.get(el.id)):
                continue  # resolve identity first; enumerating a disputed mark is noise
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
