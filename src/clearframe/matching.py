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


# Corporate furniture that carries no identifying signal. Matching rights
# holders on these produces confident false positives, and a false licence
# match is the most dangerous error the ledger can make: it tells a producer
# they are covered when they are not.
#
# Found the hard way. "Kobalt Music Group" matched an owner string reading
# "... Universal Music Group (master); Universal Music Publishing Group
# (composition)" on the shared tokens {music, group} alone — 2 of 3 tokens,
# comfortably over threshold — and a festival-only cue licence was reported as
# covering a Weeknd master.
_CORPORATE_NOISE = {
    "inc", "inc.", "incorporated", "llc", "l.l.c", "ltd", "ltd.", "limited",
    "corp", "corp.", "corporation", "co", "co.", "company", "companies",
    "group", "holdings", "holding", "plc", "sa", "s.a", "ag", "gmbh", "nv",
    "n.v", "bv", "b.v", "spa", "s.p.a", "ab", "as", "oy", "kk", "pty",
    "music", "records", "recording", "recordings", "entertainment", "media",
    "publishing", "publishers", "productions", "pictures", "studios",
    "international", "worldwide", "global", "and", "the",
}


def identity_tokens(label: str) -> set[str]:
    """Tokens that actually identify an organisation.

    Falls back to the full token set when stripping would leave nothing — a
    holder genuinely named "The Music Company" should still match itself.
    """
    full = tokens(label)
    distinctive = {t for t in full if t not in _CORPORATE_NOISE}
    return distinctive or full


def holders_match(a: str, b: str, threshold: float = MATCH_THRESHOLD) -> bool:
    """Do two strings name the same rights holder?

    Stricter than `labels_match`: comparison runs over identifying tokens only,
    so shared corporate furniture cannot carry a match on its own.
    """
    ta, tb = identity_tokens(a), identity_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= threshold
