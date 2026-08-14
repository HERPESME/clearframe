from clearframe.exporters.csv_markers import render_csv
from clearframe.exporters.edl import MarkerEntry
from clearframe.models import ClearanceCategory, RiskBand


def test_csv_golden():
    e = MarkerEntry(
        start_s=1.0,
        end_s=2.0,
        label='Poster, "Tranquility"',
        band=RiskBand.MEDIUM,
        category=ClearanceCategory.COPYRIGHT_ART,
    )
    rows = render_csv([e], fps=24).split("\r\n")
    assert rows[0] == "timecode_in,timecode_out,label,category,risk_band"
    assert rows[1] == '01:00:01:00,01:00:02:00,"Poster, ""Tranquility""",COPYRIGHT_ART,MEDIUM'
