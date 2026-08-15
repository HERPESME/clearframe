from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context


async def test_incomplete_ip_elements_get_candidates(tmp_path):
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline()).run(ctx)
    # mural: research incomplete + copyright category -> FindAll candidates
    assert "e5" in state.candidates
    assert len(state.candidates["e5"]) == 3
    kinds = {c.kind for c in state.candidates["e5"]}
    assert "property owner" in kinds
    # passerby face: incomplete but RIGHT_OF_PUBLICITY -> no enumeration
    assert "e6" not in state.candidates
    # complete research -> no enumeration
    assert "e1" not in state.candidates
