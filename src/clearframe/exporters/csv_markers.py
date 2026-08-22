"""Coordinator spreadsheet / generic NLE marker CSV."""

import csv
import io

from clearframe.exporters import safe_cell
from clearframe.exporters.edl import MarkerEntry
from clearframe.timecode import seconds_to_tc


def render_csv(entries: list[MarkerEntry], fps: float) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["timecode_in", "timecode_out", "label", "category", "risk_band", "identity"]
    )
    for e in entries:
        writer.writerow(
            [
                seconds_to_tc(e.start_s, fps=fps),
                seconds_to_tc(e.end_s, fps=fps),
                safe_cell(e.label),
                e.category.value,
                e.band.value,
                e.identity,
            ]
        )
    return buf.getvalue()
