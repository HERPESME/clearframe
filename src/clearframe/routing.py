"""The escalation ladder: resolve each finding at the cheapest rung that can answer it.

A 21.8-second clip took twenty minutes. The cause was not detection — it was
sending all sixteen findings to Parallel's deep-research Task API, the most
expensive tool in the system. Six returned no owner at all. Seven were human
faces, and no amount of web research produces a release form.

The fix is not to detect less. Recall is this product's entire safety claim,
and the cases prove it: the Hangover II tattoo, a mural on a parking garage,
a poster on a sitcom wall. The fix is to stop confusing "we must report this"
with "we must pay for deep research about this".

  LOCAL    local rights table          0 ms      $0        who owns a famous mark
  STATUTE  deterministic law           0 ms      $0        de minimis, release, own content
  SEARCH   Parallel Search            ~2 s       $0.005    posture, contact, live signals
  DEEP     Parallel Task              minutes    $0.01+    genuinely unknown ownership

The routing table below is derived from the litigation record rather than from
our category enum, and two findings from that record shape it:

1. Risk is INVERTED relative to where detection effort usually goes. Brand
   owners mostly lose against productions (Rogers v. Grimaldi; Caterpillar v.
   Disney; Wham-O v. Paramount), while music publishers reliably win. So a
   famous logo deserves a two-second lookup and a song deserves the deep run.

2. For trademark the risk variable is not identity but DEPICTION. Wham-O lost
   because exaggeration made endorsement implausible; NBC digitally erased
   In-Sink-Erator from Heroes only because the scene was unflattering. Which
   is why a catalogued mark still gets a live posture check rather than being
   waved through on the strength of a static table.

Every cheap route carries a `disposition` and a `basis`, because E&O carriers
do not accept fair use offered in place of clearance and distributors reject
"incidental use" without documentation. A finding resolved for free must still
appear in the dossier as a documented position — never as a silent skip.

Pure code, no I/O, no LLM. Same contract as `scoring.py` and `territory.py`.
"""

from clearframe.knowledge import KnowledgeBase
from clearframe.matching import tokens
from clearframe.scoring import provisional_score
from clearframe.models import (
    ClearanceCategory,
    Corroboration,
    IdentityVerdict,
    LicensingPosture,
    Prominence,
    ResearchRoute,
    ResearchTier,
    TriagedElement,
)

SEARCH_COST_USD = 0.005
SEARCH_LATENCY_S = 2.0
DEEP_LATENCY_S = 180.0

# A finding this exposed gets the full treatment regardless of how cheaply its
# category could otherwise be resolved. Matches the HIGH band in `scoring.py`.
#
# Cheapest-that-can-answer is the right default, but it is not the right rule
# for the two or three findings that will actually sink the delivery. Those
# need what only a deep run produces: a licensing contact, a cost band, and
# citations an underwriter can follow. Speed is worth having everywhere except
# where the money is.
MATERIALITY_ESCALATION_SCORE = 45

# --- vocabularies ----------------------------------------------------------

# A person with no name. There is no rights holder to research: the clearance
# instrument is a release form or a crowd notice, obtained on set or in post.
_ANONYMOUS = {
    "background", "passerby", "passer", "by", "audience", "crowd", "extra",
    "extras", "bystander", "bystanders", "unnamed", "unidentified", "anonymous",
    "member", "members", "pedestrian", "pedestrians", "onlooker", "onlookers",
    "spectator", "spectators", "patron", "patrons", "customer", "customers",
    "unknown", "face", "faces", "person", "people", "man", "woman", "men",
    "women", "guy", "girl", "boy", "child", "kid", "figure", "silhouette",
}

# Graphics the production made itself. Its own copyright; nothing to clear.
_OWN_CONTENT = {
    "overlay", "overlays", "caption", "captions", "subtitle", "subtitles",
    "credits", "chyron", "watermark", "lower", "third", "supers", "super",
    "titlecard", "slate", "bug",
}
_OWN_CONTENT_PHRASES = (
    "title card", "end card", "thank you", "call to action", "subscribe",
    "narrative text", "opening title", "closing title", "our logo",
)

