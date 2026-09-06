"""Which finding owns a measured rectangle.

Grounding answers per LABEL — the model is handed a list of labels and returns
boxes for the ones it can see. The player draws per FINDING. Those are not the
same thing in two directions, and both were being resolved by luck:

  One finding, several places. Pizza Hut on the cap AND on the box is one
  trademark, one clearance, one finding — and two rectangles. The parser kept
  the first and dropped the rest, so the reviewer saw one of them with nothing
  saying the other existed.

  Several findings, one label. Two elements whose labels both match what the
  model returned were resolved by whichever appeared first in the state, and
  the loser's box was discarded. Where the labels were identical, both were
  handed the SAME rectangle and shown as two independently measured findings.

Binding is now explicit: one claimant takes every box for its label; several
claimants take at most one each, paired to the rectangle nearest their own
scan box, and a claimant with nothing to compare against takes none. Two
findings are never shown the same rectangle.
"""

from clearframe.models import (
    BBox, ClearanceCategory, ElementType, Prominence, TimeRange, TriagedElement,
)
from clearframe.overlay import bind_ground_boxes


def bbox(xmin: float, xmax: float) -> BBox:
    return BBox(ymin=0.4, xmin=xmin, ymax=0.6, xmax=xmax)


def el(eid: str, label: str, scan_box: BBox | None = None) -> TriagedElement:
    return TriagedElement(
        id=eid, label=label, element_type=ElementType.LOGO, description="",
        category=ClearanceCategory.TRADEMARK,
        time_ranges=[TimeRange(start_s=0.0, end_s=10.0, bbox=scan_box)],
        prominence=Prominence(screen_time_s=10.0, frame_coverage=0.1,
                              centrality=0.5, plot_integral=False),
    )


def test_one_finding_takes_every_box_measured_for_its_label():
    """The Pizza Hut case: one mark, two places, one clearance."""
    here = [el("1", "Pizza Hut", bbox(0.1, 0.2))]
    bound = bind_ground_boxes(here, {"Pizza Hut": [bbox(0.1, 0.2), bbox(0.7, 0.8)]}, 5.0)

    assert list(bound) == ["1"]
    assert [b.xmin for b in bound["1"]] == [0.1, 0.7]


def test_two_findings_sharing_a_label_are_never_given_the_same_rectangle():
    """The failure that made two findings look independently measured."""
    here = [el("1", "Nike", bbox(0.1, 0.2)), el("2", "Nike", bbox(0.7, 0.8))]
    bound = bind_ground_boxes(here, {"Nike": [bbox(0.72, 0.82)]}, 5.0)

    assert len(bound) == 1
    # The one whose own scan box is anywhere near the measurement.
    assert list(bound) == ["2"]


def test_competing_findings_each_take_the_rectangle_nearest_their_own_box():
    here = [el("1", "Nike", bbox(0.1, 0.2)), el("2", "Nike", bbox(0.7, 0.8))]
    bound = bind_ground_boxes(here, {"Nike": [bbox(0.71, 0.81), bbox(0.11, 0.21)]}, 5.0)

    assert bound["1"][0].xmin == 0.11
    assert bound["2"][0].xmin == 0.71
    assert all(len(v) == 1 for v in bound.values())


def test_a_competing_finding_with_no_box_of_its_own_takes_nothing():
    """Nothing to attribute with is not a licence to guess.

    A shared rectangle would report a position for a finding no one measured.
    """
    here = [el("1", "Nike", None), el("2", "Nike", bbox(0.7, 0.8))]
    bound = bind_ground_boxes(here, {"Nike": [bbox(0.72, 0.82)]}, 5.0)

    assert list(bound) == ["2"]


def test_a_label_with_no_boxes_is_simply_absent():
    here = [el("1", "Nike", bbox(0.1, 0.2)), el("2", "Adidas", bbox(0.5, 0.6))]
    bound = bind_ground_boxes(here, {"Nike": [bbox(0.1, 0.2)]}, 5.0)

    assert list(bound) == ["1"]


def test_a_measured_label_nobody_here_claims_is_dropped():
    """Grounding locates the findings it was given; it cannot introduce one."""
    here = [el("1", "Nike", bbox(0.1, 0.2))]
    bound = bind_ground_boxes(here, {"Adidas": [bbox(0.5, 0.6)]}, 5.0)

    assert bound == {}
