"""Stage 3: concurrent rights research fan-out — one Parallel task per element."""

import asyncio

from clearframe.pipeline import PipelineContext


class ResearchStage:
    name = "research"

    async def run(self, ctx: PipelineContext) -> None:
        elements = ctx.state.elements
        results = await asyncio.gather(
            *(
                ctx.parallel.research(el, ctx.state.production.title)
                for el in elements
            )
        )
        ctx.state.research = {el.id: res for el, res in zip(elements, results)}
