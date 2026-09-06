"""Rule-based clearance triage and cross-shot duplicate merging."""

from clearframe.matching import labels_match, tokens
from clearframe.overlay import boxes_overlap, iou, locates
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


def union_spans(ranges: list[TimeRange]) -> list[TimeRange]:
    """Overlapping intervals welded into the fewest that cover the same time.

    Boxless by intent: any rectangle on the input describes a narrower span
    than the output range does, so carrying one out of here would misplace it.
    Use it where the answer is a stretch of time and nothing else — unscanned
    ranges, which never had a box in the first place.
    """
    out: list[TimeRange] = []
    for r in sorted(ranges, key=lambda r: (r.start_s, r.end_s)):
        if out and r.start_s <= out[-1].end_s:
            if r.end_s > out[-1].end_s:
                out[-1] = out[-1].model_copy(update={"end_s": r.end_s})
            continue
        out.append(r.model_copy(update={"bbox": None}))
    return out


# The shortest stretch worth reporting as an appearance of its own. Below this
# a leftover is two passes disagreeing about where an appearance ended, not a
# separate sighting: the live tattoo pair's real remainders are 0.1s and 0.2s
# at shared boundaries, while its one genuine uncovered tail is 0.8s. Emitting
# the small ones would also manufacture ranges shorter than a frame, which
# `timeline.timing_is_reliable` then disowns — costing the element every box
# it had. Re-check it against new footage before trusting it, like the three
# merge thresholds above.
MIN_SPLIT_S = 0.25


def _gaps(span: TimeRange, covered: list[TimeRange]) -> list[tuple[float, float]]:
    """The parts of `span` no kept range accounts for."""
    out: list[tuple[float, float]] = []
    cursor = span.start_s
    for k in covered:
        if k.end_s <= cursor or k.start_s >= span.end_s:
            continue
        if k.start_s > cursor:
            out.append((cursor, k.start_s))
        cursor = max(cursor, k.end_s)
        if cursor >= span.end_s:
            break
    if cursor < span.end_s:
        out.append((cursor, span.end_s))
    return out


def merge_appearances(ranges: list[TimeRange]) -> list[TimeRange]:
    """Merge sightings without painting one shot's rectangle across another.

    The scan is asked to split a moving element into shorter appearances, each
    with the box for THAT appearance. Two passes then describe the same
    seconds at different resolutions: one returns the split, the other one
    coarse range with a single box that is a union of wherever the subject
    travelled. Welding those together kept the coarse box and lost the split —
    the same failure `overlay.py` refuses to draw, arriving through the merge.

    So the finest measurement of any second wins. Candidates are taken shortest
    first, each keeping only the seconds nothing better already covers; a range
    that is entirely covered still donates its box to a survivor that has none,
    because a union box over a wider span is the only measurement there is and
    is honest on the narrower one. The output tiles the covered set exactly, so
    `_screen_time` still measures the union and overlapping sightings still
    count once.
    """
    ordered = sorted(
        ranges, key=lambda r: (r.duration_s, r.bbox is None, r.start_s, r.end_s)
    )
    kept: list[TimeRange] = []

    def _donate(r: TimeRange) -> None:
        """A rectangle beats no rectangle on seconds both ranges describe."""
        if r.bbox is None:
            return
        for i, k in enumerate(kept):
            if k.bbox is None and k.start_s < r.end_s and r.start_s < k.end_s:
                kept[i] = k.model_copy(update={"bbox": r.bbox})

    for r in ordered:
        gaps = _gaps(r, sorted(kept, key=lambda k: k.start_s))
        _donate(r)
        for start, end in gaps:
            if end - start >= MIN_SPLIT_S:
                kept.append(r.model_copy(update={"start_s": start, "end_s": end}))
                continue
            # Noise at a shared boundary. Widen whichever neighbour touches it
            # rather than emitting a sub-frame range of its own.
            before = [i for i, k in enumerate(kept) if k.end_s == start]
            after = [i for i, k in enumerate(kept) if k.start_s == end]
            if before:
                kept[before[0]] = kept[before[0]].model_copy(update={"end_s": end})
            elif after:
                kept[after[0]] = kept[after[0]].model_copy(update={"start_s": start})
            else:
                kept.append(r.model_copy(update={"start_s": start, "end_s": end}))

    kept.sort(key=lambda r: (r.start_s, r.end_s))
    # Adjacent stretches join only when neither carries a rectangle — with no
    # box to misplace, one range says the same thing as two.
    out: list[TimeRange] = []
    for r in kept:
        if (
            out
            and out[-1].bbox is None
            and r.bbox is None
            and r.start_s <= out[-1].end_s
        ):
            out[-1] = out[-1].model_copy(update={"end_s": max(out[-1].end_s, r.end_s)})
            continue
        out.append(r)
    return out


