"""Script-vs-screen drift: what appeared on camera that the script never called for.

Unscripted clearables are set-dressing/wardrobe/location surprises — the
elements nobody budgeted clearance for. FACE elements are excluded (people in
frame aren't script props; publicity releases are a separate workflow).
"""

from clearframe.models import ElementType, ScriptDrift, ScriptMention, TriagedElement

_STOPWORDS = {"the", "a", "an", "of", "on", "in", "-", "—"}


def _tokens(label: str) -> set[str]:
    cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in label.casefold())
    return {t for t in cleaned.split() if t and t not in _STOPWORDS}


def _matches(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb)
    return overlap / min(len(ta), len(tb)) >= 0.6


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
