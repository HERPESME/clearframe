"""Six findings, one licence, and nothing on screen said so.

A live Code Geass run reported Lelouch Lamperouge at HIGH 49, Nunnally at
MEDIUM 39, C.C., Arthur, the delivery driver and a framed painting — six
separate clearance findings, each with its own band, in footage the pipeline
had already identified as being an episode of Code Geass owned by Sunrise.

The routing was right: every one of them came out LOCAL, spending nothing,
with the rationale "an element of a work this footage appears to BE". What was
missing was any way for a reviewer to SEE that. Six bands read as six
problems, and the reviewer asked why characters from the franchise whose
episode this is were being tagged at all.

`sourcework.summarise_source_work` was written for exactly this and had zero
callers — the same gap `cases_for()` had before Phase 11. The findings still
appear, because a dossier that silently omits the lead character of the clip
is not complete and the licence still has to reach the declared territories
and media. What changes is that the report leads with the one action there
actually is: clear the work.
"""

import json
from pathlib import Path

from clearframe.models import ProductionState
from clearframe.stages.preview import PreviewStage
from clearframe.sourcework import summarise_source_work


def _state(fixture: str) -> ProductionState:
    raw = json.loads(Path(fixture).read_text())
    return ProductionState(**raw)


def test_a_drawn_work_reports_what_is_covered_by_it():
    from clearframe.models import (
        ClearanceCategory, ElementType, Prominence, SourceWork,
        TimeRange, TriagedElement,
    )

    work = SourceWork(title="Code Geass: Lelouch of the Rebellion",
                      rights_holder="Sunrise", confidence="high",
                      basis="Character designs are characteristic of the series.",
                      medium="animation")

    def el(label, kind, cat):
        return TriagedElement(
            id=label[:6], label=label, element_type=kind, description="",
            time_ranges=[TimeRange(start_s=1.0, end_s=5.0)],
            prominence=Prominence(screen_time_s=4.0, frame_coverage=0.3,
                                  centrality=0.6, plot_integral=True),
            category=cat,
        )

    elements = [
        el("Lelouch Lamperouge", ElementType.CHARACTER, ClearanceCategory.COPYRIGHT_ART),
        el("Nunnally Lamperouge", ElementType.CHARACTER, ClearanceCategory.COPYRIGHT_ART),
        el("Pizza Hut Delivery Scooter", ElementType.LOGO, ClearanceCategory.TRADEMARK),
    ]
    summary = summarise_source_work(work, elements)
    assert summary is not None
    assert summary["subsumed"] == 2
    assert summary["independent"] == 1
    assert "Sunrise" in summary["action"]


def test_the_summary_reaches_the_state(tmp_path):
    """The wiring that was missing: nothing called it."""
    import asyncio

    from clearframe.models import (
        ClearanceCategory, ElementType, Production, Prominence, SourceWork,
        TimeRange, TriagedElement,
    )
    from clearframe.pipeline import PipelineContext
    from clearframe.store import LocalJsonStore

    state = ProductionState(
        production=Production(id="p", title="T", footage_uri="c.mp4",
                              duration_s=50.0, fps=24.0),
        source_work=SourceWork(title="Code Geass", rights_holder="Sunrise",
                               confidence="high", basis="art style",
                               medium="animation"),
        elements=[
            TriagedElement(
                id="e1", label="Lelouch Lamperouge",
                element_type=ElementType.CHARACTER, description="",
                time_ranges=[TimeRange(start_s=1.0, end_s=5.0)],
                prominence=Prominence(screen_time_s=4.0, frame_coverage=0.3,
                                      centrality=0.6, plot_integral=True),
                category=ClearanceCategory.COPYRIGHT_ART,
            )
        ],
    )
    ctx = PipelineContext(state=state, gemini=None, parallel=None,
                          store=LocalJsonStore(tmp_path))
    asyncio.run(PreviewStage().run(ctx))
    assert state.subsumed_ids == ["e1"]
    assert state.source_work_summary is not None
    assert state.source_work_summary["subsumed"] == 1


def test_live_action_subsumes_nothing_and_says_so():
    from clearframe.models import (
        ClearanceCategory, ElementType, Prominence, SourceWork,
        TimeRange, TriagedElement,
    )

    live = SourceWork(title="The Hangover Part II", rights_holder="Warner Bros.",
                      confidence="high", basis="the cast", medium="live_action")
    tattoo = TriagedElement(
        id="t", label="Stu's Face Tattoo", element_type=ElementType.TATTOO,
        description="", time_ranges=[TimeRange(start_s=1.0, end_s=5.0)],
        prominence=Prominence(screen_time_s=4.0, frame_coverage=0.3,
                              centrality=0.6, plot_integral=True),
        category=ClearanceCategory.COPYRIGHT_ART,
    )
    summary = summarise_source_work(live, [tattoo])
    assert summary["subsumed"] == 0
    assert summary["independent"] == 1
