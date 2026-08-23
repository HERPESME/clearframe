"""Stage: independent identity corroboration.

Two detectors of different kinds, each speaking only where it has standing:

  Cloud Video Intelligence  closed-vocabulary logo/text catalogue -> marks
  Acoustic fingerprinting   spectral hashing over the audio      -> music

Sits between triage and research on purpose: research is the expensive,
consequential step, and sending it a disputed identity is how a dossier ends
up certifying the wrong rights holder.

Music is handled by `audio.apply_audio_identity` rather than by `assess`,
because for music the fingerprint is an identity SOURCE and not merely a
second opinion. When the video model offered only a description ("Upbeat
Electronic Music") there is no claim to corroborate — there is a hole, and the
fingerprint fills it. That promotion rewrites the element label, so it must
happen before research asks "who owns THIS".
"""

from clearframe.audio import apply_audio_identity
from clearframe.corroboration import assess
from clearframe.models import ClearanceCategory, IdentityVerdict
from clearframe.pipeline import PipelineContext


class CorroborateStage:
    name = "corroborate"

    async def run(self, ctx: PipelineContext) -> None:
        production = ctx.state.production

        hits = ctx.state.detector_hits
        if not ctx.state.detector_checked and ctx.corroborator is not None:
            hits = await ctx.corroborator.detect(
                production.footage_uri, production.duration_s
            )
            ctx.state.detector_hits = hits
            ctx.state.detector_checked = True
            ctx.emit({"type": "corroborator_hits", "count": len(hits)})

        matches = ctx.state.audio_matches
        if not matches and ctx.audio is not None:
            matches = await ctx.audio.identify(
                production.footage_uri, production.duration_s
            )
            ctx.state.audio_matches = matches

        if ctx.corroborator is None and ctx.audio is None:
            ctx.emit({"type": "corroboration_skipped"})
            return

        detector = ctx.corroborator.name if ctx.corroborator else "none"
        tally = {v.value: 0 for v in IdentityVerdict}
        promotions: list[dict] = []

        for index, el in enumerate(ctx.state.elements):
            if el.category is ClearanceCategory.MUSIC_SYNC:
                identity = apply_audio_identity(
                    el, matches, checked=ctx.state.audio_checked
                )
                if identity.corroboration is None:
                    continue
                result = identity.corroboration
                if identity.promoted:
                    was = el.label
                    ctx.state.elements[index] = el.model_copy(
                        update={"label": identity.label}
                    )
                    promotions.append(
                        {"element_id": el.id, "was": was, "now": identity.label}
                    )
            else:
                result = assess(el, hits, detector)

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

        for promotion in promotions:
            ctx.emit({"type": "identity_promoted", **promotion})

        ctx.emit({"type": "corroboration_done", **tally})
