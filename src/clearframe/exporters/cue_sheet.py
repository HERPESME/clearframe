"""Cue sheet export — the music usage report broadcasters file with PROs (ASCAP/BMI)."""

import csv
import io

from clearframe.models import (
    ClearanceCategory,
    Production,
    ResearchResult,
    TriagedElement,
)
from clearframe.timecode import seconds_to_tc


def render_cue_sheet(
    production: Production,
    elements: list[TriagedElement],
    research: dict[str, ResearchResult],
) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "cue_number",
            "title",
            "rights_owner",
            "usage",
            "timecode_in",
            "timecode_out",
            "duration_s",
        ]
    )
    cue_number = 0
    music = [e for e in elements if e.category == ClearanceCategory.MUSIC_SYNC]
    for el in sorted(music, key=lambda e: e.time_ranges[0].start_s):
        res = research.get(el.id)
        owner = res.owner if res and res.owner else "UNKNOWN"
        usage = "Feature" if el.prominence.plot_integral else "Background"
        for r in el.time_ranges:
            cue_number += 1
            writer.writerow(
                [
                    cue_number,
                    el.label,
                    owner,
                    usage,
                    seconds_to_tc(r.start_s, fps=production.fps),
                    seconds_to_tc(r.end_s, fps=production.fps),
                    round(r.duration_s, 1),
                ]
            )
    return buf.getvalue()
