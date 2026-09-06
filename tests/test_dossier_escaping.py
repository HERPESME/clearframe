"""The dossier renders text people typed. It must render it as text.

`jinja2.Template(...)` — which is what this renderer uses — defaults to
`autoescape=False`. The autoescaping default only flips when you go through
`Environment(autoescape=True)` or `select_autoescape`, so every user-controlled
string in the E&O report has been going into the HTML raw.

The values that matter are not exotic. A decision note is free text a reviewer
types. A production title comes off the upload form. Sponsor names likewise. And
`Decision.reviewer` is now an email address with a display name behind it, both
chosen at sign-up by whoever signed up.

The dossier is served same-origin from
`/api/productions/{pid}/artifacts/dossier.html`, so a `<script>` in any of them
runs against the signed-in session. The session cookie is HttpOnly and cannot be
read by script, but same-origin `fetch` carries it regardless — so the script can
do anything the signed-in user can, which on a `legal` role includes signing off
clearance decisions.

Escaping is also plain correctness: a production honestly titled
"Fish & Chips <the documentary>" should not silently lose half its name.

The state here comes from a real demo run rather than a hand-built fixture,
because `build_dossier` reads risk, remediation, court and corroboration maps
that a partial state does not have — and a test that has to fake all of those is
testing its own fixture as much as the renderer.
"""

import pytest

from clearframe.dossier import auto_decisions, build_dossier
from clearframe.exporters.dossier_html import render_dossier_html
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context

PAYLOAD = "<script>alert('xss')</script>"


@pytest.fixture
async def state(tmp_path):
    ctx = demo_context(tmp_path)
    ran = await Pipeline(build_demo_pipeline()).run(ctx)
    ran.decisions = auto_decisions(ran)
    return ran


def _html(state) -> str:
    return render_dossier_html(build_dossier(state, generated_at="2026-09-06T00:00:00Z"))


async def test_a_hostile_production_title_is_not_markup(state):
    state.production = state.production.model_copy(update={"title": PAYLOAD})

    assert "<script>alert" not in _html(state)


async def test_a_hostile_decision_note_is_not_markup(state):
    """Free text, typed by a reviewer, straight into the report."""
    first = next(iter(state.decisions.values()))
    state.decisions[first.element_id] = first.model_copy(update={"note": PAYLOAD})

    assert "<script>alert" not in _html(state)


async def test_a_hostile_reviewer_identity_is_not_markup(state):
    """This one is new. The audit trail used to record the role WORD; it now
    records an email and display name that the signer chose themselves."""
    first = next(iter(state.decisions.values()))
    state.decisions[first.element_id] = first.model_copy(update={"reviewer": PAYLOAD})

    assert "<script>alert" not in _html(state)


async def test_a_hostile_sponsor_name_is_not_markup(state):
    state.production = state.production.model_copy(update={"sponsors": [PAYLOAD]})

    assert "<script>alert" not in _html(state)


async def test_a_hostile_element_label_is_not_markup(state):
    """Not typed by the user, but derived from their footage via a model that
    will repeat what it reads on screen."""
    state.elements[0] = state.elements[0].model_copy(update={"label": PAYLOAD})

    assert "<script>alert" not in _html(state)


async def test_the_escaped_text_is_still_present_and_readable(state):
    """Escaping must not silently drop the content — a reviewer needs to see
    what was written, even when what was written is hostile."""
    state.production = state.production.model_copy(update={"title": PAYLOAD})

    assert "&lt;script&gt;" in _html(state)


async def test_an_ordinary_ampersand_survives_a_title(state):
    """The everyday half of the same bug: a real title with punctuation."""
    state.production = state.production.model_copy(
        update={"title": "Fish & Chips <the documentary>"}
    )
    html = _html(state)

    assert "Fish &amp; Chips" in html
    assert "&lt;the documentary&gt;" in html


async def test_an_attribute_break_out_is_neutralised(state):
    """Some values land inside HTML attributes, where a bare quote escapes the
    attribute without needing a tag at all."""
    state.production = state.production.model_copy(
        update={"title": '" onmouseover="alert(1)'}
    )

    assert 'onmouseover="alert(1)"' not in _html(state)


async def test_the_report_still_renders_normally(state):
    """The guard against fixing this by breaking the document."""
    html = _html(state)

    assert html.lstrip().startswith("<!doctype html>")
    assert "Golden Hour" in html
    assert "CLEARANCE REPORT" in html.upper()
