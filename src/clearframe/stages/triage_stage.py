"""Stage 2: map detections to clearance categories and merge duplicates."""

from clearframe.pipeline import PipelineContext
from clearframe.triage import triage


class TriageStage:
    name = "triage"

    async def run(self, ctx: PipelineContext) -> None:
        ctx.state.elements = triage(ctx.state.detections)
