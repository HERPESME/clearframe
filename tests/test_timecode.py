from clearframe.timecode import seconds_to_tc


def test_basic():
    assert seconds_to_tc(12.5, fps=24, offset_s=0) == "00:00:12:12"


def test_default_hour_offset():
    assert seconds_to_tc(0) == "01:00:00:00"
