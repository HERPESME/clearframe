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
from clearframe.models import DetectedElement
from clearframe.pipeline import PipelineContext
from clearframe.matching import labels_match
from clearframe.sourcework import corrected_types
from clearframe.timeline import timing_is_reliable

log = logging.getLogger("clearframe.scan")



def merge_passes(
    scan: list[DetectedElement], audit: list[DetectedElement]
) -> list[DetectedElement]:
    """Concatenate the two passes, guaranteeing every id is distinct.

    Both calls are independent and both number their findings from 1, so the
    moment the auditor catches something the first pass missed — its entire
    purpose — two unrelated findings share an id. Every downstream dict is
    keyed by that id, so one finding silently inherits the other's route,
    ownership and risk. On a clip of The Hangover Part II, "Stu's Face Tattoo"
    and a "National" car-rental logo were both id "1" and the tattoo was
    reported with the car-rental company's analysis.

    The first pass keeps its ids so an existing state or a UI deep-link does
    not shift underneath it; only a later collision is renamed. Renaming
    happens BEFORE triage, which dedupes by (type, label) rather than by id, so
    a genuine second sighting of the same thing still merges.
    """
    out: list[DetectedElement] = []
    seen: set[str] = set()
    for d in [*scan, *audit]:
        eid = d.id
        if eid in seen:
            n = 2
            while f"{d.id}-{n}" in seen:
                n += 1
            eid = f"{d.id}-{n}"
            d = d.model_copy(update={"id": eid})
        seen.add(eid)
        out.append(d)
    return out


def _with_timing_verdict(
    detection: DetectedElement, production
) -> DetectedElement:
    """Mark a detection whose timecodes cannot be what they claim.

    Gemini returned one element of eight with appearances of 20-30ms in a 24fps
    clip while reporting 10 seconds of screen time for the same element. The
    finding was real and important — it was the tattoo from Whitmill v. Warner
    Bros. — but no human can pause inside a 20ms window, so it had timecodes in
    the list and no box anywhere in the player.

    The finding is kept. Only its timing is disowned.
    """
    ok, reason = timing_is_reliable(
        detection, production.duration_s, production.fps
    )
    if ok:
        return detection
    log.warning("Unusable timecodes for %r: %s", detection.label, reason)
    return detection.model_copy(
        update={"timing_reliable": False, "timing_note": reason}
    )


# How many independent Gemini passes to run before the auditor. Two, because a
# single pass was measured at about 60% recall: three identical baseline runs
# over one 41.5s clip found 15 distinct things between them, a mean of 9.0
# each, with only 3 present in all three and 7 in exactly one.
#
# Recall is this product's whole safety claim, and no video parameter improved
# it — media_resolution is rejected by the model outright, and fps=2 was
# strictly worse. Another pass is what works, and running it concurrently makes
# it nearly free in wall clock, which matters because anything that costs
# minutes eventually gets cut.
SCAN_PASSES = 2


async def gather_detections(
    gemini, footage_uri: str, duration_s: float, context: str, passes: int = SCAN_PASSES
):
    """Independent passes concurrently, then the auditor primed on their union.

    The auditor's job is to catch what was missed, so it should be told
    everything already found — not just one pass's share of it. Returns the
    merged detections and the ScanResult of the first pass, which carries the
    document-level fields (source_work, unscanned_ranges, exposures).
    """
    results = await asyncio.gather(
        *(gemini.scan(footage_uri, duration_s, context) for _ in range(max(1, passes)))
    )

    seen: list[str] = []
    for r in results:
        for d in r.detections:
            if not any(labels_match(d.label, s) for s in seen):
                seen.append(d.label)

    audit = await gemini.audit_scan(footage_uri, duration_s, seen, context)

    merged: list[DetectedElement] = []
    for r in [*results, audit]:
        merged = merge_passes(merged, r.detections) if merged else list(r.detections)
    return merge_passes(merged, []), results[0], audit

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
            merged, result, audit = await gather_detections(
                ctx.gemini,
                production.footage_uri,
                production.duration_s,
                scan_context,
            )
            ctx.emit({"type": "scan_found", "count": len(result.detections)})
            ctx.emit({"type": "audit_found", "count": len(audit.detections)})
            return merged, result, audit

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
        merged, result, audit = watched

        # Typing is corrected BEFORE triage, which is what turns an element
        # type into a clearance category — a real actor needs a release, not a
        # copyright licence.
        work = result.source_work or audit.source_work
        ctx.state.detections = [
            _with_timing_verdict(d, production)
            for d in corrected_types(merged, work)
        ]
        ctx.state.unscanned_ranges = result.unscanned_ranges + audit.unscanned_ranges
        # Not clearance items. Nobody owns a delivery label with your address
        # on it, which is exactly why no clearance tool looks for one.
        ctx.state.exposures = result.exposures + audit.exposures
        # If the footage IS an existing work, that one fact reframes most of
        # the findings below it.
        ctx.state.source_work = result.source_work or audit.source_work
        if ctx.state.source_work:
            w = ctx.state.source_work
            ctx.emit(
                {
                    "type": "source_work_identified",
                    "title": w.title,
                    "rights_holder": w.rights_holder,
                    "confidence": w.confidence,
                }
            )
        if ctx.state.exposures:
            ctx.emit({"type": "exposures_found", "count": len(ctx.state.exposures)})
        ctx.state.audio_matches = _or_empty(matches, "audio fingerprinting")
        ctx.state.audio_checked = getattr(ctx.audio, "available", True)
        if not ctx.state.audio_checked:
            ctx.emit({"type": "fingerprint_unavailable"})
        ctx.state.detector_hits = _or_empty(hits, "logo corroboration")
        # Record that the detector was ASKED. Without this, an empty prefetch
        # is indistinguishable from no prefetch and `corroborate` pays Video
        # Intelligence's full latency a second time for the same empty answer.
        ctx.state.detector_checked = not isinstance(hits, BaseException)


def _or_empty(value, what: str) -> list:
    """A failed second opinion degrades identity; it never fails the run."""
    if isinstance(value, BaseException):
        log.warning("%s unavailable (%s)", what, value)
        return []
    return value
