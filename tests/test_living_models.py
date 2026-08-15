from clearframe.models import (
    CandidateEntity,
    ClearanceWatch,
    ElementType,
    Production,
    ProductionState,
    ScriptDrift,
    ScriptMention,
    WatchAlert,
)


def test_living_clearance_state_roundtrip():
    state = ProductionState(
        production=Production(
            id="p",
            title="T",
            footage_uri="u",
            duration_s=1,
            script_uri="demo://golden-hour-script",
        ),
        script_mentions=[
            ScriptMention(label="Coca-Cola can", element_type=ElementType.LOGO, scene="INT. KITCHEN")
        ],
        drift=ScriptDrift(unscripted_element_ids=["e3"], scripted_not_seen=[]),
        candidates={
            "e5": [
                CandidateEntity(
                    name="Precita Eyes Muralists",
                    kind="mural registry",
                    url="https://example.org",
                    note="registers SF-area murals",
                )
            ]
        },
        watches={
            "e3": ClearanceWatch(
                element_id="e3", monitor_id="mon-e3", query="new Nike enforcement", frequency="weekly"
            )
        },
        alerts=[
            WatchAlert(
                element_id="e3",
                monitor_id="mon-e3",
                at="2026-09-01T00:00:00Z",
                summary="Nike files new depiction suit",
                source_url="https://example.com",
            )
        ],
    )
    restored = ProductionState.model_validate_json(state.model_dump_json())
    assert restored.drift.unscripted_element_ids == ["e3"]
    assert restored.candidates["e5"][0].kind == "mural registry"
    assert restored.watches["e3"].monitor_id == "mon-e3"
    assert restored.alerts[0].summary.startswith("Nike")


def test_precedent_quote_fields_default_empty():
    from clearframe.models import Precedent

    p = Precedent(case_name="X", citation="C", holding="H", relevance="R")
    assert p.quote == "" and p.source_url == ""
