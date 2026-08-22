"""What the platform does when you publish — not what a court would do.

Every other module here reasons about legal merit. This one reasons about
DETECTABILITY, and the two invert.

In 2025 YouTube processed 2.5 billion Content ID claims, 99%+ of them
automated, and rights holders chose to monetise over 90% — so the dominant
outcome is revenue diversion, not removal. Crucially, the system does not
evaluate fair use. A perfect legal argument does not stop an automated claim.

The consequence for a creator:

  a background mural   real legal weight against you, almost never detected
  a 12-second music bed  excellent fair-use argument, caught essentially always

A clearance report that ranks those by legal merit tells a creator to worry
about the wrong one. So this module answers a different question — will this be
caught, by what, and what exactly do I do about it — and answers it with a
timecode rather than a memo.

Pure code, no I/O beyond loading the policy table.
"""

import json
from functools import lru_cache
from pathlib import Path

from clearframe.models import (
    AudioMatch,
    AudioProvenance,
    ClearanceCategory,
    DetectionMethod,
    PlatformAction,
    PlatformOutcome,
    PlatformPolicy,
    TriagedElement,
)

DATA_PATH = Path(__file__).parent / "data" / "platforms.json"

# How likely each outcome is to actually happen to you. Automated matching is
# the only mechanism that operates at scale; everything else needs a human to
# notice, care, and file.
_DETECTABILITY: dict[PlatformAction, int] = {
    PlatformAction.CLAIM_LIKELY: 95,
    PlatformAction.CLAIM_POSSIBLE: 55,
    PlatformAction.PRIVACY_COMPLAINT: 20,
    PlatformAction.MANUAL_COMPLAINT: 15,
    PlatformAction.NO_PLATFORM_ACTION: 0,
}

_NO_ACTION_CATEGORIES: set[ClearanceCategory] = set()