# Interface furniture. Not authored expression, not a mark.
_GENERIC_UI = {
    "timestamp", "timecode", "battery", "wifi", "signal", "menu", "button",
    "ui", "interface", "notification", "notifications", "cursor", "icon",
    "icons", "hud", "clock", "scrollbar", "toolbar", "keypad", "indicator",
}

# Places with no protectable identity: no trade dress, no location agreement.
_GENERIC_PLACE = {
    "generic", "street", "streets", "sidewalk", "pavement", "road", "roads",
    "park", "room", "office", "interior", "exterior", "alley", "hallway",
    "corridor", "field", "forest", "beach", "sky", "parking", "lot", "garage",
    "apartment", "house", "kitchen", "bedroom", "bathroom", "city", "town",
    "downtown", "urban", "rural", "building", "buildings", "wall", "store",
    "shop", "restaurant", "cafe", "bar", "stairwell", "lobby", "rooftop",
    "landscape", "countryside", "highway", "intersection", "crosswalk",
}

# Useful articles. 17 U.S.C. §101 protects a useful article's design only to the
# extent of pictorial, graphic or sculptural features separable from its utility
# — Star Athletica v. Varsity Brands, 580 U.S. 405 (2017). A plain vase, a chair,
# a lamp is not a work of authorship and there is nobody to clear with.
#
# Found on a live run: a 1950s Bayer spot produced "Flower Vase" and "Second
# Flower Vase" as ARTWORK, and both were dispatched to deep rights research.
#
# Deliberately narrow. Paintings, posters, photographs, sculptures and murals
# are NOT here at any prominence: Ringgold v. BET turned on a poster hanging on
# a wall, and quietly downgrading authored images is the failure this product
# exists to prevent.
_UTILITARIAN = {
    "vase", "vases", "pot", "pots", "planter", "plant", "plants", "flower",
    "flowers", "bouquet", "furniture", "chair", "chairs", "sofa", "couch",
    "table", "tables", "desk", "lamp", "lamps", "shelf", "shelves", "curtain",
    "curtains", "blind", "blinds", "rug", "carpet", "cushion", "cushions",
    "pillow", "pillows", "blanket", "towel", "dish", "dishes", "plate",
    "plates", "bowl", "bowls", "cup", "cups", "mug", "glass", "glasses",
    "cutlery", "utensil", "utensils", "tray", "jug", "kettle", "pan", "pot",
    "clock", "mirror", "candle", "candles", "ornament", "vessel", "basket",
    "crockery", "tableware", "glassware", "houseplant", "fern", "orchid",
    # qualifiers that do not make an object distinctive
    "second", "third", "another", "additional", "further", "other", "more",
    "small", "large", "plain", "simple", "blank", "unmarked", "undecorated",
    "generic", "background", "foreground", "white", "black", "wooden", "wood",
    "ceramic", "metal", "silver", "brass", "empty", "set", "dressing", "prop",
    "props", "decor", "decorative", "decoration", "arrangement", "display",
}

# Art whose author is not on the face of the work. The Falkner profile.
_UNATTRIBUTED = {
    "unknown", "unidentified", "unattributed", "unsigned", "anonymous",
    "mural", "murals", "graffiti", "street", "tag", "tags", "wheatpaste",
}

_STOPWORDS = {"a", "an", "the", "of", "and", "or", "in", "on", "with", "for", "to", "s"}


def _meaningful(label: str) -> list[str]:
    return [t for t in tokens(label) if t not in _STOPWORDS]


def _any_token(label: str, vocab: set[str]) -> bool:
    return any(t in vocab for t in _meaningful(label))


def _all_tokens(label: str, vocab: set[str]) -> bool:
    words = _meaningful(label)
    return bool(words) and all(t in vocab for t in words)


