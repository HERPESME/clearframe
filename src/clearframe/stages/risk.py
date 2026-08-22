"""Stage 4: deterministic risk scoring per element."""

from clearframe.pipeline import PipelineContext
from clearframe.scoring import score_element


class RiskStage:
    name = "risk"

    async def run(self, ctx: PipelineContext) -> None:
        use_context = ctx.state.production.use_context
        ctx.state.risk = {
            el.id: score_element(el, ctx.state.research.get(el.id), use_context)
            for el in ctx.state.elements
        }
