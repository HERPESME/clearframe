"""Gemini hears and sees everything, and knows nothing about the production.

`_video_part` sends the whole mp4, so Gemini decodes both tracks natively — it
hears the dialogue and the voiceover, and it reads on-screen text. That part was
never the gap. The gap is that no production context travelled with it: not the
title, not that this is an advert rather than a film, not who is paying for it,
not what the script already said.

Context sharpens two judgements the scan is otherwise guessing at — how
prominent something is to the story, and how it is portrayed. It must never
cause the model to omit anything: recall is the whole safety claim.
"""

import pytest

from clearframe.integrations.gemini_client import build_scan_context
from clearframe.models import ElementType, Production, ScriptMention, UseContext


def production(**kw):
    base = dict(id="p", title="Golden Hour", footage_uri="x", duration_s=60.0)
    base.update(kw)
    return Production(**base)


def test_no_context_when_nothing_is_declared():
    """An unadorned production must send exactly the prompt it always sent."""
    assert build_scan_context(production(), []) == ""


def test_the_title_and_medium_travel():
    ctx = build_scan_context(
        production(use_context=UseContext.ADVERTISING), []
    )
    assert "Golden Hour" in ctx
    assert "advertis" in ctx.lower()


def test_sponsors_are_named_as_authorised_but_still_reportable():
    ctx = build_scan_context(production(sponsors=["Domino's Pizza"]), [])
    assert "Domino's Pizza" in ctx
    assert "authorised" in ctx.lower()
    assert "still report" in ctx.lower()


def test_script_mentions_prime_the_scan():
    mentions = [
        ScriptMention(label="Coca-Cola can", element_type=ElementType.LOGO, scene="INT. KITCHEN"),
        ScriptMention(label="Nike hoodie", element_type=ElementType.LOGO, scene="EXT. STREET"),
    ]
    ctx = build_scan_context(production(), mentions)
    assert "Coca-Cola can" in ctx and "Nike hoodie" in ctx


def test_the_script_list_is_capped_so_it_cannot_swamp_the_prompt():
    many = [
        ScriptMention(label=f"Item {i}", element_type=ElementType.LOGO, scene="S")
        for i in range(200)
    ]
    ctx = build_scan_context(production(), many)
    assert len(ctx) < 4000
    assert "Item 0" in ctx


def test_context_never_licenses_the_model_to_omit_anything():
    """The one instruction that must survive every future edit. Detection
    breadth is this product's safety claim, and a hint about what matters is
    one careless sentence away from becoming permission to skip things."""
    ctx = build_scan_context(
        production(use_context=UseContext.ADVERTISING, sponsors=["Domino's Pizza"]),
        [ScriptMention(label="X", element_type=ElementType.LOGO, scene="S")],
    )
    lowered = ctx.lower()
    assert "report everything" in lowered
    assert "must not" in lowered or "never" in lowered


def test_the_context_is_appended_not_substituted():
    from clearframe.integrations.gemini_client import SCAN_PROMPT, scan_prompt_with

    ctx = build_scan_context(production(sponsors=["Domino's Pizza"]), [])
    combined = scan_prompt_with(ctx)
    assert combined.startswith(SCAN_PROMPT)
    assert ctx in combined


def test_an_empty_context_leaves_the_prompt_byte_identical():
    from clearframe.integrations.gemini_client import SCAN_PROMPT, scan_prompt_with

    assert scan_prompt_with("") == SCAN_PROMPT
