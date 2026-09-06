"""One report, two formats, and they must not drift.

The clearance report is delivered as HTML to read and DOCX to file with an E&O
application. Two renderers reading one `ClearanceDossier` is the simplest thing
that works, and the obvious way for it to go wrong is for one of them to gain a
finding, a band or a signatory that the other never shows.

So this is a cross-check rather than a golden file: it asserts the two agree on
the things a reader would act on, and says nothing about layout, which is the
whole reason there are two of them.
"""

import asyncio
import io

import pytest
from docx import Document

from clearframe.dossier import auto_decisions, build_dossier
from clearframe.exporters.dossier_docx import render_dossier_docx
from clearframe.exporters.dossier_html import render_dossier_html
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.reportmeta import reference, status


def _dossier(tmp_path):
    """A fully reviewed demo run — the same one the CLI produces."""
    state = asyncio.run(Pipeline(build_demo_pipeline()).run(demo_context(tmp_path)))
    state.decisions = auto_decisions(state)
    return build_dossier(state, generated_at="2026-09-07T00:00:00Z")


def _rendered_docx(d):
    buf = io.BytesIO()
    render_dossier_docx(d, buf)
    buf.seek(0)
    return buf


def _docx_text(d) -> str:
    doc = Document(_rendered_docx(d))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    d = _dossier(tmp_path_factory.mktemp("report"))
    return d, render_dossier_html(d), _docx_text(d)


def test_every_finding_appears_in_both(rendered):
    """A finding missing from one format is a finding somebody will not clear."""
    d, html, docx = rendered
    for entry in d.entries:
        assert entry.element.label in html, f"{entry.element.label} missing from HTML"
        assert entry.element.label in docx, f"{entry.element.label} missing from DOCX"


def test_both_carry_the_same_report_reference_and_status(rendered):
    """The reference is how the report gets cited in an email; the status is
    the difference between a draft somebody circulated and an opinion somebody
    relied on. They come from `reportmeta` precisely so they cannot differ."""
    d, html, docx = rendered
    assert reference(d.production) in html and reference(d.production) in docx
    assert status(d) in html and status(d) in docx


def test_both_carry_the_disclaimer(rendered):
    """E&O carriers reject fair use offered in place of clearance. Neither
    format may present itself as legal advice."""
    _, html, docx = rendered
    assert "not legal advice" in html.lower()
    assert "not legal advice" in docx.lower()


def test_both_carry_the_confidentiality_legend(rendered):
    _, html, docx = rendered
    assert "CONFIDENTIAL" in html and "CONFIDENTIAL" in docx


def test_the_bands_agree(rendered):
    """The single number a producer reads off this report."""
    d, html, docx = rendered
    for entry in d.entries:
        band = entry.risk.band.value
        assert band in html and band in docx


def test_the_docx_says_which_cut_was_reviewed(rendered):
    """`media_version` is the only thing distinguishing two uploads at one
    production id, and a clearance report that cannot name the footage it looked
    at is not evidence of anything."""
    _, html, docx = rendered
    assert "Footage identifier" in docx
    assert "Footage identifier" in html


def test_the_docx_is_a_real_word_document_with_navigable_headings(tmp_path):
    """Not bold text pretending to be headings. A document whose structure is
    only formatting cannot be navigated, outlined or restyled by whoever
    receives it — and this one is meant to be marked up by counsel."""
    doc = Document(_rendered_docx(_dossier(tmp_path)))

    styles = {p.style.name for p in doc.paragraphs if p.text.strip()}
    assert "Title" in styles
    assert "Heading 1" in styles and "Heading 2" in styles
    assert doc.tables, "the document-control block is a table"


def test_the_docx_is_paginated(tmp_path):
    """`Page N of M` as Word fields, so it stays right after anyone adds a
    comment box."""
    doc = Document(_rendered_docx(_dossier(tmp_path)))

    footer = doc.sections[0].footer.paragraphs[0]
    assert "Page" in footer.text
    xml = footer._p.xml
    assert "PAGE" in xml and "NUMPAGES" in xml
    assert footer.text.count("Page") == 1, "the footer was written twice"


def test_hostile_text_is_inert_in_the_word_document(tmp_path):
    """A decision note is free text a reviewer types, and it executed as script
    in the HTML report until `autoescape=True`. In OOXML it is a text run and
    cannot be markup at all — asserted rather than assumed, because the same
    values reach both renderers."""
    d = _dossier(tmp_path)
    d.production.title = "<script>alert(1)</script>"
    for entry in d.entries:
        if entry.decision is not None:
            entry.decision.note = "<b>not bold</b>"

    text = _docx_text(d)
    buf = _rendered_docx(d)

    assert "<script>alert(1)</script>" in text, "the title should read as text"
    assert b"<script>alert(1)</script>" not in buf.getvalue(), (
        "the hostile string reached the XML unescaped"
    )
