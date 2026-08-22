"""Script-vs-screen drift: what appeared on camera that the script never called for.

Unscripted clearables are set-dressing/wardrobe/location surprises — the
elements nobody budgeted clearance for. FACE elements are excluded (people in
frame aren't script props; publicity releases are a separate workflow).
"""

from clearframe.matching import labels_match as _matches
from clearframe.models import ElementType, ScriptDrift, ScriptMention, TriagedElement


def compute_drift(
    mentions: list[ScriptMention], elements: list[TriagedElement]
) -> ScriptDrift:
    unscripted = [
        el.id
        for el in elements
        if el.element_type != ElementType.FACE
        and not any(_matches(m.label, el.label) for m in mentions)
    ]
    unseen = [
        m.label
        for m in mentions
        if not any(_matches(m.label, el.label) for el in elements)
    ]
    return ScriptDrift(unscripted_element_ids=unscripted, scripted_not_seen=unseen)
