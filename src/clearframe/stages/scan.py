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

from clearframe.corroboration import leftover_hits, promote_hits
from clearframe.integrations.gemini_client import build_scan_context
from clearframe.models import DetectedElement, ExposureFinding, SourceWork, TimeRange
from clearframe.pipeline import PipelineContext
from clearframe.matching import labels_match
from clearframe.sourcework import corrected_types
from clearframe.timeline import clamp_to_footage, timing_is_reliable
from clearframe.triage import union_spans

log = logging.getLogger("clearframe.scan")


def fold_unscanned(results, audit) -> list[TimeRange]:
    """What no pass could analyse, said once.

    Concatenated, two passes reporting the same unmeasurable window reported
    it twice — overstating the gap in the one column whose whole job is to be
    honest about coverage.
    """
    ranges = [r for res in [*results, audit] for r in res.unscanned_ranges]
    return union_spans(ranges)


def _same_exposure(a: ExposureFinding, b: ExposureFinding) -> bool:
    """Two passes describing one thing, rather than two things.

    Deliberately conservative, and in the same direction as triage but for the
    opposite reason. A duplicate exposure is a second warning about one child;
    a wrongly merged one is a child nobody is warned about. So all three of
    kind, time and wording have to agree — a second child in a later shot
    stays a second finding even when described identically.
    """
    if a.kind is not b.kind:
        return False
    overlaps = any(
        r.start_s < q.end_s and q.start_s < r.end_s
        for r in a.time_ranges
        for q in b.time_ranges
    )
    return overlaps and labels_match(a.description, b.description)


def dedupe_exposures(found: list[ExposureFinding]) -> list[ExposureFinding]:
    """One finding per thing on screen, however many passes saw it.

    Exposures are the one class with no second detector anywhere — no
    catalogue, no fingerprint, no corroborator — so every pass's contribution
    is kept. That also means the same minor arrives once per pass, and both
    passes number their exposures from 1, so ids collide exactly the way
    detections do.
    """
    groups: list[list[ExposureFinding]] = []
    for e in found:
        for g in groups:
            if _same_exposure(g[0], e):
                g.append(e)
                break
        else:
            groups.append([e])

    out: list[ExposureFinding] = []
    used: set[str] = set()
    for group in groups:
        first = group[0]
        richest = max(group, key=lambda e: len(e.description or ""))
        eid = first.id
        n = 2
        while eid in used:
            eid = f"{first.id}-{n}"
            n += 1
        used.add(eid)
        out.append(
            first.model_copy(
                update={
                    "id": eid,
                    "description": richest.description,
                    "time_ranges": union_spans(
                        [r for e in group for r in e.time_ranges]
                    ),
                    "bbox": next((e.bbox for e in group if e.bbox is not None), first.bbox),
                }
            )
        )
    return out


# Confidence gates subsumption in `sourcework`, so it is what ranks a claim.
_CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}


