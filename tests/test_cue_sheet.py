from clearframe.exporters.cue_sheet import render_cue_sheet
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context


async def test_cue_sheet_golden(tmp_path):
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline()).run(ctx)
    csv_text = render_cue_sheet(state.production, state.elements, state.research)
    rows = csv_text.strip().split("\r\n")
    assert rows[0] == (
        "cue_number,title,rights_owner,usage,timecode_in,timecode_out,duration_s"
    )
    assert len(rows) == 2  # one music cue in the demo scene
    cue = rows[1]
    assert cue.startswith("1,Blinding Lights - The Weeknd,")
    assert ",Feature," in cue
    assert cue.endswith(",12.0")


async def test_no_music_returns_header_only(tmp_path):
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline()).run(ctx)
    non_music = [e for e in state.elements if e.category.value != "MUSIC_SYNC"]
    csv_text = render_cue_sheet(state.production, non_music, state.research)
    assert len(csv_text.strip().split("\r\n")) == 1
