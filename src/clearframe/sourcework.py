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

from clearframe.matching import labels_match
from clearframe.models import (
    ClearanceCategory,
    DetectedElement,
    ElementType,
    SourceWork,
    TriagedElement,
)

# Categories whose rights travel with the work itself. Everything else has its
# own counterparty and its own piece of paper.
_SUBSUMABLE = {ClearanceCategory.COPYRIGHT_ART, ClearanceCategory.TEXT_ON_SCREEN}

_CONFIDENT = {"high", "medium"}

# Only a drawn work authors what is on screen. This is the whole of the
# distinction, and getting it wrong is not symmetrical: over-subsuming tells a
# producer they are covered when they are not.
_STUDIO_AUTHORED = {"animation"}


def subsumed_by(element: TriagedElement, work: SourceWork | None) -> bool:
    """Is this finding just a part of the identified work?

    Only in a drawn work. There, the studio drew the characters, the props and
    the background, so an element of the work genuinely is covered by a licence
    to the work. Live action inverts it: the camera photographs a world full of
    other people's property, which is why clearance departments exist at all.

    Whitmill v. Warner Bros. settles it. Warner Bros. MADE The Hangover Part II
    and was still sued over the tattoo on Stu's face — and still faced a
    preliminary-injunction motion weeks before release. "Covered by your licence
    to the film" would have been exactly the wrong advice, in the one direction
    this product must never be wrong in.
    """
    if work is None or work.confidence not in _CONFIDENT or not work.title:
        return False
    if work.medium not in _STUDIO_AUTHORED:
        return False
    # A drawn character is the studio's design by definition.
    if element.element_type is ElementType.CHARACTER:
        return True
    return element.category in _SUBSUMABLE


def corrected_types(
    detections: list[DetectedElement], work: SourceWork | None
) -> list[DetectedElement]:
    """The medium decides what kind of thing a person on screen is.

    Two corrections, one in each direction, both gated on a medium the scan
    identified and neither applied when it did not.

    CHARACTER exists for a specific legal reason: a drawn character has no
    right of publicity, because there is nobody to consent, and the right that
    does exist is copyright in the design. Applied to a live actor it inverts —
    Bradley Cooper stops needing a personal release and becomes a drawing
    somebody owns.

    The scan prompt already says to use FACE for a real person. It is obeyed
    intermittently: across three identical runs of one clip, one typed all
    three actors CHARACTER, one typed them FACE, one found no people. A prompt
    is not a contract.

    Only corrected where it can be proven — a work the scan identified as
    live_action cannot have a drawn character playing its lead. An unknown
    medium changes nothing.

    The drawn direction is handled by `_drawn_faces_are_characters` and is
    deliberately narrower: it settles a disagreement between two passes rather
    than reclassifying every face in an animation.
    """
    if work is None:
        return detections
    if work.medium == "live_action":
        return [
            d.model_copy(update={"element_type": ElementType.FACE})
            if d.element_type is ElementType.CHARACTER
            else d
            for d in detections
        ]
    if work.medium in _STUDIO_AUTHORED:
        return _drawn_faces_are_characters(detections)
    return detections


def _drawn_faces_are_characters(
    detections: list[DetectedElement],
) -> list[DetectedElement]:
    """The mirror image, and deliberately narrower than its reflection.

    A live Code Geass run reported the same cartoon twice:

        CHARACTER  "Pizza Hut Delivery Driver"   an element of the work
        FACE       "Pizza Hut Delivery Driver"   obtain a personal release

    One drawn delivery driver, two findings, two contradictory answers to the
    only question that matters — and `triage` cannot join them, because
    grouping needs one element type and both of these are rights-bearing.

    Only a FACE that another detection in the SAME scan already called a
    CHARACTER is corrected. That is a disagreement between two passes about
    one object, and settling it invents nothing. A lone face is left as it is:
    a drawn work can contain a photograph of a real person, CHARACTER is
    subsumable by a licence to the work, and a blanket rule would therefore
    risk suppressing a release that was genuinely needed. Narrow costs a
    duplicate; broad costs a finding.
    """
    drawn = [d.label for d in detections if d.element_type is ElementType.CHARACTER]
    if not drawn:
        return detections
    return [
        d.model_copy(update={"element_type": ElementType.CHARACTER})
        if d.element_type is ElementType.FACE
        and any(labels_match(d.label, c) for c in drawn)
        else d
        for d in detections
    ]


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