def is_de_minimis(p: Prominence) -> bool:
    """Sandoval v. New Line: brief, small, peripheral and not the subject.

    Identical thresholds to `scoring.de_minimis` on purpose — one definition,
    so the route a finding took and the band it received cannot disagree.
    """
    return (
        p.screen_time_s < 2.0
        and p.frame_coverage < 0.05
        and p.centrality < 0.3
        and not p.plot_integral
    )


def is_own_content(label: str, description: str = "") -> bool:
    haystack = f"{label} {description}".casefold()
    if any(phrase in haystack for phrase in _OWN_CONTENT_PHRASES):
        return True
    return _any_token(label, _OWN_CONTENT)


# --- routes ----------------------------------------------------------------


def _local(el, owner, posture, evidence) -> ResearchRoute:
    return ResearchRoute(
        element_id=el.id,
        tier=ResearchTier.LOCAL,
        owner=owner,
        posture=posture,
        rationale=(
            "Owner and licensing posture are both known locally with a citation; "
            "no network call can improve on that."
        ),
        basis=evidence,
        disposition=f"Seek clearance from {owner}.",
    )


def _statute(el, rationale, basis, disposition) -> ResearchRoute:
    return ResearchRoute(
        element_id=el.id,
        tier=ResearchTier.STATUTE,
        rationale=rationale,
        basis=basis,
        disposition=disposition,
    )


def _search(el, rationale, *, owner=None, disposition="") -> ResearchRoute:
    return ResearchRoute(
        element_id=el.id,
        tier=ResearchTier.SEARCH,
        owner=owner,
        rationale=rationale,
        disposition=disposition,
        est_cost_usd=SEARCH_COST_USD,
        est_latency_s=SEARCH_LATENCY_S,
    )


def _deep(el, rationale, *, basis="", enumerate_candidates=False) -> ResearchRoute:
    return ResearchRoute(
        element_id=el.id,
        tier=ResearchTier.DEEP,
        rationale=rationale,
        basis=basis,
        enumerate_candidates=enumerate_candidates,
        est_cost_usd=0.0,  # filled from the processor tier by the planner
        est_latency_s=DEEP_LATENCY_S,
    )


# --- per-category rules ----------------------------------------------------


def _route_trademark(el: TriagedElement, kb: KnowledgeBase) -> ResearchRoute:
    mark = kb.find_mark(el.label)
    if mark is None:
        return _deep(
            el,
            "Mark is not in the local catalogue, so ownership genuinely requires "
            "an open-web investigation — registries, corporate filings, assignments.",
        )
    if mark.has_cited_posture:
        return _local(el, mark.owner, mark.posture, mark.posture_evidence)
    return _search(
        el,
        f"Ownership resolved locally ({mark.owner}); a live search establishes "
        "current licensing posture and the contact route. Posture is the variable "
        "a static table cannot know, and for trademark it is the variable that "
        "decides risk — brand owners sue over unflattering depiction, not presence.",
        owner=mark.owner,
        disposition=f"Confirm posture, then approach {mark.owner} if depiction is unflattering.",
    )


def _route_music(el: TriagedElement, corroboration: Corroboration | None) -> ResearchRoute:
    fingerprinted = (
        corroboration is not None
        and corroboration.verdict is IdentityVerdict.FINGERPRINTED
    )
    if fingerprinted:
        return _search(
            el,
            "Recording identified by acoustic fingerprint, so the remaining "
            "unknowns are posture and the two licensing contacts (composition "
            "and master) — a search answers both in seconds.",
            disposition=(
                "Clear BOTH the synchronisation licence from the publisher and the "
                "master-use licence from the label. One without the other is the "
                "most common music clearance failure."
            ),
        )
    return _deep(
        el,
        "Music is the category productions reliably lose, and this recording is "
        "unidentified — no fingerprint match. Publisher and master chains are "
        "genuinely multi-hop, which is exactly what a deep run is for.",
        basis="NMPA v. Fullscreen (2013); Bridgeport v. Dimension Films, 410 F.3d 792 (6th Cir. 2005)",
    )