def _overlaps(a: DetectedElement, b: DetectedElement) -> bool:
    return any(
        r.start_s < q.end_s and q.start_s < r.end_s
        for r in a.time_ranges
        for q in b.time_ranges
    )


# A label that names the same thing in both passes, allowing only for
# punctuation and word order. Deliberately far above MATCH_THRESHOLD: this is
# the only evidence permitted to merge across a type disagreement.
_NAMES_THE_SAME = 0.9

# The floor for treating a shared instant and a shared place as CORROBORATION.
# Colocation promotes a label agreement that fell just short of
# MATCH_THRESHOLD; it never manufactures one. Without this, two people standing
# in one frame overlapped — which is what standing next to someone looks like —
# and Lelouch was merged with C.C., and a cat named Arthur with a pizza
# delivery guy. Both absorbed findings were deleted from the report.
_WEAK_AGREEMENT = 0.3


# How much two rectangles must agree when there is no usable clock behind
# them. Anchored on the two pairs that set it, both from one live re-run:
# the same face tattoo measured by both passes scores 0.56, while aviator
# sunglasses and a sticker on a water heater — which clip a corner — score
# 0.06. Only used when the timing has been disowned; a pair that shares an
# instant needs no more than an overlap.
SAME_REGION_IOU = 0.3


def _colocated(a: DetectedElement, b: DetectedElement) -> bool:
    """On screen at the same moment AND in the same part of the frame.

    The objection to matching on time alone is that two distinct logos share a
    shot. They do — and they are not in the same place in it, which is what
    this adds. Both sightings must carry a box that LOCATES: an absent box is
    not agreement, and neither is a box around the whole frame, which overlaps
    every other box in the picture.

    That last clause is not defensive. Replaying a real run's detections found
    "Stu Price (Ed Helms)" boxed at {0, 0, 1, 1} while sharing a tenth of a
    second with "Alan Garner (Zach Galifianakis)" — two actors, merged into
    one, and one of them deleted from the report. Over-merging is the failure
    this whole rule is written around.
    """
    # A clock we have already disowned cannot testify that two sightings are
    # different. One live re-run returned the second pass's timecodes as
    # seconds DIVIDED BY 100 — 0.04971 for 4.971s — so the two passes' ranges
    # never overlapped and the same tattoo stayed two findings. `timeline.py`
    # had already proved those timecodes impossible; using them anyway to keep
    # the findings apart was reading meaning into the same numbers we refused
    # to trust.
    unclocked = not (a.timing_reliable and b.timing_reliable)
    pairs = [
        (r.bbox, q.bbox)
        for r in a.time_ranges
        for q in b.time_ranges
        if (unclocked or (r.start_s < q.end_s and q.start_s < r.end_s))
        and locates(r.bbox) and locates(q.bbox)
    ]
    if unclocked:
        # The rectangle is the whole of the evidence, so it has to describe the
        # same region rather than merely touch one.
        return any(iou(r, q) >= SAME_REGION_IOU for r, q in pairs)
    return any(boxes_overlap(r, q) for r, q in pairs)


def _same_finding(a: DetectedElement, b: DetectedElement) -> bool:
    """Are these two sightings of one object?

    Two rules beyond the label, each added for a pair that survived on a live
    run and was routed, scored and reported twice.

    Same type, same instant, same rectangle. "Mike Tyson face tattoo" and
    "Stu's Face Tattoo" share {face, tattoo} — 2 of 4 tokens, 0.5 against a
    0.6 threshold — so the label alone says no. They are the same square inch
    of the same face at the same second, and the grounding pass returned the
    identical box for both.

    Or one of them is TEXT. TEXT_ON_SCREEN is what the scan produces when it
    reads letters rather than recognising the thing wearing them, so a mark
    the second pass spelled out is the mark, not a separate finding — but only
    on an all-but-identical label, because that is the whole of the evidence.
    """
    if a.element_type is b.element_type:
        if labels_match(a.label, b.label):
            return True
        # Corroboration, not substitution: the labels must already half agree.
        return labels_match(a.label, b.label, _WEAK_AGREEMENT) and _colocated(a, b)
    if ElementType.TEXT in (a.element_type, b.element_type):
        return labels_match(a.label, b.label, _NAMES_THE_SAME) and _overlaps(a, b)
    return _one_object_typed_twice(a, b)


