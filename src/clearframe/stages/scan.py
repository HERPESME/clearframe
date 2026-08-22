"""Stage 1: three independent observers run concurrently over the same footage.

Gemini watches (plus a second auditor pass that catches misses), Cloud Video
Intelligence reads catalogued logos, and acoustic fingerprinting listens. None
of the three depends on another's output, so running them in sequence was
paying their latencies added together instead of the slowest one.

The logo and audio results are stashed on the state; `corroborate` consumes
them. That stage still works if this prefetch is absent — it falls back to
calling the detector itself — so the two stages stay independently testable
and resumable.
"""

import asyncio
import logging

from clearframe.integrations.gemini_client import build_scan_context
from clearframe.pipeline import PipelineContext

log = logging.getLogger("clearframe.scan")


class ScanStage:
    name = "scan"

    async def run(self, ctx: PipelineContext) -> None:
        production = ctx.state.production

        # The `script` stage has already run, so what the screenplay named is
        # available to prime the scan. Gemini receives the whole mp4 either way
        # — both tracks, natively — but until now it knew nothing ABOUT the
        # production it was watching.
        scan_context = build_scan_context(production, ctx.state.script_mentions)

        async def _watch():
            result = await ctx.gemini.scan(
                production.footage_uri, production.duration_s, scan_context
            )
            ctx.emit({"type": "scan_found", "count": len(result.detections)})
            audit = await ctx.gemini.audit_scan(
                production.footage_uri,
                production.duration_s,
                [d.label for d in result.detections],
                scan_context,
            )
            ctx.emit({"type": "audit_found", "count": len(audit.detections)})
            return result, audit

        async def _listen():
            if ctx.audio is None:
                return []
            ctx.emit({"type": "fingerprint_start"})
            matches = await ctx.audio.identify(
                production.footage_uri, production.duration_s
            )
            ctx.emit(
                {
                    "type": "fingerprint_done",
                    "count": len(matches),
                    "titles": [m.title for m in matches],
                }
            )
            return matches

        async def _catalogue():
            if ctx.corroborator is None:
                return []
            hits = await ctx.corroborator.detect(
                production.footage_uri, production.duration_s
            )
            ctx.emit({"type": "corroborator_hits", "count": len(hits)})
            return hits

        watched, matches, hits = await asyncio.gather(
            _watch(), _listen(), _catalogue(), return_exceptions=True
        )

        if isinstance(watched, BaseException):
            raise watched  # the scan is load-bearing; the other two are not
        result, audit = watched

        ctx.state.detections = result.detections + audit.detections
        ctx.state.unscanned_ranges = result.unscanned_ranges + audit.unscanned_ranges
        # Not clearance items. Nobody owns a delivery label with your address
        # on it, which is exactly why no clearance tool looks for one.
        ctx.state.exposures = result.exposures + audit.exposures
        if ctx.state.exposures:
            ctx.emit({"type": "exposures_found", "count": len(ctx.state.exposures)})
        ctx.state.audio_matches = _or_empty(matches, "audio fingerprinting")
        ctx.state.audio_checked = getattr(ctx.audio, "available", True)
        if not ctx.state.audio_checked:
            ctx.emit({"type": "fingerprint_unavailable"})
        ctx.state.detector_hits = _or_empty(hits, "logo corroboration")


def _or_empty(value, what: str) -> list:
    """A failed second opinion degrades identity; it never fails the run."""
    if isinstance(value, BaseException):
        log.warning("%s unavailable (%s)", what, value)
        return []
    return value
