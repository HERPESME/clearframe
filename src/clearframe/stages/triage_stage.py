"""Stage 2: map detections to clearance categories and merge duplicates.

Then take the cast out. A face the scan attributed to a named performer is not
a third-party finding — the production engaged them — and leaving them in cost
a live search for an agent contact each, plus a full-frame rectangle on the
player. Everyone the scan could not name stays, because those releases are
real. See `cast.py`.
"""

from clearframe.cast import partition
from clearframe.pipeline import PipelineContext
from clearframe.triage import triage


class TriageStage:
    name = "triage"

    async def run(self, ctx: PipelineContext) -> None:
        findings, credits = partition(triage(ctx.state.detections))
        ctx.state.elements = findings
        ctx.state.cast = credits
