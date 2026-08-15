"""Stage 3: concurrent rights research fan-out — one Parallel task per element.

A spend cap (`max_research`) bounds the fan-out on long footage: budget goes to
the most prominent elements first; the overflow surfaces honestly as
RESEARCH_INCOMPLETE instead of being silently dropped.
"""

import asyncio

from clearframe.integrations.parallel_client import _incomplete
from clearframe.pipeline import PipelineContext


class ResearchStage:
    name = "research"

    def __init__(self, max_research: int = 25):
        self.max_research = max_research

    async def run(self, ctx: PipelineContext) -> None:
        ranked = sorted(
            ctx.state.elements,
            key=lambda el: el.prominence.screen_time_s,
            reverse=True,
        )
        funded = ranked[: self.max_research]
        skipped = ranked[self.max_research :]

        results = await asyncio.gather(
            *(
                ctx.parallel.research(el, ctx.state.production.title)
                for el in funded
            )
        )
        research = {el.id: res for el, res in zip(funded, results)}
        for el in skipped:
            research[el.id] = _incomplete(el.id)
        ctx.state.research = research
