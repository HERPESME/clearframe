"""Audio identity: fingerprinting is a measurement, not an opinion."""

import json
from pathlib import Path

import pytest

from clearframe.audio import (
    AUDIO_DETECTOR,
    apply_audio_identity,
    is_generic_label,
    sample_offsets,
)
from clearframe.integrations.audio_client import (
    FixtureAudioClient,
    parse_audd_response,
)
from clearframe.models import (
    AudioMatch,
    AudioProvenance,
    ClearanceCategory,
    ElementType,
    IdentityVerdict,
    Prominence,
    TimeRange,
    TriagedElement,
)

FIXTURES = Path(__file__).parent.parent / "src" / "clearframe" / "integrations" / "fixtures"


def _music(label: str, eid: str = "e1") -> TriagedElement:
    return TriagedElement(
        id=eid,
        label=label,
        element_type=ElementType.MUSIC,
        description="background music",
        time_ranges=[TimeRange(start_s=0.0, end_s=20.0)],
        prominence=Prominence(
            screen_time_s=20.0, frame_coverage=0.0, centrality=0.0, plot_integral=True
        ),
        category=ClearanceCategory.MUSIC_SYNC,
    )


# ----------------------------------------------------------- generic labels
@pytest.mark.parametrize(
    "label",
    [
        "Upbeat Electronic Music",
        "Background Music",
        "background music",
        "Instrumental Track",
        "Pop Song",
        "Ambient Score",
        "Unknown Song",
        "upbeat pop",
    ],
)
def test_descriptive_labels_are_generic(label):
    assert is_generic_label(label) is True


@pytest.mark.parametrize(
    "label",
    ["Blinding Lights", "Bohemian Rhapsody", "Sintel Theme", "Take Five"],
)
def test_real_titles_are_not_generic(label):
    assert is_generic_label(label) is False


# ------------------------------------------------------------- the promotion
def test_generic_label_is_replaced_by_the_fingerprint():
    """Gemini said 'Upbeat Electronic Music'. That is an absence of identity,
    not a competing claim, so the fingerprint supplies identity outright."""
    el = _music("Upbeat Electronic Music")
    match = AudioMatch(
        title="Blinding Lights",
        artist="The Weeknd",
        label="Republic Records",
        provenance=AudioProvenance.VERIFIED,
        catalogues=["spotify", "apple_music"],
        confidence=1.0,
        at_s=6.8,
    )
    result = apply_audio_identity(el, [match])

    assert result.corroboration.verdict is IdentityVerdict.FINGERPRINTED
    assert result.label == "Blinding Lights — The Weeknd"
    assert result.promoted is True
    assert "Upbeat Electronic Music" in result.corroboration.note


def test_agreeing_fingerprint_corroborates_a_specific_label():
    el = _music("Blinding Lights")
    match = AudioMatch(title="Blinding Lights", artist="The Weeknd", confidence=1.0)
    result = apply_audio_identity(el, [match])

    assert result.corroboration.verdict is IdentityVerdict.FINGERPRINTED
    assert result.promoted is False


def test_disagreeing_fingerprint_conflicts_and_blocks_research():
    """A named title the fingerprint contradicts is a real identity dispute."""
    from clearframe.corroboration import blocks_research

    el = _music("Bohemian Rhapsody")
    match = AudioMatch(title="Blinding Lights", artist="The Weeknd", confidence=1.0)
    result = apply_audio_identity(el, [match])

    assert result.corroboration.verdict is IdentityVerdict.CONFLICTED
    assert blocks_research(result.corroboration) is True
    assert result.label == "Bohemian Rhapsody"  # never silently overwritten


def test_no_fingerprint_leaves_the_element_single_source():
    el = _music("Blinding Lights")
    result = apply_audio_identity(el, [])
    assert result.corroboration.verdict is IdentityVerdict.SINGLE_SOURCE
    assert result.promoted is False


def test_non_music_elements_are_untouched():
    el = _music("Blinding Lights")
    el = el.model_copy(update={"category": ClearanceCategory.TRADEMARK})
    result = apply_audio_identity(el, [AudioMatch(title="Whatever")])
    assert result.corroboration is None