# How much of the smaller rectangle must lie inside the larger one for the two
# to be the same region. One live pair sits at 1.00 — the LOGO box entirely
# inside the ARTWORK box — while their IoU is 0.207, under `SAME_REGION_IOU`,
# because IoU punishes containment whenever the two extents differ in scale.
# That is the wrong measure for a pair where one pass boxed the sticker and the
# other boxed the sticker and its surround.
CONTAINED = 0.9


def _identical_label(a: DetectedElement, b: DetectedElement) -> bool:
    """Not `labels_match` — the same words, exactly.

    This is what lets a group cross the type boundary at all, so it has to be
    stronger than the similarity test that boundary was protecting against. A
    Nike swoosh on a shoe and a Nike mural on a wall are genuinely two things
    and may both be labelled "Nike"; what they are not is one object that two
    passes typed differently.
    """
    return " ".join(a.label.split()).casefold() == " ".join(b.label.split()).casefold()


def _contained(a: DetectedElement, b: DetectedElement) -> bool:
    """Is one sighting's rectangle wholly inside the other's, at some instant?

    The same timing guard `_colocated` uses: a clock already disowned cannot
    testify that two sightings are different, so a pair with a broken clock is
    compared on place alone.
    """
    unclocked = not (a.timing_reliable and b.timing_reliable)
    for r in a.time_ranges:
        for q in b.time_ranges:
            if not (unclocked or (r.start_s < q.end_s and q.start_s < r.end_s)):
                continue
            if not (locates(r.bbox) and locates(q.bbox)):
                continue
            overlap = _intersection_area(r.bbox, q.bbox)
            smaller = min(_area(r.bbox), _area(q.bbox))
            if smaller > 0 and overlap / smaller >= CONTAINED:
                return True
    return False


def _area(box) -> float:
    return max(0.0, box.ymax - box.ymin) * max(0.0, box.xmax - box.xmin)


def _intersection_area(a, b) -> float:
    dy = min(a.ymax, b.ymax) - max(a.ymin, b.ymin)
    dx = min(a.xmax, b.xmax) - max(a.xmin, b.xmin)
    return max(0.0, dy) * max(0.0, dx)


def _one_object_typed_twice(a: DetectedElement, b: DetectedElement) -> bool:
    """One thing that two passes disagreed about the TYPE of.

    A deployed run reported `Sticker on water heater` twice from the same scan:
    id `5` typed LOGO — so TRADEMARK — with a 20ms appearance the physical test
    rejected, and another typed ARTWORK — so COPYRIGHT_ART — with a usable
    clock. Byte-identical labels, and `triage` never compared them, because
    grouping requires one element type and only TEXT yields. The result is the
    failure this codebase already knows is its most consequential: one object
    carrying two owners, two routes and two risk bands.

    Staying apart is right for SIMILAR labels, and `CLAUDE.md` records "LOGO vs
    ARTWORK still stays two findings" as deliberate. It is wrong on an
    identical one — but only with a second, independent signal, because
    over-merging DELETES a finding and that is the failure this module is
    written around. So place has to agree too: either the existing colocation
    rule, or one rectangle wholly inside the other, which is what two passes
    boxing the same sticker at different extents looks like.
    """
    if not _identical_label(a, b):
        return False
    return _colocated(a, b) or _contained(a, b)


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


def _shared_label(group: list[DetectedElement]) -> str:
    """The label that is true of every member, or the fullest if none is.

    Two rules pulling opposite ways, and both are right for their own case.

    Two passes describing ONE object: "Stu's Face Tattoo" knows something
    "Face Tattoo" does not, so the fuller label wins. That is what this used
    to do unconditionally.

    One MARK on several objects: a live Code Geass clip put Pizza Hut on a
    delivery scooter, on the delivery man's cap and on the pizza box. Merging
    them is right — it is one trademark and one clearance — but the longest
    label won, so the group was called "Pizza Hut Delivery Scooter" and at 4s
    that label sat on a rectangle round the man's hat. It reads as the tool
    losing track of the scooter.

    A label whose tokens are contained in every other member's is true of all
    of them; "Pizza Hut" is, and "Pizza Hut Delivery Scooter" is not. Where no
    such label exists, nothing has been generalised and the fullest still wins.
    """
    labels = [d.label for d in group if d.label]
    if not labels:
        return group[0].label
    sets = [(label, tokens(label)) for label in labels]
    general = [
        label
        for label, own in sets
        if own and all(own <= other for _, other in sets if other)
    ]
    if general:
        # Shortest among equals: the same mark spelled two ways generalises to
        # the plainer spelling rather than an arbitrary one.
        return min(general, key=len)
    return max(labels, key=len)


