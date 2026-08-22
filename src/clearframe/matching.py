"""Shared label matching for cross-source comparison.

Two independent sources rarely spell an element the same way — Gemini writes
"Nike hoodie swoosh", a logo detector writes "Nike". Script drift and identity
corroboration both need the same judgement about whether two labels name the
same thing, so the rule lives in exactly one place.
"""

_STOPWORDS = {"the", "a", "an", "of", "on", "in", "-", "—"}

MATCH_THRESHOLD = 0.6


def tokens(label: str) -> set[str]:
    cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in label.casefold())
    return {t for t in cleaned.split() if t and t not in _STOPWORDS}


def labels_match(a: str, b: str, threshold: float = MATCH_THRESHOLD) -> bool:
    """True when the shorter label's tokens are mostly contained in the longer."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb)
    return overlap / min(len(ta), len(tb)) >= threshold
