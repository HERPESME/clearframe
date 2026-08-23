"""Rule-based clearance triage and cross-shot duplicate merging."""

from clearframe.models import (
    ClearanceCategory,
    DetectedElement,
    ElementType,
    Prominence,
    TimeRange,
    TriagedElement,
)

CATEGORY_RULES: dict[ElementType, ClearanceCategory] = {
    ElementType.LOGO: ClearanceCategory.TRADEMARK,
    ElementType.ARTWORK: ClearanceCategory.COPYRIGHT_ART,
    ElementType.MUSIC: ClearanceCategory.MUSIC_SYNC,
    ElementType.FACE: ClearanceCategory.RIGHT_OF_PUBLICITY,
    ElementType.CHARACTER: ClearanceCategory.COPYRIGHT_ART,
    ElementType.TATTOO: ClearanceCategory.COPYRIGHT_ART,
    ElementType.LOCATION: ClearanceCategory.LOCATION,
    ElementType.TEXT: ClearanceCategory.TEXT_ON_SCREEN,
}


def _union(ranges: list[TimeRange]) -> list[TimeRange]:
    """Overlapping sightings of one thing are one sighting.

    Two independent scan passes both report the whole element, so the same
    ten seconds arrives twice. Concatenating them made a 10s tattoo read as
    20s, and prominence drives the risk score.
    """
    out: list[TimeRange] = []
    for r in sorted(ranges, key=lambda r: (r.start_s, r.end_s)):
        if out and r.start_s <= out[-1].end_s:
            if r.end_s > out[-1].end_s:
                # Keep the earlier box: it was measured, and a merged range
                # spans more than either box was drawn for.
                out[-1] = out[-1].model_copy(update={"end_s": r.end_s})
            continue
        out.append(r)
    return out


def _overlaps(a: DetectedElement, b: DetectedElement) -> bool:
    return any(
        r.start_s < q.end_s and q.start_s < r.end_s
        for r in a.time_ranges
        for q in b.time_ranges
    )


def _screen_time(group: list[DetectedElement], ranges: list[TimeRange]) -> float:
    """Measured from the merged ranges, not summed from each pass's claim.

    Summing was right while the only merge was scan + auditor finding DIFFERENT
    appearances. Two independent passes both report the whole element, so the
    same ten seconds arrives twice and a 10s tattoo read as 20s — and
    prominence drives the risk score.

    The union of the ranges answers it directly: overlapping sightings count
    once, separate ones still add up. It is also the more honest number, since
    an element cannot be on screen longer than the timecodes saying where it
    is. Every element in the demo fixture already agrees with its own ranges to
    the decimal, and seven of eight did on the last live clip; the eighth was
    the tattoo whose timecodes `timeline.py` disowns.

    Falls back to the largest claim when there are no usable ranges at all.
    """
    measured = sum(r.duration_s for r in ranges)
    return measured or max(d.prominence.screen_time_s for d in group)


def _merge(group: list[DetectedElement]) -> DetectedElement:
    first = group[0]
    ranges = _union([r for d in group for r in d.time_ranges])
    # Screen time comes from the ranges rather than from the sum of what each
    # pass claimed: an element cannot be on screen longer than the timecodes
    # saying where it is.
    # Copied from `first` rather than rebuilt field by field. Rebuilding
    # silently dropped everything the constructor did not name — siting,
    # depiction, bbox, at_s, timing_reliable — which stayed invisible while
    # merges were rare and became routine the moment a second independent scan
    # pass was added. The demo mural lost its siting and Germany stopped
    # applying freedom of panorama to the one element written for it.
    richer = {
        # Prefer whichever pass actually reported these; a default is not an
        # observation, and the first pass is not authoritative over the second.
        "siting": next(
            (d.siting for d in group if d.siting != "unknown"), first.siting
        ),
        "depiction": next(
            (d.depiction for d in group if d.depiction is not None), first.depiction
        ),
        "bbox": next((d.bbox for d in group if d.bbox is not None), first.bbox),
        "at_s": next((d.at_s for d in group if d.at_s is not None), first.at_s),
        # Disowned timing is sticky: one pass proving the timecodes impossible
        # is not cancelled by another pass being silent about it.
        "timing_reliable": all(d.timing_reliable for d in group),
        "timing_note": next((d.timing_note for d in group if d.timing_note), ""),
    }
    return first.model_copy(
        update={
            **richer,
            "time_ranges": ranges,
            "prominence": Prominence(
                screen_time_s=_screen_time(group, ranges),
                frame_coverage=max(d.prominence.frame_coverage for d in group),
                centrality=max(d.prominence.centrality for d in group),
                plot_integral=any(d.prominence.plot_integral for d in group),
            ),
        }
    )


def triage(detections: list[DetectedElement]) -> list[TriagedElement]:
    groups: dict[tuple[ElementType, str], list[DetectedElement]] = {}
    for d in detections:
        groups.setdefault((d.element_type, d.label.casefold().strip()), []).append(d)

    out: list[TriagedElement] = []
    for group in groups.values():
        merged = _merge(group) if len(group) > 1 else group[0]
        out.append(
            TriagedElement(**merged.model_dump(), category=CATEGORY_RULES[merged.element_type])
        )
    return out
