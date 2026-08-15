from clearframe.models import (
    Brief,
    CourtOpinion,
    Precedent,
    Production,
    ProductionState,
    ResearchPlan,
)


def test_court_models_roundtrip():
    opinion = CourtOpinion(
        element_id="e1",
        holding="clear_required",
        confidence="high",
        reasoning="Plot-integral sync use; no de minimis defense.",
        briefs=[
            Brief(
                side="counsel",
                argument="Willful infringement risks statutory damages.",
                precedents=[
                    Precedent(
                        case_name="Ringgold v. Black Entertainment Television",
                        citation="126 F.3d 70 (2d Cir. 1997)",
                        holding="Recognizable background artwork used without license was infringing.",
                        relevance="Plot-integral copyrighted work shown clearly.",
                    )
                ],
            )
        ],
    )
    state = ProductionState(
        production=Production(id="p", title="T", footage_uri="u", duration_s=1),
        court={"e1": opinion},
        research_plan={
            "e1": ResearchPlan(
                element_id="e1",
                processor="pro",
                rationale="Music ownership splits composition and master.",
                est_cost_usd=1.0,
            )
        },
    )
    restored = ProductionState.model_validate_json(state.model_dump_json())
    assert restored.court["e1"].holding == "clear_required"
    assert restored.court["e1"].briefs[0].precedents[0].citation.startswith("126 F.3d")
    assert restored.research_plan["e1"].processor == "pro"
