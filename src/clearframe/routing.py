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

from clearframe.audio import is_generic_label
from clearframe.knowledge import KnowledgeBase
from clearframe.matching import tokens
from clearframe.scoring import provisional_score
import re

from clearframe.models import (
    ClearanceCategory,
    DepictionTone,
    Corroboration,
    IdentityVerdict,
    ElementType,
    LicensingPosture,
    Prominence,
    ResearchRoute,
    ResearchTier,
    SourceWork,
    TriagedElement,
    UseContext,
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

# Commercial speech gets no expressive-work shield, so knowing the holder's
# posture is no longer enough — you need an actual licence, which means an
# actual contact and cost band, which only a deep run produces.
_COMMERCIAL = {UseContext.ADVERTISING, UseContext.SPONSORED}

# Portrayals a rights holder is likely to object to. Presence is rarely the
# complaint; association is.
_ADVERSE = {DepictionTone.UNFLATTERING, DepictionTone.DISPARAGING}

# Categories where a sponsor's own mark can appear.
_BRAND_CATEGORIES = {
    ClearanceCategory.TRADEMARK,
    ClearanceCategory.TEXT_ON_SCREEN,
}


def _sponsor_authorised(
    element: TriagedElement, knowledge: KnowledgeBase, sponsors: list[str]
) -> ResearchRoute | None:
    """The sponsor's own mark, appearing in the thing they are paying for.

    This is not an unlicensed use, and treating it as one produced the worst
    output the router has generated: a Parallel Task run and the disposition
    "approach Domino's Pizza, Inc." handed to the agency whose client
    commissioned the advert.

    It is not suppressed either — a dossier that silently omits the hero
    product is incomplete, and the production agreement still has to reach the
    declared territories and media. That is a coverage question, and this is
    how it gets asked.
    """
    if not sponsors or element.category not in _BRAND_CATEGORIES:
        return None
    # Authorisation covers showing the mark, not disparaging it.
    if element.depiction in _ADVERSE:
        return None

    found = knowledge.find_mark(element.label)
    if found is None:
        return None

    for name in sponsors:
        sponsor = knowledge.find_mark(name)
        if sponsor is None:
            continue
        if found.owner != sponsor.owner and found.parent != sponsor.parent:
            continue
        return ResearchRoute(
            element_id=element.id,
            tier=ResearchTier.LOCAL,
            owner=found.owner,
            posture=LicensingPosture.PERMISSIVE,
            rationale=(
                f"'{name}' is a declared sponsor of this production, so {found.owner}'s "
                "mark appearing in it is authorised by contract rather than a use "
                "needing clearance. Researching who owns it would spend a deep run to "
                "arrive back at the client."
            ),
            basis="Authorised by the production or sponsorship agreement",
            disposition=(
                f"No clearance request. Confirm the {name} agreement covers the "
                "declared territories, media and term — an authorised mark shown "
                "outside the granted scope is still a gap."
            ),
        )
    return None

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
    # Relationship and role labels. A scan describing the cast by their part
    # ("Father", "Grandmother", "Presenter") has named nobody: there is no
    # rights holder behind a role. Found on a live run where "Father" and
    # "Grandmother" were dispatched to rights research and returned nothing,
    # while "Young Boy" and "Little Girl" correctly went to release forms —
    # the same people, sorted by an accident of vocabulary.
    "father", "mother", "dad", "mom", "mum", "parent", "grandmother",
    "grandfather", "grandma", "grandpa", "son", "daughter", "brother",
    "sister", "husband", "wife", "family", "baby", "infant", "toddler",
    "teen", "teenager", "adult", "elderly", "senior", "young", "old",
    "presenter", "host", "hostess", "announcer", "narrator", "spokesperson",
    "spokesman", "spokeswoman", "actor", "actors", "actress", "cast",
    "performer", "model", "dancer", "singer", "musician", "worker", "waiter",
    "waitress", "clerk", "cashier", "driver", "doctor", "nurse", "teacher",
    "student", "shopper", "diner", "guest", "visitor", "neighbour", "neighbor",
    "couple", "group", "portrait", "headshot", "profile",
}

