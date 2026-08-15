"""Stage 5: draft remediation options for every element."""

from clearframe.pipeline import PipelineContext
from clearframe.remediation import draft_options


class RemediationStage:
    name = "remediation"

    async def run(self, ctx: PipelineContext) -> None:
        ctx.state.remediation = {
            el.id: draft_options(
                el,
                ctx.state.research[el.id],
                ctx.state.risk[el.id],
                ctx.state.production,
            )
            for el in ctx.state.elements
        }
