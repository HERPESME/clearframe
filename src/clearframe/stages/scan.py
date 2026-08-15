"""Stage 1: Gemini watches the footage; a second auditor pass catches misses."""

from clearframe.pipeline import PipelineContext


class ScanStage:
    name = "scan"

    async def run(self, ctx: PipelineContext) -> None:
        production = ctx.state.production
        result = await ctx.gemini.scan(production.footage_uri, production.duration_s)
        ctx.emit(
            {"type": "scan_found", "count": len(result.detections)}
        )

        audit = await ctx.gemini.audit_scan(
            production.footage_uri,
            production.duration_s,
            [d.label for d in result.detections],
        )
        ctx.emit({"type": "audit_found", "count": len(audit.detections)})

        ctx.state.detections = result.detections + audit.detections
        ctx.state.unscanned_ranges = result.unscanned_ranges + audit.unscanned_ranges
