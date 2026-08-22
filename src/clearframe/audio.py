"""Audio identity: promotion, corroboration and sampling. Pure code, no I/O.

Music is the category a production reliably LOSES. Publishers and labels detect
at industrial scale, hold standing licensing infrastructure, and carry
$750-$150,000 per-work statutory exposure. It is also the category ClearFrame
identified worst: a language model listening to a track and naming it.

Observed on real footage: Gemini reported "Upbeat Electronic Music". Rights
research faithfully researched that phrase and returned a plausible owner with
fourteen citations. The recording was actually "Blinding Lights" (UMPG / XO /
Republic). One missing identity at stage 2 produced a confidently wrong,
well-cited answer six stages later.

An acoustic fingerprint fixes the root cause because it is a *measurement*
over the audio - spectral peak hashing against an indexed database - rather
than a model's impression. So for music the fingerprint is an identity
SOURCE, not merely a corroborator, and the verdict it yields (FINGERPRINTED)
outranks CORROBORATED.

Four deterministic outcomes, in the same spirit as `corroboration.py`:

  generic label  + hit  -> PROMOTE. The model supplied no identity to dispute.
  specific label + agreeing hit -> FINGERPRINTED, label untouched.
  specific label + disagreeing hit -> CONFLICTED. Blocks research, as always.
  any label + no hit -> SINGLE_SOURCE. Silence is not contradiction.
"""

import math
import re
from dataclasses import dataclass

from clearframe.matching import labels_match
from clearframe.models import (
    AudioMatch,
    AudioProvenance,
    ClearanceCategory,
    Corroboration,
    IdentityVerdict,
    TriagedElement,
)

AUDIO_DETECTOR = "audd-fingerprint"

# Words that describe music rather than name it. A label made ENTIRELY of these
# (plus stopwords) is a description, and a description is not an identity claim.
_GENERIC_TERMS = {
    "music", "song", "songs", "track", "tracks", "audio", "sound", "sounds",
    "instrumental", "instrumentals", "score", "soundtrack", "cue", "beat",
    "beats", "tune", "melody", "theme", "jingle", "background", "bgm",
    "underscore", "loop", "stinger", "sting", "bed",
    # genre / mood adjectives
    "upbeat", "ambient", "electronic", "electronica", "pop", "rock", "jazz",
    "classical", "orchestral", "acoustic", "hip", "hop", "rap", "edm", "house",
    "techno", "lofi", "lo-fi", "funk", "soul", "blues", "country", "folk",
    "indie", "metal", "punk", "reggae", "disco", "dance", "chill", "calm",
    "dramatic", "tense", "happy", "sad", "energetic", "uplifting", "moody",
    "cheerful", "somber", "epic", "soft", "loud", "slow", "fast", "modern",
    "vintage", "retro", "generic", "royalty", "free", "stock", "library",
    "unknown", "unidentified", "unnamed", "various", "playing", "plays",
    "diegetic", "non-diegetic", "vocal", "vocals", "male", "female",
}

_STOPWORDS = {"a", "an", "the", "of", "and", "or", "in", "on", "with", "for", "to"}

_TOKEN = re.compile(r"[a-z0-9']+")


def is_generic_label(label: str) -> bool:
    """True when the label merely DESCRIBES music instead of naming a work."""
    tokens = _TOKEN.findall((label or "").casefold())
    meaningful = [t for t in tokens if t not in _STOPWORDS]
    if not meaningful:
        return True
    return all(t in _GENERIC_TERMS for t in meaningful)


def sample_offsets(
    duration_s: float, segment_s: float = 15.0, max_samples: int = 4
) -> list[float]:
    """Where to cut audio samples for fingerprinting.

    Spread evenly across the whole clip rather than sampling only the head:
    on the footage that motivated this module the music was quiet under
    dialogue and only became dominant in the final seconds. A single head
    sample would have missed the one element that mattered most.

    Capped because AudD bills per request; feature-length footage should pass
    scan-detected music ranges instead of blind-sampling.
    """
    duration_s = max(0.0, float(duration_s))
    if duration_s <= segment_s:
        return [0.0]
    needed = math.ceil(duration_s / segment_s)
    n = max(2, min(max_samples, needed))
    span = duration_s - segment_s
    return [round(span * i / (n - 1), 3) for i in range(n)]


def ranges_to_offsets(
    ranges: list[tuple[float, float]], segment_s: float = 15.0, max_samples: int = 4
) -> list[float]:
    """Targeted sampling over windows where music was actually detected."""
    offsets: list[float] = []
    for start, end in sorted(ranges):
        if end - start < 1.0:
            continue
        offsets.append(round(max(0.0, start), 3))
        midpoint = start + (end - start) / 2
        if end - start > segment_s * 1.5:
            offsets.append(round(midpoint, 3))
    deduped = sorted({o for o in offsets})
    return deduped[:max_samples]