def _route_art(el: TriagedElement) -> ResearchRoute:
    if _all_tokens(el.label, _UTILITARIAN):
        return _statute(
            el,
            "A useful article, not a work of authorship. There is no author to "
            "identify and no rights holder to clear with — researching it spends "
            "a deep run to discover that a vase is a vase.",
            "17 U.S.C. §101 (useful articles); Star Athletica v. Varsity Brands, "
            "580 U.S. 405 (2017) — protection extends only to separable artistic features",
            "No action, unless the piece carries separable artwork or a designer "
            "mark, in which case reclassify it and re-run.",
        )
    if is_de_minimis(el.prominence):
        return _statute(
            el,
            "Brief, small, peripheral and not the subject of the shot.",
            "Sandoval v. New Line Cinema, 147 F.3d 215 (2d Cir. 1998)",
            "Record a de minimis position in the E&O file. Carriers do not accept "
            "fair use in place of clearance, so the memo must be written down, not assumed.",
        )
    if _any_token(el.label, _UNATTRIBUTED):
        return _deep(
            el,
            "Material artwork with no author on the face of the work. This is the "
            "highest-value visual clearance risk and the one case where exhaustive "
            "open-web enumeration genuinely pays.",
            basis="Falkner v. General Motors (C.D. Cal. 2018) — the US architectural "
            "exemption, 17 U.S.C. §120(a), does not cover art painted on a building",
            enumerate_candidates=True,
        )
    return _deep(
        el,
        "For artwork, 'who owns this' IS the question, and a two-second search "
        "cannot answer it: a poster's rights can sit with the band, the label, "
        "the photographer or the designer. Ownership chains for authored images "
        "are multi-hop by nature, which is what a deep run is for.",
        basis="Ringgold v. Black Entertainment Television, 126 F.3d 70 (2d Cir. 1997) "
        "— recognisable background artwork is not de minimis",
    )


def _route_person(el: TriagedElement) -> ResearchRoute:
    if _any_token(el.label, _ANONYMOUS):
        return _statute(
            el,
            "An unnamed individual has no discoverable rights holder. Research "
            "cannot produce the instrument this needs.",
            "Right of publicity — cleared by consent, not by ownership research",
            "Obtain a personal release, or blur. If shot in a public place under a "
            "crowd notice, file the notice against this finding.",
        )
    return _search(
        el,
        "A named individual is cleared through their representation, so the useful "
        "answer is a current agent or estate contact — not a rights lookup.",
        disposition="Obtain a likeness release via the individual's agent or estate.",
    )


def _route_location(el: TriagedElement) -> ResearchRoute:
    if _all_tokens(el.label, _GENERIC_PLACE) or _any_token(el.label, {"generic"}):
        return _statute(
            el,
            "A generic place carries no protectable trade dress and no identifiable "
            "owner to clear with.",
            "No protectable identity",
            "Confirm a location agreement exists for the shoot day; nothing to research.",
        )
    return _search(
        el,
        "A named venue may carry trade dress or a filming policy; a search finds "
        "the operator and their terms.",
        disposition="Confirm the location agreement covers the distribution media.",
    )


def _route_text(el: TriagedElement, kb: KnowledgeBase) -> ResearchRoute:
    if is_own_content(el.label, el.description):
        return _statute(
            el,
            "This is the production's own graphic. Its copyright already belongs "
            "to the production.",
            "Own work — no third-party right implicated",
            "No action. Recorded so the dossier is complete, not because it is a risk.",
        )
    mark = kb.find_mark(el.label)
    if mark is not None:
        return _route_trademark(el, kb)
    if _all_tokens(el.label, _GENERIC_UI) or _any_token(el.label, _GENERIC_UI):
        return _statute(
            el,
            "Interface furniture is neither authored expression nor a mark.",
            "Not protectable subject matter",
            "No action.",
        )
    return _search(
        el,
        "Readable text that is not ours and not catalogued — a search settles "
        "cheaply whether it is a live mark.",
        disposition="Verify whether the wording is a registered mark before locking.",
    )


