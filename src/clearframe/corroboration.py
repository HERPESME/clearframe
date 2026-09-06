"""Identity corroboration: does a second, independent detector agree WHAT this is?

The E&O auditor stage is Gemini reviewing Gemini. Two passes of the same model
share the same priors, so the auditor reliably catches *omissions* and
unreliably catches *misidentifications*. Misidentification is the more
dangerous failure: a wrong brand name routes rights research to the wrong
company and produces a dossier certifying a clearance that was never obtained.

So identity gets a second opinion from a detector of a different kind — a
closed-vocabulary logo/OCR detector that cannot invent a brand outside its
catalogue. The three verdicts drive real behaviour downstream:

  CORROBORATED   two independent detectors named the same thing -> research it
  SINGLE_SOURCE  only the generative pass saw it (murals, tattoos, artwork the
                 catalogue cannot know) -> research it, but say so in the dossier
  CONFLICTED     the detectors named DIFFERENT things -> never auto-research;
                 a human resolves identity first

Deterministic and reproducible, like the rest of the scoring path.
"""

from clearframe.matching import marks_match
from clearframe.overlay import boxes_overlap, locates
from clearframe.models import (
    ClearanceCategory,
    Corroboration,
    DetectedElement,
    DetectorHit,
    ElementType,
    IdentityVerdict,
    Prominence,
    TimeRange,
    TriagedElement,
)

# Categories a closed-vocabulary logo/text detector can legitimately speak to.
# A street mural or a tattoo is outside any brand catalogue, so silence there is
# not evidence of absence and must not read as a conflict.
CORROBORATABLE = {ClearanceCategory.TRADEMARK, ClearanceCategory.TEXT_ON_SCREEN}

MIN_CONFIDENCE = 0.5


def _overlaps(element: TriagedElement, hit: DetectorHit) -> bool:
    """Does the hit fall inside any window where the element appears?"""
    if hit.start_s is None or hit.end_s is None:
        return True  # untimed hit (still frame) — treat as in-scope
    return any(
        hit.start_s < r.end_s and hit.end_s > r.start_s for r in element.time_ranges
    )


# Element types a closed-vocabulary logo/text detector can speak to, before
# triage has assigned categories. The pre-triage mirror of CORROBORATABLE.
_CATALOGUED_TYPES = {ElementType.LOGO, ElementType.TEXT}

# What it takes to MINT a finding from one detector, as opposed to seconding
# one the video model already made. Stricter than MIN_CONFIDENCE on purpose:
# corroboration only ever adjusts a verdict on a finding that already exists,
# while this puts a new row in front of a reviewer. Every true hit observed so
# far clears it — the fixtures at 0.71/0.88/0.93, the live Bayer read at ~0.87
# — and the one documented spurious class sat above the 0.5 floor. Anchored on
# few observations, like the merge thresholds: re-check against new footage.
PROMOTE_MIN_CONFIDENCE = 0.7


def _about_one_object(detection: DetectedElement, hit: DetectorHit) -> bool:
    """Is the detector disputing this finding, or naming a different thing?

    Time cannot answer it. Two brands share a shot constantly — a trainer and a
    drink on one table — and treating every in-scope hit as spoken for would
    mean the catalogue can never contribute anything in a shot where the scan
    already found something, which is most shots.

    Place answers it, and this is the colocation rule `triage` already uses:
    the same instant AND the same part of the frame. Both rectangles have to
    LOCATE, since a box around the whole frame overlaps everything in the
    picture and is not evidence of anything.

    When neither side can be placed, the answer is "assume it is the same
    object" — the conservative direction here, because the cost of being wrong
    is a duplicate finding that then corroborates itself from the very hit that
    disputed the original.
    """
    boxes = [r.bbox for r in detection.time_ranges if locates(r.bbox)]
    if locates(detection.bbox):
        boxes.append(detection.bbox)
    if not locates(hit.bbox) or not boxes:
        return True
    return any(boxes_overlap(b, hit.bbox) for b in boxes)


def _consumed(detection: DetectedElement, hit: DetectorHit) -> bool:
    """Did this hit speak to this finding — agreeing, or disputing it?

    Both count. A conflicting hit is already doing work: it makes the element's
    identity CONFLICTED and blocks research on it. The demo's Kappa reading of
    the Adidas duffel is exactly that, and promoting it as well would put a
    second finding on screen for one bag and then let it corroborate itself
    from the hit that disputed the first.

    But disputing only means anything about ONE object — hence the place test.
    """
    if detection.element_type not in _CATALOGUED_TYPES:
        return False
    if hit.confidence < MIN_CONFIDENCE:
        return False
    if hit.start_s is None or hit.end_s is None:
        return True  # untimed hits are in scope everywhere, so never leftover
    shares_a_moment = any(
        hit.start_s < r.end_s and hit.end_s > r.start_s for r in detection.time_ranges
    )
    if not shares_a_moment:
        return False
    if marks_match(detection.label, hit.label):
        return True
    return _about_one_object(detection, hit)