# Graphics the production made itself. Its own copyright; nothing to clear.
#
# Split in two, because the scan does not reliably put the giveaway word in the
# LABEL. A deployed run produced eight subtitle findings: one labelled
# "On-screen subtitles" and seven labelled with the dialogue itself — `Alan!`,
# `He's bald!`, `Oh, holy sh*t.` — whose only clue is the sentence underneath,
# "The text '…' appears as a subtitle at the bottom of the frame." Reading the
# label alone caught one of eight, drew boxes on the other seven, and sent seven
# Parallel Searches asking whether lines of the film's own dialogue were
# registered marks.
#
# These are safe to read from the description as well as the label. No ordinary
# object is described as a subtitle or a chyron.
_OWN_CONTENT_ANYWHERE = {
    "subtitle", "subtitles", "caption", "captions", "chyron", "watermark",
    "titlecard", "supers",
}
# These are only read from the LABEL, because a description is a whole sentence
# of ordinary English: a poster on a "lower" shelf, a "super" soaker, a "bug"
# on the windscreen, the "credits" on a bill.
_OWN_CONTENT = {
    "overlay", "overlays", "credits", "lower", "third", "super", "slate", "bug",
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
    # Wardrobe and personal effects. A watch is a watch: there is no author to
    # find, so a deep run spends minutes to discover it. Anything carrying a
    # visible mark keeps a proper noun in its label and never reaches here,
    # because the test is that EVERY meaningful token is generic.
    "watch", "wristwatch", "watches", "sunglasses", "spectacles", "eyewear",
    "ring", "rings", "bracelet", "necklace", "earring", "earrings", "belt",
    "buckle", "shoe", "shoes", "boot", "boots", "sneaker", "sneakers",
    "handbag", "purse", "wallet", "luggage", "suitcase", "briefcase",
    "umbrella", "keys", "keyring", "sunglass", "aviator", "aviators",
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


_POSSESSIVE = re.compile(r"\b[\w]+['’]s\b")


def _without_possessives(label: str) -> str:
    """Drop possessive words before testing whether a label is generic.

    "Phil's Ring" is a ring. The possessive names the wearer, not the maker,
    and there is no rights holder called Phil — but it kept the label out of
    the utilitarian bucket and bought a multi-minute ownership investigation
    into a piece of jewellery.
    """
    return _POSSESSIVE.sub(" ", label)


def _any_token(label: str, vocab: set[str]) -> bool:
    return any(t in vocab for t in _meaningful(label))


def _all_tokens(label: str, vocab: set[str]) -> bool:
    words = _meaningful(label)
    return bool(words) and all(t in vocab for t in words)


# The scan describing an element as a reproduction of another work. Whitmill
# turns on exactly this: replicating a tattoo onto a different person is
# materially riskier than filming the person who wears it.
#
# Stems, not whole words. The live scan wrote "replicating" while the set held
# "replicated", so the check missed the exact fact pattern that lawsuit was
# about, in the exact clip it was about. English inflects; a list of literals
# does not.
_REPLICA_STEMS = (
    "replic", "reproduc", "recreat", "copie", "copy",
    "imitat", "duplicat", "mimic", "knockoff", "knock-off",
)


def _describes_a_reproduction(text: str) -> bool:
    return any(t.startswith(_REPLICA_STEMS) for t in _meaningful(text))


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
    """Did the production author this graphic, or did the camera record it?

    The description is read for the unambiguous words and the label for the
    ambiguous ones. That asymmetry is the whole point: the scan writes the
    giveaway ("appears as a subtitle") in the sentence far more reliably than in
    the label, but a sentence is also where an ordinary word like "lower" or
    "bug" is most likely to mean something else entirely.
    """
    haystack = f"{label} {description}".casefold()
    if any(phrase in haystack for phrase in _OWN_CONTENT_PHRASES):
        return True
    if _any_token(f"{label} {description}", _OWN_CONTENT_ANYWHERE):
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
    if mark is None and _all_tokens(_without_possessives(el.label), _UTILITARIAN):
        # A product type is not a mark. The scan typed "Wristwatch" as a LOGO,
        # so it reached the trademark router, missed the catalogue and bought a
        # multi-minute ownership investigation — for a string with no
        # proprietor in it. No amount of searching invents one.
        #
        # Deliberately narrow: this is not a catalogue miss. "Calvin Klein" is
        # a real mark absent from our entries and still earns a deep run.
        return _statute(
            el,
            "The label names a kind of object rather than a brand, so there is "
            "no proprietor to find. A deep run here spends minutes establishing "
            "that a wristwatch is a wristwatch.",
            "A trademark protects a mark used to indicate source; a generic "
            "product designation is not registrable — 15 U.S.C. §1064(3), "
            "Kellogg Co. v. National Biscuit Co., 305 U.S. 111 (1938)",
            "No action unless a mark becomes legible, in which case relabel the "
            "finding with the brand and re-run.",
        )
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
    if is_generic_label(el.label):
        return _statute(
            el,
            "The scan described this music rather than naming it, and acoustic "
            "fingerprinting found no match — so there is no work to research. "
            "Researching a description is not merely fruitless: on real footage "
            "'Upbeat Electronic Music' returned a plausible owner with fourteen "
            "citations for a recording that was actually 'Blinding Lights'. A "
            "confident wrong answer is worse than an admitted gap.",
            "No identified work — research requires an identity to research",
            "Identify the recording before clearing it: production music records "
            "and the composer or library agreement will name it, or re-run "
            "fingerprinting over a segment where the cue is not buried under "
            "dialogue. Do NOT file a cue sheet from a description.",
        )
    return _deep(
        el,
        "Music is the category productions reliably lose. The recording carries a "
        "title but no fingerprint match, so publisher and master chains still need "
        "tracing — genuinely multi-hop, which is what a deep run is for.",
        basis="NMPA v. Fullscreen (2013); Bridgeport v. Dimension Films, 410 F.3d 792 (6th Cir. 2005)",
    )


def _tattoo_route(el: TriagedElement, kb: KnowledgeBase) -> ResearchRoute:
    """Tattoos have settled category guidance, and it is already in the table.

    `cases_for()` fed liability.py and nothing else, so the most-litigated
    tattoo in film history went to a four-minute open-web search that returned
    nothing while the case describing it sat in `litigation.json`.

    The record splits on one fact. Solid Oak and Alexander both concern tattoos
    on the person who wears them: real claims, low value, answered by a release.
    Whitmill concerns a tattoo REPLICATED onto someone else, which drew a
    federal suit and a settlement weeks before opening. So the question is not
    who inked it — it is whether this is the wearer or a copy.
    """
    cases = kb.cases_for(ClearanceCategory.COPYRIGHT_ART.value)
    named = {c.name.split(" v. ")[0]: c for c in cases}
    replica = _describes_a_reproduction(el.description)

    if replica:
        whitmill = named.get("Whitmill")
        return ResearchRoute(
            element_id=el.id,
            tier=ResearchTier.DEEP,
            owner=None,
            posture=None,
            rationale=(
                "The scan describes this as a reproduction of an existing "
                "tattoo rather than the wearer's own. That is the fact Whitmill "
                "turned on, and it moves the question from 'get a release' to "
                "'who authored the original design' — which is a genuine "
                "ownership investigation."
            ),
            basis=(
                f"{whitmill.name} ({whitmill.citation}) — {whitmill.lesson}"
                if whitmill
                else "Replicating a tattoo onto a different person is materially "
                "riskier than filming the person who wears it."
            ),
            disposition=(
                "Identify and clear the original tattoo artist, or redesign the "
                "artwork. A release from the actor wearing the copy does not "
                "reach the design."
            ),
            est_cost_usd=0.0,  # filled from the processor tier by the planner
        )

    citing = [named[n] for n in ("Solid Oak", "Alexander") if n in named]
    return _statute(
        el,
        "A tattoo on the person wearing it. The claim is real but low-value, and "
        "it is answered by a release from the person, not by an ownership "
        "investigation into who inked it — which is why a deep run here returns "
        "nothing at a cost of minutes.",
        "; ".join(f"{c.name} ({c.citation}) — {c.lesson}" for c in citing)
        or "Tattoo claims on the wearer are defensible where the production is "
        "entitled to depict the person.",
        "Obtain a personal release from the wearer covering the tattoo, and keep "
        "it on file. Escalate only if the design is a reproduction of another "
        "artist's work.",
    )


def _route_art(el: TriagedElement, kb: KnowledgeBase) -> ResearchRoute:
    if el.element_type is ElementType.TATTOO:
        return _tattoo_route(el, kb)
    if _all_tokens(_without_possessives(el.label), _UTILITARIAN):
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
    # Deliberately NOT mirrored from the music rule above. A bare "Painting"
    # is as unidentifiable as "Instrumental Score", but the stakes are not
    # symmetric: Falkner and Ringgold both turned on unattributed images, and
    # FindAll enumeration is a real answer for art in a way it is not for a
    # recording. Art gets the expensive attempt; music does not.
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


def _route_person(el: TriagedElement, use_context: UseContext) -> ResearchRoute:
    if _any_token(el.label, _ANONYMOUS):
        commercial = use_context in _COMMERCIAL
        return _statute(
            el,
            "An unnamed individual has no discoverable rights holder. Research "
            "cannot produce the instrument this needs."
            + (
                " In a commercial context this is not advisory: the right of "
                "publicity is a tort of COMMERCIAL appropriation, so an advert "
                "is the one place the claim is at its strongest."
                if commercial
                else ""
            ),
            "Right of publicity — cleared by consent, not by ownership research"
            + (
                "; commercial appropriation is the core of the tort"
                if commercial
                else ""
            ),
            (
                "A signed personal release is MANDATORY before this can run "
                "commercially. Blur otherwise — a crowd notice does not cover "
                "advertising use."
                if commercial
                else "Obtain a personal release, or blur. If shot in a public place "
                "under a crowd notice, file the notice against this finding."
            ),
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
    ClearanceCategory.TRADEMARK: lambda el, kb, corr, ctx: _route_trademark(el, kb),
    ClearanceCategory.MUSIC_SYNC: lambda el, kb, corr, ctx: _route_music(el, corr),
    ClearanceCategory.COPYRIGHT_ART: lambda el, kb, corr, ctx: _route_art(el, kb),
    ClearanceCategory.RIGHT_OF_PUBLICITY: lambda el, kb, corr, ctx: _route_person(el, ctx),
    ClearanceCategory.LOCATION: lambda el, kb, corr, ctx: _route_location(el),
    ClearanceCategory.TEXT_ON_SCREEN: lambda el, kb, corr, ctx: _route_text(el, kb),
}


def route(
    element: TriagedElement,
    knowledge: KnowledgeBase,
    corroboration: Corroboration | None = None,
    escalate_material: bool = True,
    use_context: UseContext = UseContext.EXPRESSIVE,
    sponsors: list[str] | None = None,
    source_work: SourceWork | None = None,
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
    # If the footage IS someone else's work, its own characters, set dressing
    # and on-screen text are not separately licensable. Researching them spends
    # minutes to rediscover the studio we already named.
    from clearframe.sourcework import subsumed_by

    if subsumed_by(element, source_work):
        holder = source_work.rights_holder or "the rights holder"
        return ResearchRoute(
            element_id=element.id,
            tier=ResearchTier.LOCAL,
            owner=source_work.rights_holder or None,
            rationale=(
                f"An element of '{source_work.title}', which this footage appears "
                "to BE rather than merely contain. Its characters and set dressing "
                "belong to the same studio as the film, so researching them "
                "separately rediscovers an answer we already have."
            ),
            basis=f"Identified source work — {source_work.basis}",
            disposition=(
                f"No separate clearance. Obtain a licence to '{source_work.title}' "
                f"from {holder}; this element is covered by it and cannot be "
                "licensed on its own."
            ),
        )

    authorised = _sponsor_authorised(element, knowledge, sponsors or [])
    if authorised is not None:
        return authorised

    chosen = _ROUTERS[element.category](element, knowledge, corroboration, use_context)

    # An adverse depiction changes the question being asked. Ownership is known
    # and posture would normally be a two-second search — but "are they
    # litigious in general" is not what matters here. "Will they object to
    # THIS" does, and answering it needs a contact and a route to ask.
    if chosen.tier is ResearchTier.SEARCH and element.depiction in _ADVERSE:
        return chosen.model_copy(
            update={
                "tier": ResearchTier.DEEP,
                "rationale": (
                    f"The mark is depicted as {element.depiction.value.lower()}, which "
                    "is what rights holders actually object to — presence is rarely the "
                    "complaint. So the open question is not general posture but whether "
                    "this holder will object to this scene, which needs a named contact "
                    f"and a route to ask. {chosen.rationale}"
                ),
                "basis": (
                    "Wham-O v. Paramount (C.D. Cal. 2003) — suit filed over an "
                    "unflattering product gag; In-Sink-Erator / NBC 'Heroes' (2006) — "
                    "mark digitally removed in post rather than defended"
                ),
                "disposition": (
                    "Seek written permission for this specific depiction, or plan a "
                    "digital removal. NBC chose removal and paid for it in post."
                ),
                "est_cost_usd": 0.0,
                "est_latency_s": DEEP_LATENCY_S,
            }
        )

    # Commercial speech: posture is no longer the open question, permission is.
    if chosen.tier is ResearchTier.SEARCH and use_context in _COMMERCIAL:
        return chosen.model_copy(
            update={
                "tier": ResearchTier.DEEP,
                "rationale": (
                    f"This is {use_context.value.lower()} use, which carries no "
                    "expressive-work shield — Rogers v. Grimaldi protects films, "
                    "not adverts, and every brand-owner win in the record is an "
                    "advert (Falkner v. GM, Mercedes v. the Detroit muralists, "
                    "Revok v. H&M). Knowing the posture is not enough; you need "
                    "an actual licence, so you need the contact and the cost "
                    f"band. {chosen.rationale}"
                ),
                "est_cost_usd": 0.0,
                "est_latency_s": DEEP_LATENCY_S,
            }
        )

    if (
        escalate_material
        and chosen.tier is ResearchTier.SEARCH
        and provisional_score(element, use_context) >= MATERIALITY_ESCALATION_SCORE
    ):
        score = provisional_score(element, use_context)
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
    use_context: UseContext = UseContext.EXPRESSIVE,
    sponsors: list[str] | None = None,
    source_work: SourceWork | None = None,
) -> dict[str, ResearchRoute]:
    corroboration = corroboration or {}
    return {
        el.id: route(
            el,
            knowledge,
            corroboration.get(el.id),
            escalate_material,
            use_context,
            sponsors,
            source_work,
        )
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
