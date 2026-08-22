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


# Legal-entity furniture. "Bayer Aspirin" and "Bayer Corporation" name the same
# brand; the suffix is paperwork, not identity.
#
# Found on a live run of a 1950s Bayer spot. Cloud Video Intelligence returned
# "Bayer Corporation" three times at ~0.87 confidence — correct agreement — but
# {bayer, aspirin} against {bayer, corporation} scores 1/2 = 0.5, under the 0.6
# threshold, so the agreement was rejected. A single spurious "Wake Forest Demon
# Deacons" hit then made the identity CONFLICTED, and research was blocked on
# the only confidently identified brand in the clip. A FALSE conflict is worse
# than no corroboration: it stops the pipeline on a correct answer.
_LEGAL_SUFFIXES = {
    "inc", "inc.", "incorporated", "llc", "l.l.c", "ltd", "ltd.", "limited",
    "corp", "corp.", "corporation", "co", "co.", "company", "companies",
    "group", "holdings", "holding", "plc", "sa", "s.a", "ag", "gmbh", "nv",
    "n.v", "bv", "b.v", "spa", "s.p.a", "ab", "as", "oy", "kk", "pty", "and",
    "the",
}

# Industry descriptors, stripped only when matching RIGHTS HOLDERS. Half the
# music business shares them, so a ledger that matched on them reported a
# festival-only Kobalt cue licence as covering a Universal master. They are NOT
# stripped for brand identity, where "Warner Music" and "Warner Bros." must stay
# distinct.
_INDUSTRY_WORDS = {
    "music", "records", "recording", "recordings", "entertainment", "media",
    "publishing", "publishers", "productions", "pictures", "studios",
    "international", "worldwide", "global",
}


def _strip(label: str, vocab: set[str]) -> set[str]:
    """Tokens minus `vocab`, falling back to the full set if that empties it.

    The fallback matters: an organisation genuinely named "The Music Company"
    must still match itself.
    """
    full = tokens(label)
    return {t for t in full if t not in vocab} or full


def identity_tokens(label: str) -> set[str]:
    """Tokens that identify an organisation, for rights-holder comparison."""
    return _strip(label, _LEGAL_SUFFIXES | _INDUSTRY_WORDS)


def _overlap(ta: set[str], tb: set[str], threshold: float) -> bool:
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= threshold


def holders_match(a: str, b: str, threshold: float = MATCH_THRESHOLD) -> bool:
    """Do two strings name the same rights holder?

    The strictest of the three: shared corporate furniture cannot carry a match
    on its own. Being wrong in the "covered" direction is the one failure the
    rights ledger must not have.
    """
    return _overlap(identity_tokens(a), identity_tokens(b), threshold)


def marks_match(a: str, b: str, threshold: float = MATCH_THRESHOLD) -> bool:
    """Do a detected label and a catalogue label name the same brand?

    Looser than `holders_match` — only legal-entity suffixes are discounted, so
    industry words still distinguish "Warner Music" from "Warner Bros." Used for
    identity corroboration, where a false CONFLICTED blocks research on a
    correct answer and is worse than no corroboration at all.
    """
    return _overlap(_strip(a, _LEGAL_SUFFIXES), _strip(b, _LEGAL_SUFFIXES), threshold)
