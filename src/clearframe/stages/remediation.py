"""Stage 5: draft remediation options, and price the cost of not taking them."""

from clearframe.knowledge import load_knowledge
from clearframe.liability import estimate
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

        # Both inputs exist by now — the licence price from research and the
        # fix price from the options above — so this is the first point at
        # which the other branch can be costed.
        knowledge = load_knowledge()
        ctx.state.liability = {
            el.id: estimate(
                el,
                ctx.state.research.get(el.id),
                ctx.state.remediation.get(el.id, []),
                knowledge,
            )
            for el in ctx.state.elements
        }
        stoppers = [
            e for e in ctx.state.liability.values()
            if e.injunction_risk == "documented"
        ]
        ctx.emit(
            {
                "type": "liability_estimated",
                "count": len(ctx.state.liability),
                "can_stop_a_release": len(stoppers),
            }
        )