def leftover_hits(
    detections: list[DetectedElement], hits: list[DetectorHit]
) -> list[DetectorHit]:
    """Catalogued marks that took no part in any finding's identity verdict.

    `assess` iterates ELEMENTS looking for hits that match them, so a hit
    matching nothing was discarded without a trace — no finding, no event, no
    line in the dossier. That is the interesting case: Video Intelligence reads
    a closed vocabulary, so it cannot invent a brand the way a generative pass
    can, and a high-confidence hit nobody reported is a mark every scan pass
    missed, already fetched and already paid for.
    """
    return [h for h in hits if not any(_consumed(d, h) for d in detections)]


def promote_hits(hits: list[DetectorHit], detector: str) -> list[DetectedElement]:
    """Turn leftover catalogue hits into findings the pipeline can route.

    Emitted before typing correction and triage so they travel the identical
    path as everything else — merged, categorised, routed, banded — rather than
    arriving as a privileged second class. `corroborate` will then mark them
    CORROBORATED from the same hits, which is worth stating plainly: that
    verdict reads "two detectors agreed" for a finding only one detector saw.
    The description carries its provenance so the reviewer is never misled
    about where it came from.
    """
    grouped: dict[str, list[DetectorHit]] = {}
    for h in hits:
        if h.confidence < PROMOTE_MIN_CONFIDENCE:
            continue
        if h.start_s is None or h.end_s is None:
            # No window means no appearance to draw, and an untimed hit is
            # never leftover anyway.
            continue
        grouped.setdefault(h.label, []).append(h)

    out: list[DetectedElement] = []
    for n, (label, group) in enumerate(sorted(grouped.items()), start=1):
        ranges = [
            TimeRange(
                start_s=h.start_s,
                # Video Intelligence can return a point segment; a TimeRange
                # needs a positive duration to be an appearance at all.
                end_s=max(h.end_s, h.start_s + 0.1),
                bbox=h.bbox,
            )
            for h in sorted(group, key=lambda h: h.start_s)
        ]
        best = max(group, key=lambda h: h.confidence)
        area = 0.0
        if best.bbox is not None:
            area = (best.bbox.xmax - best.bbox.xmin) * (best.bbox.ymax - best.bbox.ymin)
        out.append(
            DetectedElement(
                id=f"vi-{n}",
                label=label,
                element_type=ElementType.LOGO,
                description=(
                    f"Detected by {detector} logo recognition at "
                    f"{best.confidence:.0%} confidence; not reported by the "
                    "Gemini scan passes."
                ),
                time_ranges=ranges,
                bbox=best.bbox,
                prominence=Prominence(
                    screen_time_s=round(sum(r.duration_s for r in ranges), 2),
                    frame_coverage=round(area, 4),
                    # Measured where it can be, neutral where it cannot: a
                    # detector reports a rectangle, not what a shot is about.
                    centrality=0.5,
                    plot_integral=False,
                ),
            )
        )
    return out


def assess(
    element: TriagedElement, hits: list[DetectorHit], detector: str
) -> Corroboration:
    if element.category not in CORROBORATABLE:
        return Corroboration(
            element_id=element.id,
            verdict=IdentityVerdict.SINGLE_SOURCE,
            detector=detector,
            detected_label=None,
            confidence=0.0,
            note=(
                f"No closed-vocabulary detector covers {element.category.value}; "
                "identity rests on the video model alone."
            ),
        )

    in_scope = [
        h for h in hits if h.confidence >= MIN_CONFIDENCE and _overlaps(element, h)
    ]
    agreeing = [h for h in in_scope if marks_match(element.label, h.label)]

    if agreeing:
        best = max(agreeing, key=lambda h: h.confidence)
        return Corroboration(
            element_id=element.id,
            verdict=IdentityVerdict.CORROBORATED,
            detector=detector,
            detected_label=best.label,
            confidence=best.confidence,
            note=(
                f"{detector} independently identified '{best.label}' in the same window "
                f"at {best.confidence:.0%} confidence."
            ),
        )

    if in_scope:
        best = max(in_scope, key=lambda h: h.confidence)
        others = ", ".join(sorted({h.label for h in in_scope}))
        return Corroboration(
            element_id=element.id,
            verdict=IdentityVerdict.CONFLICTED,
            detector=detector,
            detected_label=best.label,
            confidence=best.confidence,
            note=(
                f"Identity dispute: the video model read '{element.label}' but {detector} "
                f"read '{others}' in the same window. Resolve before researching — "
                "researching the wrong rights holder produces a false clearance."
            ),
        )

    return Corroboration(
        element_id=element.id,
        verdict=IdentityVerdict.SINGLE_SOURCE,
        detector=detector,
        detected_label=None,
        confidence=0.0,
        note=(
            f"{detector} saw no catalogued mark in this window. Not a contradiction — "
            "the mark may simply be outside its vocabulary — but identity is unconfirmed."
        ),
    )


def blocks_research(corroboration: Corroboration | None) -> bool:
    """CONFLICTED identity must not be researched automatically."""
    return corroboration is not None and corroboration.verdict is IdentityVerdict.CONFLICTED
