"""Rule-based clearance triage and cross-shot duplicate merging."""

from clearframe.models import (
    ClearanceCategory,
    DetectedElement,
    ElementType,
    Prominence,
    TriagedElement,
)

CATEGORY_RULES: dict[ElementType, ClearanceCategory] = {
    ElementType.LOGO: ClearanceCategory.TRADEMARK,
    ElementType.ARTWORK: ClearanceCategory.COPYRIGHT_ART,
    ElementType.MUSIC: ClearanceCategory.MUSIC_SYNC,
    ElementType.FACE: ClearanceCategory.RIGHT_OF_PUBLICITY,
    ElementType.TATTOO: ClearanceCategory.COPYRIGHT_ART,
    ElementType.LOCATION: ClearanceCategory.LOCATION,
    ElementType.TEXT: ClearanceCategory.TEXT_ON_SCREEN,
}


def _merge(group: list[DetectedElement]) -> DetectedElement:
    first = group[0]
    ranges = sorted(
        (r for d in group for r in d.time_ranges), key=lambda r: (r.start_s, r.end_s)
    )
    return DetectedElement(
        id=first.id,
        label=first.label,
        element_type=first.element_type,
        description=first.description,
        time_ranges=ranges,
        prominence=Prominence(
            screen_time_s=sum(d.prominence.screen_time_s for d in group),
            frame_coverage=max(d.prominence.frame_coverage for d in group),
            centrality=max(d.prominence.centrality for d in group),
            plot_integral=any(d.prominence.plot_integral for d in group),
        ),
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
