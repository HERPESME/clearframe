"""'No match' and 'we could not check' are different answers.

AudD returns error 900 when a token is valid but the account has no active
trial or subscription. Our client swallowed it and returned an empty list —
indistinguishable from a genuine no-match — so the dossier read:

    "Acoustic fingerprinting returned no match. Not a contradiction — the
     recording may be library, original or absent from the database."

Every word of that is false when the service rejected our credentials. One
says the music is probably safe; the other says nobody looked. This codebase
distinguishes SINGLE_SOURCE from CONFLICTED, and RESEARCH INCOMPLETE from
research done, for exactly this reason.
"""

import pytest

from clearframe.audio import apply_audio_identity
from clearframe.integrations.audio_client import parse_audd_response, service_unavailable
from clearframe.models import (
    ClearanceCategory,
    ElementType,
    IdentityVerdict,
    Prominence,
    TimeRange,
    TriagedElement,
)

INACTIVE = {
    "status": "error",
    "error": {
        "error_code": 900,
        "error_message": "authorization failed: the provided api_token is "
        "incorrect, invalid, or inactive.",
    },
}
NO_MATCH = {"status": "success", "result": None}


def music(label="Atmospheric Score"):
    return TriagedElement(
        id="e1", label=label, element_type=ElementType.MUSIC, description="",
        time_ranges=[TimeRange(start_s=0.0, end_s=30.0)],
        prominence=Prominence(screen_time_s=30.0, frame_coverage=0.0,
                              centrality=0.0, plot_integral=True),
        category=ClearanceCategory.MUSIC_SYNC,
    )


# ------------------------------------------------------- telling them apart
def test_an_auth_failure_is_recognised_as_unavailable():
    assert service_unavailable(INACTIVE) is True


def test_a_genuine_no_match_is_not_unavailable():
    assert service_unavailable(NO_MATCH) is False


def test_a_successful_match_is_not_unavailable():
    hit = {"status": "success", "result": {"title": "X", "artist": "Y"}}
    assert service_unavailable(hit) is False


def test_both_still_parse_to_no_matches():
    """The parser's contract is unchanged; only the reporting differs."""
    assert parse_audd_response(INACTIVE, at_s=0.0) == []
    assert parse_audd_response(NO_MATCH, at_s=0.0) == []


# --------------------------------------------------------- what it reports
def test_an_unchecked_recording_does_not_claim_it_was_checked():
    result = apply_audio_identity(music(), [], checked=False)
    note = result.corroboration.note.lower()
    assert "no match" not in note
    assert "could not" in note or "unavailable" in note
    assert result.corroboration.verdict is IdentityVerdict.SINGLE_SOURCE


def test_a_checked_recording_still_says_no_match():
    note = apply_audio_identity(music(), [], checked=True).corroboration.note.lower()
    assert "no match" in note


def test_the_default_is_checked_so_nothing_existing_moves():
    assert (
        apply_audio_identity(music(), []).corroboration.note
        == apply_audio_identity(music(), [], checked=True).corroboration.note
    )


def test_the_unchecked_note_says_what_to_do_about_it():
    note = apply_audio_identity(music(), [], checked=False).corroboration.note
    assert "AUDD_API_TOKEN" in note or "token" in note.lower()
