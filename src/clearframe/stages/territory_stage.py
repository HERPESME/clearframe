"""Stage: per-territory risk banding for the release plan."""

from clearframe.pipeline import PipelineContext
from clearframe.territory import assess_all, defences_for, governing_regime, worst_band


class TerritoryStage:
    name = "territory"

    async def run(self, ctx: PipelineContext) -> None:
        territories = ctx.state.production.release_territories
        if not territories:
            ctx.emit({"type": "territory_skipped"})
            return
        ctx.state.territories = list(territories)
        ctx.state.territory_risk = assess_all(
            ctx.state.elements, ctx.state.risk, territories
        )
        # What defence exists WHERE. A skit maker who learns parody is statutory
        # in the UK and simply absent in India has been told something no single
        # global answer could convey.
        ctx.state.defences = {
            el.id: [
                d.model_dump(mode="json")
                for t in territories
                for d in defences_for(el, t)
            ]
            for el in ctx.state.elements
        }
        missing = sum(
            1
            for rows in ctx.state.defences.values()
            for d in rows
            if not d["available"]
        )
        ctx.emit(
            {
                "type": "defences_mapped",
                "territories": len(territories),
                "unavailable": missing,
                "regimes": sorted(
                    {
                        governing_regime(el.category, t)
                        for el in ctx.state.elements
                        for t in territories
                    }
                ),
            }
        )

        divergent = sum(
            1
            for el in ctx.state.elements
            if worst_band(ctx.state.territory_risk[el.id]) != ctx.state.risk[el.id].band
        )
        ctx.emit(
            {
                "type": "territory_assessed",
                "territories": len(territories),
                "divergent": divergent,
            }
        )
