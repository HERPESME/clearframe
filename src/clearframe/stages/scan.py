"""Stage 1: Gemini watches the footage and reports clearable elements."""

from clearframe.pipeline import PipelineContext


class ScanStage:
    name = "scan"

    async def run(self, ctx: PipelineContext) -> None:
        result = await ctx.gemini.scan(
            ctx.state.production.footage_uri, ctx.state.production.duration_s
        )
        ctx.state.detections = result.detections
        ctx.state.unscanned_ranges = result.unscanned_ranges
