"""CMX3600 EDL with locator lines — importable via Resolve's "Timeline Markers from EDL"."""

from dataclasses import dataclass

from clearframe.models import ClearanceCategory, RiskAssessment, RiskBand, TriagedElement
from clearframe.timecode import seconds_to_tc

BAND_COLOR: dict[RiskBand, str] = {
    RiskBand.CRITICAL: "RED",
    RiskBand.HIGH: "YELLOW",
    RiskBand.MEDIUM: "CYAN",
    RiskBand.LOW: "GREEN",
}


@dataclass
class MarkerEntry:
    start_s: float
    end_s: float
    label: str
    band: RiskBand
    category: ClearanceCategory


def elements_to_markers(
    elements: list[TriagedElement], risk: dict[str, RiskAssessment]
) -> list[MarkerEntry]:
    markers = [
        MarkerEntry(
            start_s=r.start_s,
            end_s=r.end_s,
            label=el.label,
            band=risk[el.id].band,
            category=el.category,
        )
        for el in elements
        for r in el.time_ranges
    ]
    return sorted(markers, key=lambda m: m.start_s)


def render_edl(title: str, entries: list[MarkerEntry], fps: float) -> str:
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    frame_s = 1.0 / fps
    for i, e in enumerate(entries, start=1):
        tc_in = seconds_to_tc(e.start_s, fps=fps)
        tc_out = seconds_to_tc(e.start_s + frame_s, fps=fps)
        lines.append(f"{i:03d}  001      V     C        {tc_in} {tc_out} {tc_in} {tc_out}")
        lines.append(
            f"* LOC: {tc_in} {BAND_COLOR[e.band]} {e.band.value}|{e.category.value}|{e.label}"
        )
        lines.append("")
    return "\n".join(lines)