def best_source_work(candidates) -> SourceWork | None:
    """The most confident identification, not the first pass's.

    `sourcework` only subsumes findings on a high or medium confidence claim,
    so a low-confidence guess from pass one shadowing a high-confidence
    identification from pass two would quietly disable the mechanism — and,
    through `corrected_types`, keep routing drawn characters as real people
    who need releases. Ties keep pass order, so a run stays reproducible.
    """
    ranked = [w for w in candidates if w is not None]
    if not ranked:
        return None
    return max(
        enumerate(ranked),
        key=lambda pair: (_CONFIDENCE_ORDER.get(pair[1].confidence, 0), -pair[0]),
    )[1]



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

    First, though, an end time that overshoots the last frame by a rounding
    margin is pulled back onto it. A live run lost `Bangkok Hotel Room` — a
    finding spanning the whole scene — because the scan said it ended at 41.60s
    in a 41.50s clip, and disowning cost it its timeline and every rectangle it
    had over a tenth of a second.
    """
    detection = clamp_to_footage(detection, production.duration_s)
    ok, reason = timing_is_reliable(
        detection, production.duration_s, production.fps
    )
    if ok:
        return detection
    log.warning("Unusable timecodes for %r: %s", detection.label, reason)
    return detection.model_copy(
        update={"timing_reliable": False, "timing_note": reason}
    )


# How many independent Gemini passes to run before the auditor. Three, because
# a single pass was measured at about 60% recall: three identical baseline runs
# over one 41.5s clip found 15 distinct things between them, a mean of 9.0
# each, with only 3 present in all three and 7 in exactly one. Those three runs
# ARE the evidence for three — between them they saw everything the measurement
# found, where any one of them saw about nine of fifteen.
#
# Recall is this product's whole safety claim, and no video parameter improved
# it — media_resolution is rejected by the model outright, and fps=2 was
# strictly worse. Another pass is what works, and running it concurrently makes
# it nearly free in wall clock, which matters because anything that costs
# minutes eventually gets cut. In money it is about $0.02 per minute of footage
# per pass, so a 45-second clip pays roughly a cent and a half for the third.
SCAN_PASSES = 3


def _configured_passes() -> int:
    """Read at call time so a test — or an operator — can change it.

    Env rather than a config field, following PREGROUND_MAX_FRAMES: the right
    number depends on how much recall the run is worth paying for, which is an
    operational choice rather than part of the analysis contract.
    """
    import os

    raw = os.environ.get("CLEARFRAME_SCAN_PASSES")
    if raw is None:
        return SCAN_PASSES
    try:
        return max(1, int(raw))
    except ValueError:
        log.warning("ignoring unusable CLEARFRAME_SCAN_PASSES=%r", raw)
        return SCAN_PASSES


async def gather_detections(
    gemini, footage_uri: str, duration_s: float, context: str, passes: int | None = None
):
    """Independent passes concurrently, then the auditor primed on their union.

    The auditor's job is to catch what was missed, so it should be told
    everything already found — not just one pass's share of it.

    Returns the merged detections, EVERY successful pass's result, and the
    audit. All of them, because the document-level fields — exposures,
    source_work, unscanned_ranges — used to be read off `results[0]` alone: the
    extra passes contributed their findings and had everything else they saw
    discarded, on the one class of finding with no second detector anywhere.

    A pass that fails does not fail the run. The extra passes exist to raise
    recall, so losing one should cost recall and nothing else — but the gather
    had no `return_exceptions`, so one transient transport error took down a
    scan the other passes had already completed. Only a total failure raises.
    """
    wanted = max(1, passes if passes is not None else _configured_passes())
    settled = await asyncio.gather(
        *(gemini.scan(footage_uri, duration_s, context) for _ in range(wanted)),
        return_exceptions=True,
    )
    results = [r for r in settled if not isinstance(r, BaseException)]
    for failure in (r for r in settled if isinstance(r, BaseException)):
        log.warning("a scan pass failed and was dropped: %s", failure)
    if not results:
        raise next(r for r in settled if isinstance(r, BaseException))

    seen: list[str] = []
    for r in results:
        for d in r.detections:
            if not any(labels_match(d.label, s) for s in seen):
                seen.append(d.label)

    audit = await gemini.audit_scan(footage_uri, duration_s, seen, context)

    merged: list[DetectedElement] = []
    for r in [*results, audit]:
        merged = merge_passes(merged, r.detections) if merged else list(r.detections)
    return merge_passes(merged, []), results, audit

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
            merged, results, audit = await gather_detections(
                ctx.gemini,
                production.footage_uri,
                production.duration_s,
                scan_context,
            )
            # What the SCAN found, not what one pass of it found. This reported
            # `results[0]` while the merged set was already bigger, so Mission
            # Control showed a single pass's count as the scan's.
            ctx.emit(
                {
                    "type": "scan_found",
                    "count": len(merged),
                    "passes": len(results),
                }
            )
            ctx.emit({"type": "audit_found", "count": len(audit.detections)})
            return merged, results, audit

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
        merged, results, audit = watched

        # Every pass's document-level fields, not just the first one's. The
        # extra passes exist because one sees about 60% of what is there, and
        # reading these off `results[0]` threw away everything they saw beyond
        # their detections.
        work = best_source_work([r.source_work for r in results] + [audit.source_work])

        # A catalogued mark every pass missed is a finding, not a discarded
        # hit. Video Intelligence reads a closed vocabulary, so unlike the
        # generative passes it cannot name a brand that does not exist — which
        # makes a high-confidence hit that spoke to no finding the one piece of
        # free recall in the system, already fetched and already paid for.
        #
        # Added HERE, before typing correction and triage, so it travels the
        # identical path as everything else: merged, categorised, routed,
        # banded. A finding that skipped that path would be a second unaudited
        # detector, which is the objection grounding answers by refusing to
        # detect at all.
        catalogue_hits = _or_empty(hits, "logo corroboration")
        promoted = promote_hits(
            leftover_hits(merged, catalogue_hits), "Cloud Video Intelligence"
        )
        if promoted:
            log.info(
                "promoting %d catalogued mark(s) no scan pass reported: %s",
                len(promoted), ", ".join(p.label for p in promoted),
            )
            ctx.emit(
                {
                    "type": "detector_found",
                    "count": len(promoted),
                    "labels": [p.label for p in promoted],
                }
            )
            merged = merge_passes(merged, promoted)

        # Typing is corrected BEFORE triage, which is what turns an element
        # type into a clearance category — a real actor needs a release, not a
        # copyright licence.
        ctx.state.detections = [
            _with_timing_verdict(d, production)
            for d in corrected_types(merged, work)
        ]
        ctx.state.unscanned_ranges = fold_unscanned(results, audit)
        # Not clearance items. Nobody owns a delivery label with your address
        # on it, which is exactly why no clearance tool looks for one — and why
        # this is the one class with no second detector to fall back on, so
        # every pass's sightings are kept and merged rather than one pass's
        # taken and the rest dropped.
        ctx.state.exposures = dedupe_exposures(
            [e for r in results for e in r.exposures] + list(audit.exposures)
        )
        # If the footage IS an existing work, that one fact reframes most of
        # the findings below it.
        ctx.state.source_work = work
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
        ctx.state.detector_hits = catalogue_hits
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
