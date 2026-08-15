"""Stage: script-vs-screen drift — flag what appeared that was never scripted."""

from clearframe.drift import compute_drift
from clearframe.pipeline import PipelineContext


class DriftStage:
    name = "drift"

    async def run(self, ctx: PipelineContext) -> None:
        if not ctx.state.script_mentions:
            ctx.emit({"type": "drift_computed", "unscripted": 0, "skipped": True})
            return
        drift = compute_drift(ctx.state.script_mentions, ctx.state.elements)
        ctx.state.drift = drift
        ctx.emit(
            {
                "type": "drift_computed",
                "unscripted": len(drift.unscripted_element_ids),
                "scripted_not_seen": len(drift.scripted_not_seen),
            }
        )