# ------------------------------------------------------- knockoff provenance
def test_unverified_match_promotes_the_title_but_not_the_artist():
    """AudD matched a knockoff re-upload: right title, junk artist, no catalogue.
    Trust the title; refuse to put the artist into a PRO cue sheet."""
    el = _music("Upbeat Electronic Music")
    match = AudioMatch(
        title="Blinding Lights",
        artist="Magix",
        provenance=AudioProvenance.UNVERIFIED,
        catalogues=[],
        confidence=1.0,
    )
    result = apply_audio_identity(el, [match])

    assert result.label == "Blinding Lights"  # artist withheld
    assert result.corroboration.verdict is IdentityVerdict.FINGERPRINTED
    assert "unverified" in result.corroboration.note.lower()


# -------------------------------------------------------------- the sampling
def test_short_clips_still_sample_the_end():
    """Their clip's music only became dominant at the end; one head sample misses it."""
    offsets = sample_offsets(21.8, segment_s=15.0, max_samples=4)
    assert offsets[0] == 0.0
    assert offsets[-1] + 15.0 >= 21.8 - 0.01


def test_sampling_is_capped_for_long_footage():
    offsets = sample_offsets(5400.0, segment_s=15.0, max_samples=4)
    assert len(offsets) == 4
    assert offsets == sorted(offsets)
    assert offsets[-1] + 15.0 <= 5400.0 + 0.01


def test_a_clip_shorter_than_one_segment_yields_one_sample():
    assert sample_offsets(8.0, segment_s=15.0, max_samples=4) == [0.0]


# ------------------------------------------------------------------ parsing
def test_parses_a_real_audd_success_payload():
    payload = {
        "status": "success",
        "result": {
            "artist": "The Weeknd",
            "title": "Blinding Lights",
            "album": "After Hours",
            "release_date": "2019-11-29",
            "label": "Republic Records",
            "song_link": "https://lis.tn/BlindingLights",
            "spotify": {"id": "0VjIjW4GlUZAMYd2vXMi3b"},
            "apple_music": {"url": "https://music.apple.com/x"},
        },
    }
    matches = parse_audd_response(payload, at_s=6.8)
    assert len(matches) == 1
    m = matches[0]
    assert m.title == "Blinding Lights"
    assert m.artist == "The Weeknd"
    assert m.at_s == 6.8
    assert m.provenance is AudioProvenance.VERIFIED
    assert set(m.catalogues) == {"spotify", "apple_music"}


def test_empty_catalogues_mark_the_match_unverified():
    payload = {
        "status": "success",
        "result": {
            "artist": "Magix",
            "title": "Blinding Lights",
            "label": "Ratter",
            "spotify": None,
            "apple_music": None,
            "musicbrainz": [],
        },
    }
    (m,) = parse_audd_response(payload, at_s=0.0)
    assert m.provenance is AudioProvenance.UNVERIFIED
    assert m.catalogues == []


def test_no_match_returns_nothing():
    assert parse_audd_response({"status": "success", "result": None}, at_s=0.0) == []


def test_api_error_returns_nothing_rather_than_raising():
    payload = {"status": "error", "error": {"error_code": 900, "error_message": "no plan"}}
    assert parse_audd_response(payload, at_s=0.0) == []


# ------------------------------------------------------------------ fixture
@pytest.mark.asyncio
async def test_fixture_client_shares_the_live_parser():
    client = FixtureAudioClient(FIXTURES)
    matches = await client.identify("demo.mp4", 62.0)
    assert matches, "demo fixture must carry an audio match"
    assert all(isinstance(m, AudioMatch) for m in matches)
    assert client.name == AUDIO_DETECTOR


def test_demo_fixture_is_a_genuine_audd_payload():
    """Fixture must be the real API shape, not our parsed model — same trap
    the FindAll fixture fell into before keys-day."""
    raw = json.loads((FIXTURES / "audio" / "demo_scene_audio.json").read_text())
    assert isinstance(raw, list)
    assert {"at_s", "payload"} <= set(raw[0])
    assert raw[0]["payload"]["status"] == "success"
    assert "result" in raw[0]["payload"]