_ROUTERS = {
    ClearanceCategory.TRADEMARK: lambda el, kb, corr: _route_trademark(el, kb),
    ClearanceCategory.MUSIC_SYNC: lambda el, kb, corr: _route_music(el, corr),
    ClearanceCategory.COPYRIGHT_ART: lambda el, kb, corr: _route_art(el),
    ClearanceCategory.RIGHT_OF_PUBLICITY: lambda el, kb, corr: _route_person(el),
    ClearanceCategory.LOCATION: lambda el, kb, corr: _route_location(el),
    ClearanceCategory.TEXT_ON_SCREEN: lambda el, kb, corr: _route_text(el, kb),
}


def route(
    element: TriagedElement,
    knowledge: KnowledgeBase,
    corroboration: Corroboration | None = None,
    escalate_material: bool = True,
) -> ResearchRoute:
    """Decide how one finding gets resolved. Deterministic and reproducible."""
    if corroboration is not None and corroboration.verdict is IdentityVerdict.CONFLICTED:
        return ResearchRoute(
            element_id=element.id,
            tier=ResearchTier.BLOCKED,
            rationale=(
                "Two independent detectors named different things. Research asks "
                "'who owns THIS', and we do not yet agree on what THIS is — "
                "researching would attribute rights to the wrong holder."
            ),
            basis="Identity conflict",
            disposition="A human resolves identity before any research runs.",
        )
    chosen = _ROUTERS[element.category](element, knowledge, corroboration)

    if (
        escalate_material
        and chosen.tier is ResearchTier.SEARCH
        and provisional_score(element) >= MATERIALITY_ESCALATION_SCORE
    ):
        score = provisional_score(element)
        return chosen.model_copy(
            update={
                "tier": ResearchTier.DEEP,
                "rationale": (
                    f"Escalated to deep research: provisional exposure is {score}, "
                    f"at or above the HIGH band. {chosen.rationale} A finding this "
                    "prominent needs a licensing contact, a cost band and citations "
                    "an underwriter can follow — which only a deep run produces."
                ),
                "est_cost_usd": 0.0,
                "est_latency_s": DEEP_LATENCY_S,
            }
        )
    return chosen


def route_all(
    elements: list[TriagedElement],
    knowledge: KnowledgeBase,
    corroboration: dict[str, Corroboration] | None = None,
    escalate_material: bool = True,
) -> dict[str, ResearchRoute]:
    corroboration = corroboration or {}
    return {
        el.id: route(el, knowledge, corroboration.get(el.id), escalate_material)
        for el in elements
    }


def summarise_routes(routes: dict[str, ResearchRoute]) -> dict:
    """Producer-facing summary — and the honesty guardrail.

    `resolved_without_research` is the class that must be visible in the
    dossier. A faster tool that quietly examines less is the failure this
    codebase has refused at every prior step.
    """
    counts = {tier.value: 0 for tier in ResearchTier}
    for r in routes.values():
        counts[r.tier.value] += 1

    deep = [r for r in routes.values() if r.tier is ResearchTier.DEEP]
    free = [
        r
        for r in routes.values()
        if r.tier in (ResearchTier.LOCAL, ResearchTier.STATUTE)
    ]
    est_cost = sum(r.est_cost_usd for r in routes.values())
    est_latency = max((r.est_latency_s for r in routes.values()), default=0.0)

    return {
        "counts": counts,
        "deep_runs": len(deep),
        "est_cost_usd": round(est_cost, 4),
        "est_latency_s": est_latency,
        "resolved_without_research": [
            {
                "element_id": r.element_id,
                "tier": r.tier.value,
                "rationale": r.rationale,
                "basis": r.basis,
                "disposition": r.disposition,
            }
            for r in free
        ],
    }