def _merge(group: list[DetectedElement]) -> DetectedElement:
    # Keep the id and position of the first sighting, but take the fullest
    # label and description in the group: routing reads the description, and a
    # pass that wrote "replicating Mike Tyson's famous tattoo" knows something
    # the pass that wrote "a tribal tattoo" does not.
    first = group[0]
    richest = max(group, key=lambda d: len(d.description or ""))
    label = _shared_label(group)
    # A pass whose timecodes failed the physical test contributes none of them.
    # Unioning them in produced a range set spanning both units at once, and
    # the stickiness rule below then disowned the whole finding — so a sighting
    # that HAD been measured correctly stopped drawing a box. Three findings
    # lost their boxes that way on one live re-run.
    timed = [d for d in group if d.timing_reliable] or group
    ranges = merge_appearances([r for d in timed for r in d.time_ranges])
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
        "label": label,
        "description": richest.description,
        # A brand read as lettering is still the brand. TEXT is the fallback
        # type, so it never decides the category of a group that contains a
        # type naming an actual rights subject.
        #
        # And a broken clock does not outvote a working one here either. When a
        # group crosses the type boundary — one object two passes typed
        # differently — the sighting whose timecodes survive the physical test
        # is the one there is reason to trust, and its type carries the
        # category. That decides whether a sticker is cleared as a trademark or
        # as an artwork, which is not a detail.
        "element_type": next(
            (
                d.element_type
                for d in group
                if d.element_type is not ElementType.TEXT and d.timing_reliable
            ),
            next(
                (d.element_type for d in group
                 if d.element_type is not ElementType.TEXT),
                first.element_type,
            ),
        ),
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
        # Disowned timing is sticky against SILENCE — one pass proving the
        # timecodes impossible is not cancelled by another pass saying nothing.
        # It is not sticky against a measurement: a range that survives the
        # physical test beats one that failed it, so a group with any usable
        # clock keeps it, and only a group with none stays disowned.
        "timing_reliable": any(d.timing_reliable for d in group),
        "timing_note": next((d.timing_note for d in timed if d.timing_note), ""),
    }
    return first.model_copy(
        update={
            **richer,
            "time_ranges": ranges,
            "prominence": Prominence(
                screen_time_s=_screen_time(timed, ranges),
                frame_coverage=max(d.prominence.frame_coverage for d in group),
                centrality=max(d.prominence.centrality for d in group),
                plot_integral=any(d.prominence.plot_integral for d in group),
            ),
        }
    )


def triage(detections: list[DetectedElement]) -> list[TriagedElement]:
    """Group sightings of one thing, then assign its clearance category.

    Grouping used to be exact string equality on `(element_type, label)`, which
    worked while the only two sources were the scan and its auditor — the
    auditor is primed with the first pass's labels and echoes them. A second
    independent pass is not, and phrases things its own way: one live run
    produced "Stu's Face Tattoo" and "Face Tattoo" as separate findings with
    separate routes, disagreeing with each other about whether it was the
    Whitmill fact pattern.

    Matching is deliberately conservative. Under-merging leaves a duplicate,
    which is annoying and costs a research run. Over-merging DELETES a finding,
    which is the failure this product exists to prevent. `_same_finding` holds
    the whole rule: a shared label, or the same rectangle at the same instant,
    or an all-but-identical label where one pass fell back to TEXT.
    """
    # Compared against every member of a group, not just the first.
    #
    # `_same_finding(g[0], d)` made a group's identity whatever happened to
    # arrive first, which is not a principled basis for anything — and it
    # actively fought the cross-type rule. A live run has THREE sightings of one
    # sticker: a LOGO with a broken clock, an ARTWORK, and `"Drink Beer" Sticker`
    # which is the same ARTWORK described more fully. Matching on the first
    # member, the LOGO joined and then the third was compared against the LOGO
    # alone — different type, different words — so it split off, and adding a
    # merge rule made the finding count go UP.
    groups: list[list[DetectedElement]] = []
    for d in detections:
        for g in groups:
            if any(_same_finding(m, d) for m in g):
                g.append(d)
                break
        else:
            groups.append([d])

    out: list[TriagedElement] = []
    for group in groups:
        merged = _merge(group) if len(group) > 1 else group[0]
        out.append(
            TriagedElement(**merged.model_dump(), category=CATEGORY_RULES[merged.element_type])
        )
    return out