@dataclass
class AudioIdentity:
    """The outcome of applying fingerprint evidence to one element."""

    label: str
    corroboration: Corroboration | None
    promoted: bool
    match: AudioMatch | None = None


def _display(match: AudioMatch) -> str:
    """How to name the work.

    An UNVERIFIED match came back with no major catalogue behind it - the
    signature of a knockoff re-upload, which carries the right title and a
    junk artist. Take the title, refuse the attribution: the attribution is
    what would land in an ASCAP/BMI cue sheet.
    """
    if match.provenance is AudioProvenance.VERIFIED and match.artist:
        return f"{match.title} — {match.artist}"
    return match.title


def _best(matches: list[AudioMatch]) -> AudioMatch:
    return max(
        matches,
        key=lambda m: (m.provenance is AudioProvenance.VERIFIED, m.confidence, len(m.catalogues)),
    )


def apply_audio_identity(
    element: TriagedElement, matches: list[AudioMatch], checked: bool = True
) -> AudioIdentity:
    """Deterministic identity outcome for one element given fingerprint hits.

    `checked` distinguishes "the fingerprint found nothing" from "the
    fingerprint never ran". Reporting the second as the first is a lie with a
    comforting shape: one says the recording is probably library or original,
    the other says nobody looked.
    """
    if element.category is not ClearanceCategory.MUSIC_SYNC:
        return AudioIdentity(label=element.label, corroboration=None, promoted=False)

    if not matches:
        note = (
            "Acoustic fingerprinting returned no match. Not a contradiction — "
            "the recording may be library, original or absent from the database — "
            "but the title rests on the video model alone and must not be filed "
            "to a PRO without human confirmation."
            if checked
            else (
                "Acoustic fingerprinting COULD NOT BE CHECKED — the service refused "
                "the request, so this recording was never looked up. That is not the "
                "same as finding nothing: the track may well be a commercial release. "
                "Set a working AUDD_API_TOKEN (an account needs an active trial or "
                "subscription) and re-run before filing anything to a PRO."
            )
        )
        return AudioIdentity(
            label=element.label,
            promoted=False,
            corroboration=Corroboration(
                element_id=element.id,
                verdict=IdentityVerdict.SINGLE_SOURCE,
                detector=AUDIO_DETECTOR,
                detected_label=None,
                confidence=0.0,
                note=note,
            ),
        )

    match = _best(matches)
    unverified = match.provenance is not AudioProvenance.VERIFIED
    caveat = (
        " Attribution is unverified: no major catalogue (Spotify/Apple Music/"
        "MusicBrainz) backs this row, which is the signature of a knockoff "
        "re-upload. The title is usable; the artist and label are not."
        if unverified
        else ""
    )

    if is_generic_label(element.label):
        return AudioIdentity(
            label=_display(match),
            promoted=True,
            match=match,
            corroboration=Corroboration(
                element_id=element.id,
                verdict=IdentityVerdict.FINGERPRINTED,
                detector=AUDIO_DETECTOR,
                detected_label=match.title,
                confidence=match.confidence,
                note=(
                    f"The video model offered only a description ('{element.label}'), "
                    f"which is an absence of identity rather than a competing claim. "
                    f"Acoustic fingerprinting identified '{match.title}'"
                    f"{f' by {match.artist}' if match.artist else ''} at "
                    f"{match.at_s:.1f}s, so the fingerprint supplies identity."
                    + caveat
                ),
            ),
        )

    if labels_match(element.label, match.title):
        return AudioIdentity(
            label=element.label,
            promoted=False,
            match=match,
            corroboration=Corroboration(
                element_id=element.id,
                verdict=IdentityVerdict.FINGERPRINTED,
                detector=AUDIO_DETECTOR,
                detected_label=match.title,
                confidence=match.confidence,
                note=(
                    f"Acoustic fingerprinting measured the same recording the video "
                    f"model named ('{match.title}') at {match.at_s:.1f}s. Identity is "
                    "confirmed by measurement, not inference." + caveat
                ),
            ),
        )

    return AudioIdentity(
        label=element.label,
        promoted=False,
        match=match,
        corroboration=Corroboration(
            element_id=element.id,
            verdict=IdentityVerdict.CONFLICTED,
            detector=AUDIO_DETECTOR,
            detected_label=match.title,
            confidence=match.confidence,
            note=(
                f"Identity dispute: the video model named '{element.label}' but "
                f"acoustic fingerprinting measured '{match.title}' at {match.at_s:.1f}s. "
                "Resolve before researching — a wrong title in a cue sheet is a false "
                "filing to a PRO." + caveat
            ),
        ),
    )
