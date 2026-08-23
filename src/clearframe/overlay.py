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
"""

from clearframe.models import BBox, DetectedElement, TimeRange

# How far from a legacy `at_s` a single measured box is still trusted. Two
# seconds is about one shot; beyond that the camera has usually moved.
TOLERANCE_S = 2.0


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
        return appearance.bbox

    # --- legacy states, in descending order of how much they tell us
    if element.bbox is None:
        return None
    if element.at_s is not None:
        return element.bbox if abs(at_s - element.at_s) <= TOLERANCE_S else None
    return element.bbox
