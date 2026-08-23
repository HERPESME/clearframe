"""The cap funds the most exposed findings, not the longest on screen.

`CLEARFRAME_MAX_RESEARCH` bounds the expensive rung, and overflow is reported
as RESEARCH INCOMPLETE rather than dropped — that part was always right. What
was wrong is the ordering: `sorted(deep_ids, key=screen_time_s)`.

Screen time is one of four inputs to prominence and none of the inputs to
category weight, context or depiction. On a clip where a work's own characters
dominate the frame, the funded slots went to them and the one genuinely unknown
artwork overflowed — the exact inversion the cap exists to prevent.

`provisional_score` already answers "how exposed is this before we know who
owns it", which is precisely the question the cap has to rank by. It is the
number the router escalates on and the number the two-phase report bands with,
so using it here also means one ranking rule instead of two.
"""

from clearframe.models import (
    ClearanceCategory, ElementType, Prominence, TimeRange, TriagedElement,
)
from clearframe.scoring import provisional_score
from clearframe.stages.research import rank_for_funding


def el(eid, label, screen_time_s, coverage, central, plot, category, kind):
    return TriagedElement(
        id=eid, label=label, element_type=kind, description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=1.0 + screen_time_s)],
        prominence=Prominence(screen_time_s=screen_time_s, frame_coverage=coverage,
                              centrality=central, plot_integral=plot),
        category=category,
    )


# A long, incidental background logo versus a brief, central, plot-integral
# mural by an unknown artist. Screen time prefers the first; exposure does not.
LONG_BACKGROUND = el(
    "bg", "Wristwatch", 30.0, 0.02, 0.1, False,
    ClearanceCategory.TRADEMARK, ElementType.LOGO,
)
SHORT_CRITICAL = el(
    "art", "Mural (unknown artist)", 6.0, 0.6, 0.9, True,
    ClearanceCategory.COPYRIGHT_ART, ElementType.ARTWORK,
)


def test_exposure_outranks_screen_time():
    by_id = {e.id: e for e in (LONG_BACKGROUND, SHORT_CRITICAL)}
    assert rank_for_funding(["bg", "art"], by_id) == ["art", "bg"]


def test_the_ranking_is_the_provisional_score():
    """One rule, not two: the same number the router escalates on."""
    assert provisional_score(SHORT_CRITICAL) > provisional_score(LONG_BACKGROUND)


def test_ties_are_stable_and_do_not_depend_on_dict_order():
    a = el("a", "One", 5.0, 0.2, 0.5, False, ClearanceCategory.TRADEMARK, ElementType.LOGO)
    b = el("b", "Two", 5.0, 0.2, 0.5, False, ClearanceCategory.TRADEMARK, ElementType.LOGO)
    by_id = {"a": a, "b": b}
    assert rank_for_funding(["a", "b"], by_id) == ["a", "b"]
    assert rank_for_funding(["b", "a"], by_id) == ["b", "a"]
