"""Your own cast is not a third-party clearance finding.

A live run of The Hangover Part II reported three findings that read:

    Phil Wenneck (Bradley Cooper)    RIGHT_OF_PUBLICITY   obtain a release
    Stu Price (Ed Helms)             RIGHT_OF_PUBLICITY   obtain a release
    Alan Garner (Zach Galifianakis)  RIGHT_OF_PUBLICITY   obtain a release

You cannot have Bradley Cooper playing Phil Wenneck in your film without a
contract with Bradley Cooper. Telling the production to go and get one is
noise, and it is expensive noise: each of them was routed to a live search for
an agent contact.

It is also what broke the overlay. Asked to place a named performer on a
frame, the model answers with the whole frame — {0, 0, 1, 1} at 6s, again at
9s — so a rectangle covering the entire video sat on top of every real
finding, with its label pinned in the corner.

The removal stops at the cast, and that boundary is the point. An unnamed
person the camera happened to catch DOES need a release, and is personal data
under GDPR, DPDP and LGPD besides. So this asks for positive evidence — the
scan naming the performer — and everything else stays a finding. Being wrong
towards "you still need to clear this" is the only survivable direction.
"""

import pytest

from clearframe.cast import partition
from clearframe.models import (
    ClearanceCategory,
    ElementType,
    Prominence,
    TimeRange,
    TriagedElement,
)


def el(label, description="", kind=ElementType.FACE):
    return TriagedElement(
        id=label[:8], label=label, element_type=kind, description=description,
        time_ranges=[TimeRange(start_s=1.0, end_s=5.0)],
        prominence=Prominence(screen_time_s=4.0, frame_coverage=0.4,
                              centrality=0.8, plot_integral=True),
        category=ClearanceCategory.RIGHT_OF_PUBLICITY
        if kind is ElementType.FACE else ClearanceCategory.COPYRIGHT_ART,
    )


# --- the three from the live run

@pytest.mark.parametrize("label", [
    "Phil Wenneck (Bradley Cooper)",
    "Stu Price (Ed Helms)",
    "Alan Garner (Zach Galifianakis)",
])
def test_a_named_performer_is_cast_not_a_finding(label):
    findings, cast = partition([el(label)])
    assert findings == []
    assert [c.performer for c in cast] == [label.split("(")[1].rstrip(")")]


def test_the_credit_keeps_the_part_and_the_performer():
    _, cast = partition([el("Phil Wenneck (Bradley Cooper)")])
    assert cast[0].character == "Phil Wenneck"
    assert cast[0].performer == "Bradley Cooper"


def test_an_attribution_in_the_description_is_enough():
    """The parenthetical is not a contract either — the scan drops it."""
    findings, cast = partition([
        el("Stu Price", description="The face of the character Stu Price, "
                                    "played by actor Ed Helms.")
    ])
    assert findings == []
    assert cast[0].performer == "Ed Helms"


# --- the boundary: everyone the production did NOT cast

@pytest.mark.parametrize("label,description", [
    ("Young Boy", "A young boy standing near the counter."),
    ("Man at bar", "A man seated at the bar in the background."),
    ("Grandmother", "An elderly woman watching from the doorway."),
    ("Bystander", "Someone crossing behind the actors."),
])
def test_an_unnamed_person_is_still_a_finding(label, description):
    """These are the releases you would otherwise ship without."""
    findings, cast = partition([el(label, description)])
    assert cast == []
    assert [f.label for f in findings] == [label]


def test_a_name_alone_is_not_evidence_of_casting():
    """A documentary subject has a name too, and has signed nothing.

    Conservative on purpose: without an attribution this stays a finding, and
    the cost of that is one line in a report.
    """
    findings, cast = partition([el("Sarah Connor", "A woman at the window.")])
    assert cast == []
    assert len(findings) == 1


def test_a_one_word_parenthetical_is_not_a_performer():
    findings, cast = partition([el("Waiter (background)", "A waiter passing by.")])
    assert cast == []
    assert len(findings) == 1


