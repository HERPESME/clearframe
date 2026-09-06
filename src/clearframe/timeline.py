"""Whether the scan's timecodes can be believed at all. Pure code, no I/O.

Every other check in this codebase asks whether a finding is *right*. This one
asks whether its numbers are *possible* — and a number that is impossible is
not a close call, so this module makes no judgement and guesses nothing.

On a live clip of The Hangover Part II, Gemini reported Stu's face tattoo as
six appearances totalling 0.15 seconds — each 20-30ms, shorter than a single
frame at 24fps — while reporting in the same response that the tattoo was on
screen for 10 seconds. The other seven findings reconciled exactly, 1.0x. One
element's timeline had come back in a different unit.

That is invisible in the analysis and maddening in the player: the finding
lists with timecodes, and there is no box at any instant a human hand can pause
on, because a 20ms window cannot be hit with a mouse. The user sees a detection
they cannot verify and reasonably concludes the tool is wrong.

We deliberately do NOT repair the unit. Two candidate scales — minutes, and
fraction-of-clip — both land inside the clip, so choosing between them would be
picking, and `overlay.py` states the rule this codebase runs on: a confidently
wrong rectangle is worse than none. What we can do is prove the numbers cannot
be what they claim, keep the finding, and say so.

The tests here are physical, not statistical. A sighting shorter than one frame
was never photographed. A sighting after the last frame was never photographed
either. Neither needs a threshold anyone has to defend.
"""

from clearframe.models import DetectedElement

# A clip whose duration was never probed. `media.probe_duration_s` returns 0.0
# rather than raising, and states written before it exists carry 0.0 too, so an
# unknown duration must never be evidence against a finding.
_UNKNOWN_DURATION = 0.0

# Floating point from a JSON model, not a measurement. One millisecond of slack
# keeps a range that ends exactly on the last frame from being condemned.
_EPSILON_S = 0.001

_DEFAULT_FPS = 24.0


def _frame_duration_s(fps: float) -> float:
    return 1.0 / (fps if fps > 0 else _DEFAULT_FPS)


# How far past the last frame an end time may be and still be read as rounding.
#
# One second, and it rests on a single observation, which is stated rather than
# hidden: a live run reported `Bangkok Hotel Room` ending at 41.60s in a 41.50s
# clip. That finding spanned the whole scene, and disowning it cost it its place
# on the timeline and every rectangle it had — over a tenth of a second.
#
# Clamping is deliberately NOT the unit repair this module refuses. Choosing
# between minutes and fraction-of-clip means picking one of two answers that
# both land inside the clip, and `overlay.py`'s rule is that a confidently wrong
# answer is worse than none. Saying that an appearance running past the end of
# the footage ends at the end of the footage is not a choice: the last frame is
# the last frame. Beyond a second, though, the number is not a rounded one — it
# is a different number — so it goes back to being disowned.
CLAMP_TOLERANCE_S = 1.0


def clamp_to_footage(element: DetectedElement, duration_s: float) -> DetectedElement:
    """Pull an end time that overshoots the last frame back onto it.

    Returns the element untouched when there is nothing to do, which is the
    overwhelmingly common case. Never clamps a range that *begins* after the
    last frame: the result would be `end_s <= start_s`, which is not an
    appearance at all, and a range that starts outside the footage is a genuine
    contradiction for `timing_is_reliable` to catch.
    """
    if duration_s <= _UNKNOWN_DURATION:
        return element
    ranges = element.time_ranges
    if not ranges:
        return element
    if not any(
        duration_s + _EPSILON_S < r.end_s <= duration_s + CLAMP_TOLERANCE_S
        and r.start_s < duration_s - _EPSILON_S
        for r in ranges
    ):
        return element
    return element.model_copy(
        update={
            "time_ranges": [
                r.model_copy(update={"end_s": duration_s})
                if (
                    duration_s + _EPSILON_S
                    < r.end_s
                    <= duration_s + CLAMP_TOLERANCE_S
                    and r.start_s < duration_s - _EPSILON_S
                )
                else r
                for r in ranges
            ]
        }
    )


def timing_is_reliable(
    element: DetectedElement, duration_s: float, fps: float
) -> tuple[bool, str]:
    """Can this finding's timecodes be believed?

    Returns (reliable, reason). `reason` is empty when they can be, and carries
    the contradiction when they cannot — a dossier reader needs the evidence,
    not a verdict.
    """
    ranges = element.time_ranges
    if not ranges:
        return False, "The scan reported no timecodes for this finding."

    frame_s = _frame_duration_s(fps)
    shortest = min(r.duration_s for r in ranges)
    if shortest < frame_s - _EPSILON_S:
        claimed = element.prominence.screen_time_s
        total = sum(r.duration_s for r in ranges)
        return False, (
            f"The scan reported an appearance lasting {shortest * 1000:.0f}ms, "
            f"shorter than a single frame at {fps:g}fps ({frame_s * 1000:.0f}ms), "
            f"starting at {ranges[0].start_s:g}s. Its {len(ranges)} appearances "
            f"total {total:.2f}s against the {claimed:g}s of screen time reported "
            "for the same finding, so the timecodes are in the wrong unit. The "
            "finding stands; only its timing is unusable."
        )

    if duration_s > _UNKNOWN_DURATION:
        last = max(r.end_s for r in ranges)
        if last > duration_s + _EPSILON_S:
            return False, (
                f"The scan reported an appearance ending at {last:.2f}s in a clip "
                f"that is {duration_s:.2f}s long. The finding stands; only its "
                "timing is unusable."
            )

    return True, ""
