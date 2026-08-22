"""Stage: independent identity corroboration.

Runs a closed-vocabulary logo/text detector over the same footage and compares
what it names against what the video model named. Sits between triage and
research on purpose: research is the expensive, consequential step, and
sending it a disputed identity is how a dossier ends up certifying the wrong
rights holder.
"""

from clearframe.corroboration import assess
from clearframe.models import IdentityVerdict
from clearframe.pipeline import PipelineContext


class CorroborateStage:
    name = "corroborate"

    async def run(self, ctx: PipelineContext) -> None:
        if ctx.corroborator is None:
            ctx.emit({"type": "corroboration_skipped"})
            return
        production = ctx.state.production
        hits = await ctx.corroborator.detect(
            production.footage_uri, production.duration_s
        )
        ctx.emit({"type": "corroborator_hits", "count": len(hits)})

        tally = {v.value: 0 for v in IdentityVerdict}
        for el in ctx.state.elements:
            result = assess(el, hits, ctx.corroborator.name)
            ctx.state.corroboration[el.id] = result
            tally[result.verdict.value] += 1
            if result.verdict is IdentityVerdict.CONFLICTED:
                ctx.emit(
                    {
                        "type": "identity_conflict",
                        "element_id": el.id,
                        "label": el.label,
                        "detected_label": result.detected_label,
                    }
                )
        ctx.emit({"type": "corroboration_done", **tally})
