"""The people the production hired are not the people it has to clear.

Everything else in this codebase looks for other people's property. The cast
is the one thing on screen that belongs to the production already: you cannot
have Bradley Cooper playing Phil Wenneck in your film without a contract with
Bradley Cooper, and a performer agreement is exactly the instrument a right-of-
publicity finding would tell you to go and get.

A live run reported three of them as findings requiring a personal release,
and routed each to a live search for an agent contact. It also wrecked the
overlay: asked to place a named performer on a frame, the model returns the
whole frame — {0, 0, 1, 1} at 6s and again at 9s — so a rectangle covering the
entire video sat on top of every real finding.

The boundary is the whole design, and it is asymmetric on purpose:

    named performer     the production holds the paper. Recorded as a credit,
                        with the guild obligation stated once, and taken out
                        of the clearance list.
    anyone else         still a finding. An extra in a doorway, a passer-by, a
                        face in a crowd — those releases are real work, and
                        the same face is personal data under GDPR, DPDP and
                        LGPD. `routing._route_person` already answers them
                        with a release form rather than a rights lookup.

So this asks for POSITIVE evidence that the scan named a performer, and treats
its absence as "still a finding". Being wrong towards "you still need to clear
this" costs a line in a report. Being wrong the other way deletes the release
you needed.

Faces only. A DRAWN character has no right of publicity and no performer to
release; whether it is covered belongs to `sourcework.subsumed_by`, which
answers it with the medium of the work. Two modules answering one question is
how a tattoo ended up with two verdicts.

Pure code, no I/O.
"""

import re

from clearframe.models import CastCredit, ElementType, TriagedElement

# "Phil Wenneck (Bradley Cooper)" — the form the scan uses when it recognises
# both the part and the performer.
_ATTRIBUTED = re.compile(r"^\s*(?P<part>[^()]+?)\s*\((?P<performer>[^()]+)\)\s*$")

# "...played by actor Ed Helms." Two capitalised words minimum: a full name is
# the evidence, and "played by an extra" names nobody.
_PLAYED_BY = re.compile(
    r"(?:played|portrayed|performed)\s+by\s+(?:the\s+)?(?:actor|actress)?\s*"
    r"(?P<performer>[A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+)+)"
)

# Words that make a parenthetical a stage direction rather than a name.
_NOT_A_NAME = {
    "background", "foreground", "left", "right", "centre", "center", "back",
    "front", "offscreen", "off", "screen", "partial", "obscured", "blurred",
    "reflection", "unnamed", "unidentified", "unknown", "extra", "extras",
    "crowd", "voice", "cameo", "double", "stunt", "young", "older", "adult",
    "child", "boy", "girl", "man", "woman",
}


def _looks_like_a_name(text: str) -> bool:
    """Two or more words, none of them a stage direction.

    One word is not enough. "Alan (Zach)" is a nickname and "Waiter
    (background)" is a camera note; neither identifies a performer well enough
    to assert that somebody signed something.
    """
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    if len(words) < 2:
        return False
    return not any(w.strip(".,'’-").casefold() in _NOT_A_NAME for w in words)


def performer_of(element: TriagedElement) -> tuple[str | None, str] | None:
    """(part, performer) when the scan named who plays this face, else None."""
    if element.element_type is not ElementType.FACE:
        return None

    attributed = _ATTRIBUTED.match(element.label or "")
    if attributed:
        performer = attributed.group("performer").strip()
        if _looks_like_a_name(performer):
            part = attributed.group("part").strip()
            return (part or None, performer)

    played = _PLAYED_BY.search(element.description or "")
    if played:
        # The name runs to the end of a sentence, and the character class has
        # to admit "." for initials, so the full stop comes along with it.
        performer = played.group("performer").strip().rstrip(".,;:")
        if _looks_like_a_name(performer):
            label = (element.label or "").strip()
            part = label if label and label != performer else None
            return (part, performer)
    return None


def is_cast(element: TriagedElement) -> bool:
    return performer_of(element) is not None


def partition(
    elements: list[TriagedElement],
) -> tuple[list[TriagedElement], list[CastCredit]]:
    """Split the triaged list into what must be cleared and who was cast.

    Order is preserved for everything that stays, because the reviewer reads
    the findings list in the order the pipeline built it.
    """
    findings: list[TriagedElement] = []
    credits: list[CastCredit] = []
    for element in elements:
        named = performer_of(element)
        if named is None:
            findings.append(element)
            continue
        part, performer = named
        credits.append(
            CastCredit(
                id=element.id,
                label=element.label,
                character=part,
                performer=performer,
                screen_time_s=element.prominence.screen_time_s,
                basis=(
                    f"The scan identifies this face as {performer}"
                    + (f", playing {part}" if part else "")
                    + ". A credited performer is engaged by the production, so "
                    "the instrument a publicity finding would ask for — a "
                    "signed release — is already part of the cast agreement."
                ),
            )
        )
    return findings, credits


def summarise(credits: list[CastCredit]) -> dict | None:
    """The one paragraph a producer should read instead of N findings."""
    if not credits:
        return None
    return {
        "count": len(credits),
        "performers": [c.performer for c in credits],
        "headline": (
            f"{len(credits)} credited performer(s) recognised on screen. These "
            "are not clearance findings: the production engaged them, so their "
            "consent is a cast agreement rather than a rights lookup."
        ),
        "action": (
            "Confirm the executed performer agreements and any guild paperwork "
            "(SAG-AFTRA or local equivalent) cover this production's media, "
            "territory and term — the same three gaps that catch a music "
            "licence. Anyone on screen who is NOT cast stays in the findings "
            "list and still needs a release."
        ),
    }
