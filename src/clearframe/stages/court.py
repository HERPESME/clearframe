"""Stage 6: the Clearance Court argues contested findings (MEDIUM+ bands).

Opinions attach adversarial legal reasoning with precedent; they never modify
the deterministic risk score, and a failed case never blocks the pipeline.
"""

import asyncio

from clearframe.integrations.court_client import CourtCase
from clearframe.models import RiskBand
from clearframe.pipeline import PipelineContext

CONTESTED_BANDS = {RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL}


class CourtStage:
    name = "court"

    async def run(self, ctx: PipelineContext) -> None:
        cases = []
        for el in ctx.state.elements:
            risk = ctx.state.risk[el.id]
            if risk.band not in CONTESTED_BANDS:
                continue
            ctx.emit({"type": "case_opened", "element_id": el.id, "label": el.label})
            cases.append(
                CourtCase(
                    element=el,
                    research=ctx.state.research.get(el.id),
                    risk=risk,
                    production=ctx.state.production,
                )
            )

        # Bounded. Each case is three Gemini calls — counsel, advocate, judge —
        # so an unbounded gather over every contested finding put twenty cases
        # times three calls in flight at once, competing with the background
        # box measuring for the same quota.
        gate = asyncio.Semaphore(4)

        async def _try(case):
            async with gate:
                return await ctx.court.try_case(case)

        opinions = await asyncio.gather(*(_try(c) for c in cases))
        for case, opinion in zip(cases, opinions):
            if opinion is None:
                continue
            ctx.state.court[case.element.id] = opinion
            ctx.emit(
                {
                    "type": "case_ruled",
                    "element_id": case.element.id,
                    "label": case.element.label,
                    "holding": opinion.holding,
                }
            )
