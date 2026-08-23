"""When the footage IS someone else's work, its parts are not separate findings.

Everything else in this codebase asks what is IN the frame. This asks what the
frame IS — and when the answer is "somebody else's film", most of the other
questions stop mattering.

A clip of an existing anime produced eight findings and five separate
multi-minute investigations into C.C., Lelouch, Nunnally, Zero's Mask and
Arthur: five characters from one work, one rights holder, inside footage that
was that work. Six of the seven deep runs returned nothing, and the one that
succeeded answered all of them. The useful output was never eight findings. It
was one: this is Code Geass, clear the work.

Three things are deliberately NOT subsumed, because they carry separate paper:

  a real brand    Pizza Hut paid for that placement in Japan, and the
                  sponsorship did not travel — a licence to the film does not
                  carry the mark
  music           sync and master are separate documents, often separate
                  holders, sometimes not owned by the studio at all
  a real person   a release is signed by the person, not the studio

And it takes certainty. Wrongly deciding the footage is someone else's work
would suppress every finding inside it, so a low-confidence guess subsumes
nothing.

Pure code, no I/O.
"""

from clearframe.models import (
    ClearanceCategory,
    ElementType,
    SourceWork,
    TriagedElement,
)

# Categories whose rights travel with the work itself. Everything else has its
# own counterparty and its own piece of paper.
_SUBSUMABLE = {ClearanceCategory.COPYRIGHT_ART, ClearanceCategory.TEXT_ON_SCREEN}

_CONFIDENT = {"high", "medium"}


def subsumed_by(element: TriagedElement, work: SourceWork | None) -> bool:
    """Is this finding just a part of the identified work?"""
    if work is None or work.confidence not in _CONFIDENT or not work.title:
        return False
    # A drawn character is the studio's design by definition.
    if element.element_type is ElementType.CHARACTER:
        return True
    return element.category in _SUBSUMABLE


def summarise_source_work(
    work: SourceWork | None, elements: list[TriagedElement]
) -> dict | None:
    """The headline a producer should read before any individual finding."""
    if work is None or work.confidence not in _CONFIDENT or not work.title:
        return None
    subsumed = [e for e in elements if subsumed_by(e, work)]
    independent = [e for e in elements if not subsumed_by(e, work)]
    holder = work.rights_holder or "the rights holder"
    return {
        "title": work.title,
        "rights_holder": work.rights_holder,
        "confidence": work.confidence,
        "basis": work.basis,
        "subsumed": len(subsumed),
        "independent": len(independent),
        "headline": (
            f"This footage appears to BE '{work.title}', not merely to contain "
            f"parts of it. {len(subsumed)} finding(s) are elements of that work "
            f"and are covered by whatever licence you hold to it."
        ),
        "action": (
            f"Obtain a licence to '{work.title}' from {holder}. Clearing its "
            "individual characters, set dressing or on-screen text separately "
            "is not possible and not necessary — they are not separately "
            "licensable."
        ),
        "caveat": (
            f"{len(independent)} finding(s) are NOT covered by that licence and "
            "still need clearing on their own: real brands placed inside the "
            "work, music, and identifiable real people each carry separate paper."
        ),
    }