def _timecode(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _window(element: TriagedElement) -> str:
    if not element.time_ranges:
        return "the affected section"
    first, last = element.time_ranges[0], element.time_ranges[-1]
    return f"{_timecode(first.start_s)}–{_timecode(last.end_s)}"


@lru_cache(maxsize=1)
def load_platforms(data_path: str | None = None) -> dict[str, PlatformPolicy]:
    doc = json.loads(Path(data_path or DATA_PATH).read_text())
    return {p["key"]: PlatformPolicy.model_validate(p) for p in doc["platforms"]}


def platform_for(key: str, platforms: dict[str, PlatformPolicy]) -> PlatformPolicy:
    """Resolve a platform key, falling back rather than raising.

    An unrecognised platform must not fail a run: the fallback is the strictest
    widely-used regime, so an unknown target is warned about rather than waved
    through.
    """
    return platforms.get((key or "").strip().lower()) or platforms["youtube"]


def _music_outcome(
    element: TriagedElement, policy: PlatformPolicy, audio: AudioMatch | None
) -> PlatformOutcome:
    window = _window(element)
    fair_use_note = (
        " Fair use is no defence here: the matching system does not evaluate it, "
        "and disputing a claim is a manual process most creators lose by default."
        if not policy.considers_fair_use
        else ""
    )

    if not policy.audio_matching:
        return PlatformOutcome(
            element_id=element.id,
            platform=policy.name,
            action=PlatformAction.MANUAL_COMPLAINT,
            confidence="unlikely",
            detected_by=DetectionMethod.HUMAN_REPORT,
            consequence=(
                f"{policy.name} runs no automated audio matching, so this surfaces "
                "only if a rights holder notices. That makes it less likely and more "
                "serious when it lands — there is no takedown to react to."
            ),
            remedy=f"Clear the recording, or replace the cue at {window}.",
        )

    identified = audio is not None
    verified = identified and audio.provenance is AudioProvenance.VERIFIED
    holder = (audio.label or audio.artist) if identified else ""

    if verified:
        return PlatformOutcome(
            element_id=element.id,
            platform=policy.name,
            action=PlatformAction.CLAIM_LIKELY,
            confidence="near-certain",
            detected_by=DetectionMethod.AUDIO_FINGERPRINT,
            consequence=(
                f"A commercially released recording matched by acoustic fingerprint. "
                f"{policy.name} matches this automatically on upload, so a claim is "
                f"near-certain." + fair_use_note
            ),
            remedy=(
                f"Mute or replace the audio at {window} before publishing, or licence "
                f"the recording. Editing after a claim lands does not reverse it."
            ),
            revenue_impact=(
                f"Monetisation for the whole video is diverted to {holder}."
                if holder
                else "Monetisation for the whole video is diverted to the rights holder."
            ),
        )

    return PlatformOutcome(
        element_id=element.id,
        platform=policy.name,
        action=PlatformAction.CLAIM_POSSIBLE,
        confidence="possible",
        detected_by=DetectionMethod.AUDIO_FINGERPRINT,
        consequence=(
            "Music is present but the recording was not identified, so whether it "
            "matches a registered work is unknown. Library and original cues pass; "
            "commercial recordings do not." + fair_use_note
        ),
        remedy=(
            f"Identify the cue at {window} from production records, or replace it "
            "with audio you can evidence a licence for."
        ),
    )


def _visual_outcome(element: TriagedElement, policy: PlatformPolicy) -> PlatformOutcome:
    return PlatformOutcome(
        element_id=element.id,
        platform=policy.name,
        action=PlatformAction.MANUAL_COMPLAINT,
        confidence="possible",
        detected_by=DetectionMethod.HUMAN_REPORT,
        consequence=(
            f"No platform runs automated matching over logos or artwork inside a "
            f"video, so this bites only when a person notices and files. Lower "
            f"probability, higher severity: a manual complaint on {policy.name} can "
            f"become a takedown and a strike rather than a revenue share."
        ),
        remedy=(
            f"Clear it, blur it, or reframe the shot at {_window(element)}. "
            f"Route if challenged: {policy.trademark_complaint}"
        ),
    )


def _person_outcome(element: TriagedElement, policy: PlatformPolicy) -> PlatformOutcome:
    return PlatformOutcome(
        element_id=element.id,
        platform=policy.name,
        action=PlatformAction.PRIVACY_COMPLAINT,
        confidence="possible",
        detected_by=DetectionMethod.HUMAN_REPORT,
        consequence=(
            "An identifiable person can complain personally, through a route separate "
            "from copyright. In the EU and UK this is also personal data under GDPR, "
            "and in India under the DPDP Act — a different regime with a different "
            "remedy from the US right of publicity."
        ),
        remedy=(
            f"Obtain a release, or blur the face at {_window(element)}. "
            f"Route if challenged: {policy.privacy_complaint}"
        ),
    )


def _own_content_outcome(element: TriagedElement, policy: PlatformPolicy) -> PlatformOutcome:
    return PlatformOutcome(
        element_id=element.id,
        platform=policy.name,
        action=PlatformAction.NO_PLATFORM_ACTION,
        confidence="none",
        detected_by=DetectionMethod.NOT_DETECTED,
        consequence="This is the production's own graphic. Nothing to enforce.",
        remedy="No action.",
    )


def project_outcome(
    element: TriagedElement,
    policy: PlatformPolicy,
    audio: AudioMatch | None = None,
) -> PlatformOutcome:
    """What this platform will do about this finding when the video goes up."""
    from clearframe.routing import is_own_content

    if element.category is ClearanceCategory.MUSIC_SYNC:
        return _music_outcome(element, policy, audio)
    if element.category is ClearanceCategory.RIGHT_OF_PUBLICITY:
        return _person_outcome(element, policy)
    if element.category is ClearanceCategory.TEXT_ON_SCREEN and is_own_content(
        element.label, element.description
    ):
        return _own_content_outcome(element, policy)
    return _visual_outcome(element, policy)


def detectability(outcome: PlatformOutcome) -> int:
    """0-100: how likely this is to be CAUGHT, not how likely you are to lose."""
    return _DETECTABILITY[outcome.action]


def project_all(
    elements: list[TriagedElement],
    policy: PlatformPolicy,
    audio_matches: list[AudioMatch] | None = None,
) -> list[PlatformOutcome]:
    """Every finding, ranked by how likely the platform is to act on it."""
    best_audio = None
    for m in audio_matches or []:
        if best_audio is None or (
            m.provenance is AudioProvenance.VERIFIED
            and best_audio.provenance is not AudioProvenance.VERIFIED
        ):
            best_audio = m
    outcomes = [project_outcome(el, policy, best_audio) for el in elements]
    return sorted(outcomes, key=detectability, reverse=True)
