"""Stage: real-time freshness check on every identified rights holder.

Deep research is a snapshot; this is the live pass. One Parallel Search call
per identified owner asks whether that holder has started enforcing since the
research ran — the question a producer actually cares about at decision time,
answered at cents per call rather than dollars per Task run.
"""

import asyncio

from clearframe.freshness import material_count, to_signals
from clearframe.integrations.parallel_client import build_freshness_objective
from clearframe.sourcework import subsumed_by
from clearframe.models import research_is_incomplete
from clearframe.pipeline import PipelineContext


class FreshnessStage:
    name = "freshness"

    def __init__(self, max_results: int = 3):
        self.max_results = max_results

    async def run(self, ctx: PipelineContext) -> None:
        # Only findings whose owner came from RESEARCH. An owner supplied by
        # source-work subsumption or the local catalogue was never looked up on
        # the open web, and asking whether that holder is currently litigating
        # spends a Search call on a question we did not raise — three of them
        # on the last live run, all asking whether Warner Bros. is suing people
        # about elements of its own film.
        subsumed = {
            e.id for e in ctx.state.elements if subsumed_by(e, ctx.state.source_work)
        }
        targets = [
            el
            for el in ctx.state.elements
            if el.id not in subsumed
            and not research_is_incomplete(ctx.state.research.get(el.id))
            and ctx.state.research[el.id].owner
        ]

        async def _one(el):
            owner = ctx.state.research[el.id].owner
            findings = await ctx.parallel.search(
                build_freshness_objective(owner, el.label),
                [el.label, f"{owner} lawsuit infringement enforcement film"],
                max_results=self.max_results,
            )
            return el, owner, findings

        for el, owner, findings in await asyncio.gather(*(_one(el) for el in targets)):
            if not findings:
                continue
            signals = to_signals(el.id, owner, findings)
            ctx.state.freshness[el.id] = signals
            material = material_count(signals)
            ctx.emit(
                {
                    "type": "freshness_checked",
                    "element_id": el.id,
                    "label": el.label,
                    "signals": len(signals),
                    "material": material,
                }
            )