# --- nothing else is touched

def test_only_faces_are_considered():
    """'Stu's Face Tattoo' names a person and is not one.

    Whitmill v. Warner Bros. is this exact object. Losing it to a cast list
    would be the worst outcome in this file.
    """
    items = [
        el("Stu's Face Tattoo", "modelled after Mike Tyson's tattoo, worn by "
                                "Stu Price, played by actor Ed Helms",
           kind=ElementType.TATTOO),
        el("Calvin Klein", "brand name on a waistband", kind=ElementType.LOGO),
    ]
    findings, cast = partition(items)
    assert cast == []
    assert len(findings) == 2


def test_a_drawn_character_is_left_to_sourcework():
    """A drawn character has no right of publicity and nobody to release it.

    That question belongs to `sourcework.subsumed_by`, which answers it with
    the medium of the work. Answering it here too would give one object two
    verdicts, which is the bug this session started with.
    """
    findings, cast = partition([
        el("Lelouch Lamperouge", "the protagonist", kind=ElementType.CHARACTER)
    ])
    assert cast == []
    assert len(findings) == 1


def test_order_is_preserved_for_everything_that_stays():
    items = [el("Calvin Klein", kind=ElementType.LOGO),
             el("Phil Wenneck (Bradley Cooper)"),
             el("Young Boy", "a boy"),
             el("Dog T-Shirt", kind=ElementType.ARTWORK)]
    findings, cast = partition(items)
    assert [f.label for f in findings] == ["Calvin Klein", "Young Boy", "Dog T-Shirt"]
    assert len(cast) == 1


# --- through the pipeline, because all three transports read `state.elements`

def test_the_triage_stage_takes_cast_out_of_the_findings_list():
    """CLI, web and MCP all read `state.elements`, so one split serves all."""
    import asyncio

    from clearframe.models import DetectedElement, Production, ProductionState
    from clearframe.stages.triage_stage import TriageStage

    def det(label, kind, description=""):
        return DetectedElement(
            id=label[:8], label=label, element_type=kind, description=description,
            time_ranges=[TimeRange(start_s=1.0, end_s=5.0)],
            prominence=Prominence(screen_time_s=4.0, frame_coverage=0.4,
                                  centrality=0.8, plot_integral=True),
        )

    state = ProductionState(
        production=Production(id="p", title="T", footage_uri="clip.mp4", duration_s=40.0, fps=24.0),
        detections=[
            det("Phil Wenneck (Bradley Cooper)", ElementType.FACE),
            det("Young Boy", ElementType.FACE, "a boy by the door"),
            det("Calvin Klein", ElementType.LOGO),
        ],
    )

    class Ctx:
        pass

    ctx = Ctx()
    ctx.state = state
    asyncio.run(TriageStage().run(ctx))

    assert [e.label for e in state.elements] == ["Young Boy", "Calvin Klein"]
    assert [c.performer for c in state.cast] == ["Bradley Cooper"]


def test_the_dossier_prints_the_credits_it_removed():
    """Silently dropping three faces the reviewer can see would be worse."""
    from clearframe.dossier import build_dossier
    from clearframe.models import CastCredit, Production, ProductionState

    state = ProductionState(
        production=Production(id="p", title="T", footage_uri="clip.mp4", duration_s=40.0, fps=24.0),
        cast=[CastCredit(id="1", label="Phil Wenneck (Bradley Cooper)",
                         character="Phil Wenneck", performer="Bradley Cooper")],
    )
    dossier = build_dossier(state, generated_at="2026-08-23T00:00:00Z")
    assert [c.performer for c in dossier.cast] == ["Bradley Cooper"]
    assert dossier.cast_summary["count"] == 1
    assert "not clearance findings" in dossier.cast_summary["headline"]


def test_a_production_with_no_recognised_cast_says_nothing():
    from clearframe.cast import summarise

    assert summarise([]) is None
