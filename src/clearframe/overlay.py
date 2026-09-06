"""Which box to draw at time T. Pure code, no I/O.

The rule the player needs, in one place so the dossier and the SPA cannot
disagree about it.

A finding that appears four times needs four rectangles. It used to have one,
drawn across every appearance, so the box measured during the opening shot was
painted onto a drawing-room wall three shots later — a confidently wrong
rectangle, which is worse than none because it tells a reviewer the tool found
something there.

Boxes now live inside the appearance. Pause at 1s and you get the first shot's
box; pause at 27s and you get the third's; pause where nothing is on screen and
you get nothing.

Two fallbacks keep older states working rather than silently losing their
boxes on upgrade:

  element bbox + at_s   drawn within TOLERANCE_S of the moment it was measured
  element bbox alone    drawn across the range, which is what it always did

Whichever box wins, it still has to say WHERE. A rectangle around the entire
frame is not a position — see `locates`.
"""

from clearframe.models import BBox, DetectedElement, TimeRange

# How far from a legacy `at_s` a single measured box is still trusted. Two
# seconds is about one shot; beyond that the camera has usually moved.
TOLERANCE_S = 2.0

# A rectangle this large has stopped being a location. At 0.9 the box leaves
# less than a tenth of the picture outside it, so it says only that the element
# is in the shot — which the finding already said — while painting over every
# box beneath it.
#
# It is not hypothetical and it is not evenly distributed. Asked to place a
# named person on a frame, the model returns {0, 0, 1, 1}; asked to place the
# IWC watch in the same shot, it returns the watch to the pixel. So the guard
# is about the answer, not about the subject, and applies wherever a box comes
# from.
MAX_LOCATING_AREA = 0.9


def locates(box: BBox | None) -> bool:
    """Does this rectangle actually say WHERE something is?"""
    if box is None:
        return False
    return (box.xmax - box.xmin) * (box.ymax - box.ymin) < MAX_LOCATING_AREA


def boxes_overlap(a: BBox, b: BBox) -> bool:
    return a.xmin < b.xmax and b.xmin < a.xmax and a.ymin < b.ymax and b.ymin < a.ymax


def iou(a: BBox, b: BBox) -> float:
    """How much two rectangles agree, 0 to 1."""
    if not boxes_overlap(a, b):
        return 0.0
    inter = (min(a.xmax, b.xmax) - max(a.xmin, b.xmin)) * (
        min(a.ymax, b.ymax) - max(a.ymin, b.ymin)
    )
    area_a = (a.xmax - a.xmin) * (a.ymax - a.ymin)
    area_b = (b.xmax - b.xmin) * (b.ymax - b.ymin)
    return inter / (area_a + area_b - inter)


def _centre_gap(a: BBox, b: BBox) -> float:
    ax, ay = (a.xmin + a.xmax) / 2, (a.ymin + a.ymax) / 2
    bx, by = (b.xmin + b.xmax) / 2, (b.ymin + b.ymax) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def bind_ground_boxes(here, located: dict[str, list[BBox]], at_s: float):
    """Attach measured rectangles to the findings that claimed their label.

    Grounding answers per label; the player draws per finding. Where those are
    one to one this is a rename. Where they are not, both directions used to be
    settled by luck.

    One finding, several rectangles: it takes all of them. Pizza Hut on the cap
    and on the box is one trademark and one clearance, seen twice.

    Several findings, one label: each takes at most one rectangle, paired to
    whichever is nearest its own scan box, best agreement first. A finding with
    no box of its own takes none — a shared rectangle would report a position
    nobody measured for it, and showing two findings the same rectangle is how
    they came to look independently confirmed.
    """
    claimants: dict[str, list] = {}
    for el in here:
        claimants.setdefault(el.label, []).append(el)

    out: dict[str, list[BBox]] = {}
    for label, boxes in located.items():
        mine = claimants.get(label) or []
        if not mine or not boxes:
            continue
        if len(mine) == 1:
            out[mine[0].id] = list(boxes)
            continue
        scored = []
        for el in mine:
            guess = box_at(el, at_s)
            if guess is None:
                continue
            for i, b in enumerate(boxes):
                scored.append((iou(guess, b), -_centre_gap(guess, b), el.id, i))
        scored.sort(reverse=True)
        taken_el: set[str] = set()
        taken_box: set[int] = set()
        for _agreement, _gap, eid, i in scored:
            if eid in taken_el or i in taken_box:
                continue
            taken_el.add(eid)
            taken_box.add(i)
            out[eid] = [boxes[i]]
    return out


def _containing(element: DetectedElement, at_s: float) -> TimeRange | None:
    return next(
        (r for r in element.time_ranges if r.start_s <= at_s <= r.end_s), None
    )


def visible_at(element: DetectedElement, at_s: float) -> bool:
    """Is this element on screen at all? Independent of whether we know where."""
    if not element.timing_reliable:
        return False
    return _containing(element, at_s) is not None


def box_at(element: DetectedElement, at_s: float) -> BBox | None:
    """The rectangle to draw at this instant, or None to draw nothing.

    None is a real answer, not a failure: an element can be on screen while
    its position is unknown, and drawing a guess would be worse.
    """
    # Timecodes the scan cannot have measured place a box nowhere real. The
    # finding is kept; the rectangle is not drawn.
    if not element.timing_reliable:
        return None
    appearance = _containing(element, at_s)
    if appearance is None:
        return None
    if appearance.bbox is not None:
        return appearance.bbox if locates(appearance.bbox) else None

    # --- legacy states, in descending order of how much they tell us
    if not locates(element.bbox):
        return None
    if element.at_s is not None:
        return element.bbox if abs(at_s - element.at_s) <= TOLERANCE_S else None
    return element.bbox
