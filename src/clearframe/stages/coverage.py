"""Stage: check every finding against the clearances we already hold.

Runs after territory banding because coverage is territory-dependent: a US-only
sync licence is a gap only once you know the film ships to France.
"""

from datetime import datetime, timezone

from clearframe.licensing import assess_all, summarise
from clearframe.pipeline import PipelineContext


class CoverageStage:
    name = "coverage"

    def __init__(self, as_of: str | None = None):
        self.as_of = as_of

    async def run(self, ctx: PipelineContext) -> None:
        if not ctx.licences:
            ctx.emit({"type": "coverage_skipped", "reason": "no rights ledger on file"})
            return
        as_of = self.as_of or datetime.now(timezone.utc).isoformat()
        production = ctx.state.production
        ctx.state.coverage = assess_all(
            ctx.state.elements,
            ctx.state.research,
            ctx.licences,
            production.release_territories,
            production.distribution,
            as_of,
        )
        counts = summarise(ctx.state.coverage)
        for el in ctx.state.elements:
            cov = ctx.state.coverage[el.id]
            if cov.gaps:
                ctx.emit(
                    {
                        "type": "coverage_gap",
                        "element_id": el.id,
                        "label": el.label,
                        "licence_id": cov.licence_id,
                        "gaps": cov.gaps,
                    }
                )
        ctx.emit({"type": "coverage_checked", "ledger_size": len(ctx.licences), **counts})
