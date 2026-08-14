from clearframe.exporters.edl import MarkerEntry, render_edl
from clearframe.models import ClearanceCategory, RiskBand


def test_edl_golden():
    e = MarkerEntry(
        start_s=12.0,
        end_s=14.0,
        label="Blinding Lights - The Weeknd",
        band=RiskBand.CRITICAL,
        category=ClearanceCategory.MUSIC_SYNC,
    )
    out = render_edl("ClearFrame Risk Markers", [e], fps=24)
    assert out.splitlines()[0] == "TITLE: ClearFrame Risk Markers"
    assert "* LOC: 01:00:12:00 RED CRITICAL|MUSIC_SYNC|Blinding Lights - The Weeknd" in out
