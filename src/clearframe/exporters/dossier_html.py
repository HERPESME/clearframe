"""Print-ready HTML clearance dossier renderer."""

from jinja2 import Template

from clearframe.dossier import ClearanceDossier
from clearframe.models import research_is_incomplete
from clearframe.reportmeta import (
    CONFIDENTIALITY,
    control_rows,
    reference,
    signatories,
    status,
)
from clearframe.timecode import seconds_to_tc

BAND_HEX = {"CRITICAL": "#c0392b", "HIGH": "#e67e22", "MEDIUM": "#2980b9", "LOW": "#27ae60"}

# autoescape=True, because `jinja2.Template` does not do it by default and every
# interesting value in this report is written by a person.
#
# A decision note is free text a reviewer types. A production title and the
# sponsor list come off the upload form. `Decision.reviewer` is an email address
# and display name chosen at sign-up. All of them were going into the HTML raw,
# and this document is served same-origin from
# `/api/productions/{pid}/artifacts/dossier.html` — so a `<script>` in a note ran
# against the signed-in session. The session cookie is HttpOnly and unreadable by
# script, but same-origin fetch sends it anyway, so the script could do whatever
# the signed-in user could; on a `legal` role that includes signing off findings.
#
# Nothing in this template relied on raw HTML — no `|safe`, no `Markup` — so
# turning it on changes only the hostile cases and the honest punctuation ones
# (a film really called "Fish & Chips" kept its ampersand unescaped before).
# Anything that ever DOES need markup must now say `|safe` and be visible as an
# exception, which is the point of the default being the other way round.
_TEMPLATE = Template(
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Clearance Report — {{ d.production.title }}</title>
<style>
  body { font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a; margin: 40px auto; max-width: 900px; line-height: 1.5; }
  h1 { font-size: 26px; margin-bottom: 0; }
  .meta { color: #555; font-size: 13px; margin-bottom: 18px; }
  .disclaimer { background: #fdf6e3; border: 1px solid #e0d5a8; padding: 10px 14px; font-size: 12px; margin: 16px 0 28px; }
  table.summary { border-collapse: collapse; margin-bottom: 30px; }
  table.summary td, table.summary th { border: 1px solid #ccc; padding: 6px 14px; font-size: 13px; }
  .entry { border: 1px solid #ddd; border-left: 6px solid #999; padding: 16px 20px; margin-bottom: 22px; page-break-inside: avoid; }
  .chip { display: inline-block; padding: 2px 10px; border-radius: 10px; color: #fff; font-size: 11px; font-family: Helvetica, Arial, sans-serif; letter-spacing: .5px; }
  .cat { background: #666; }
  .label { font-size: 18px; font-weight: bold; margin-right: 8px; }
  .factors, .tcs { color: #555; font-size: 12px; }
  .section { margin-top: 10px; font-size: 13px; }
  .section h4 { margin: 10px 0 4px; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #444; }
  .citation { font-size: 12px; margin: 4px 0 4px 12px; }
  .citation a { color: #2980b9; }
  pre.email { background: #f7f7f7; border: 1px solid #e0e0e0; padding: 10px; font-size: 11px; overflow-x: auto; white-space: pre-wrap; }

  /* The cover. A clearance report is attached to an E&O application and read
     months later by somebody who was not in the room, so it has to say on its
     face which cut was reviewed, by whom, when and against which territories. */
  .cover { border-bottom: 3px double #1a1a2e; padding-bottom: 26px; margin-bottom: 28px; }
  .legend { font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: #8a6d1f; background: #fdf6e3; border: 1px solid #e0d5a8; padding: 8px 12px; margin-bottom: 26px; }
  .doctitle { font-size: 13px; letter-spacing: .22em; text-transform: uppercase; color: #666; margin-bottom: 6px; }
  .ref { font-family: Helvetica, Arial, sans-serif; font-size: 13px; color: #444; }
  .status { font-style: italic; color: #444; margin: 4px 0 18px; }
  table.control { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  table.control td { border: 1px solid #ddd; padding: 6px 12px; vertical-align: top; }
  table.control td:first-child { width: 210px; font-weight: bold; background: #fafafa; }
  .signoff { font-size: 12.5px; margin-top: 16px; }
  .signoff li { margin: 2px 0; }
  h2.part { font-size: 15px; letter-spacing: .12em; text-transform: uppercase; color: #1a1a2e; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 34px; }

  /* Print. There was one `page-break-inside` rule in 365 lines and nothing
     else, so "print to PDF" produced a screen layout on paper: no margins, no
     page breaks, and every citation URL invisible because it lived in an href. */
  @page { size: A4; margin: 18mm 16mm 20mm; }
  @media print {
    body { margin: 0; max-width: none; font-size: 10.5pt; }
    a { color: inherit; text-decoration: none; }
    .citation a[href]::after, .section a[href]::after { content: " (" attr(href) ")"; font-size: 9pt; color: #555; word-break: break-all; }
    .cover { page-break-after: always; border-bottom: none; }
    h2.part { page-break-before: always; }
    .entry, table.control, table.summary { page-break-inside: avoid; }
    h1, h2, h3, h4 { page-break-after: avoid; }
    p, li { orphans: 3; widows: 3; }
  }
  .decision { margin-top: 10px; font-size: 13px; padding: 8px 12px; background: #eef5ee; border: 1px solid #cfe3cf; }
  .decision.pending { background: #fbeeee; border-color: #e3cfcf; }
  .unscanned { background: #fbeeee; border: 1px solid #e3cfcf; padding: 10px 14px; font-size: 13px; margin-bottom: 24px; }
  .verdict { display:inline-block; padding:2px 10px; border-radius:10px; font-size:11px; font-family:Helvetica,Arial,sans-serif; letter-spacing:.5px; color:#fff; }
  .v-FINGERPRINTED { background:#2980b9; } .v-CORROBORATED { background:#27ae60; }
  .route { display:inline-block; padding:2px 10px; border-radius:10px; font-size:11px; font-family:Helvetica,Arial,sans-serif; letter-spacing:.5px; color:#fff; background:#34495e; }
  .r-LOCAL { background:#16a085; } .r-STATUTE { background:#8e44ad; } .r-SEARCH { background:#2980b9; }
  .r-DEEP { background:#d35400; } .r-BLOCKED { background:#7f8c8d; }
  .tone { display:inline-block; padding:2px 10px; border-radius:10px; font-size:11px; font-family:Helvetica,Arial,sans-serif; letter-spacing:.5px; color:#fff; }
  .t-FAVOURABLE { background:#16a085; } .t-NEUTRAL { background:#95a5a6; }
  .t-UNFLATTERING { background:#e67e22; } .t-DISPARAGING { background:#c0392b; }
  .exposure { background:#fdeaea; border:1px solid #e9b8b8; padding:10px 14px; margin:18px 0 24px; font-size:13px; }
  .exposure td, .exposure th { padding:4px 10px 4px 0; text-align:left; font-size:12px; vertical-align:top; }
  .platform { background:#fbeee6; border:1px solid #e8c4a8; padding:10px 14px; margin:18px 0 24px; font-size:13px; }
  .platform td, .platform th { padding:4px 10px 4px 0; text-align:left; font-size:12px; vertical-align:top; }
  .pa-CLAIM_LIKELY { color:#c0392b; font-weight:bold; }
  .pa-CLAIM_POSSIBLE { color:#e67e22; }
  .sponsor { background:#fdf2e9; border:1px solid #f0c9a0; padding:10px 14px; margin:18px 0 24px; font-size:13px; }
  .context { background:#eaf2f8; border:1px solid #b8d4e8; padding:8px 14px; margin:-10px 0 20px; font-size:12px; }
  .routing { background:#f4f1fa; border:1px solid #d9d2ea; padding:10px 14px; margin:18px 0 24px; font-size:13px; }
  .routing td, .routing th { padding:3px 10px 3px 0; text-align:left; font-size:12px; } .v-SINGLE_SOURCE { background:#7f8c8d; } .v-CONFLICTED { background:#c0392b; }
  table.terr { border-collapse: collapse; margin: 6px 0 2px; font-size: 12px; }
  table.terr td, table.terr th { border: 1px solid #ddd; padding: 4px 10px; text-align: left; }
  table.terr th { background: #f5f5f5; }
  .signal { font-size: 12px; margin: 4px 0 4px 12px; }
  .signal.material { border-left: 3px solid #c0392b; padding-left: 8px; }
  .conflict-note { background:#fbeeee; border:1px solid #e3cfcf; padding:8px 12px; font-size:12px; margin-top:6px; }
  .cov { display:inline-block; padding:2px 10px; border-radius:10px; font-size:11px; font-family:Helvetica,Arial,sans-serif; letter-spacing:.5px; color:#fff; }
  .cov-COVERED { background:#27ae60; } .cov-PARTIAL { background:#e67e22; }
  .cov-NOT_COVERED { background:#c0392b; } .cov-UNKNOWN { background:#7f8c8d; }
  .gap { background:#fdf3e7; border:1px solid #e8d3b8; padding:8px 12px; font-size:12px; margin-top:6px; }
</style>
</head>
<body>
<section class="cover">
<div class="legend">{{ confidentiality }}</div>
<div class="doctitle">Rights Clearance Report</div>
<h1>“{{ d.production.title }}”</h1>
<div class="ref">{{ reference }}</div>
<div class="status">{{ status }}</div>

<table class="control">
{% for key, value in control %}<tr><td>{{ key }}</td><td>{{ value }}</td></tr>
{% endfor %}</table>

<div class="disclaimer"><strong>Basis and limitations.</strong> {{ d.disclaimer }}</div>

{% if signatories %}
<div class="signoff"><strong>Reviewed and signed off by</strong>
<ul>{% for who in signatories %}<li>{{ who }}</li>{% endfor %}</ul></div>
{% endif %}
</section>

<h2 class="part">1 · Summary of findings</h2>
<table class="summary">
<tr><th>CRITICAL</th><th>HIGH</th><th>MEDIUM</th><th>LOW</th><th>Incomplete research</th><th>Pending decisions</th>
<th>Identity corroborated</th><th>Identity disputed</th><th>Live enforcement signals</th>
<th>Already licensed</th><th>Licence gaps</th><th>Unlicensed</th></tr>
<tr><td>{{ d.summary['CRITICAL'] }}</td><td>{{ d.summary['HIGH'] }}</td><td>{{ d.summary['MEDIUM'] }}</td>
<td>{{ d.summary['LOW'] }}</td><td>{{ d.summary['incomplete_research'] }}</td><td>{{ d.summary['pending_decisions'] }}</td>
<td>{{ d.summary.get('identity_corroborated', 0) }}</td><td>{{ d.summary.get('identity_conflicts', 0) }}</td>
<td>{{ d.summary.get('material_freshness_signals', 0) }}</td>
<td>{{ d.summary.get('coverage_covered', 0) }}</td><td>{{ d.summary.get('coverage_partial', 0) }}</td>
<td>{{ d.summary.get('coverage_not_covered', 0) }}</td></tr>
</table>

{% if d.use_context.value != 'EXPRESSIVE' %}
<div class="context"><strong>Use context: {{ d.use_context.value }}.</strong>
Commercial speech carries no expressive-work shield — Rogers v. Grimaldi protects films, not
advertisements, and the Supreme Court narrowed it further in Jack Daniel's v. VIP (2023).
Risk is banded accordingly, and findings that would otherwise need only a posture check are
escalated to full rights research because permission, not posture, is the open question.</div>
{% endif %}

{% if d.exposures %}
<div class="exposure">
<strong>On-screen exposure ({{ d.exposures|length }}):</strong>
not intellectual property, and nobody owns any of it — which is exactly why it gets missed.
Severity is set by the strictest release territory, because a publication cannot be
un-made in one country and left standing in another.
<table>
<tr><th>What</th><th>Where</th><th>Severity</th><th>Governing regime</th><th>Fix</th></tr>
{% for x in d.exposures %}
<tr><td>{{ x.description }}</td>
<td>{% for r in x.time_ranges %}{{ tc(r.start_s) }}–{{ tc(r.end_s) }}{% if not loop.last %}, {% endif %}{% endfor %}</td>
<td><span class="chip" style="background: {{ band_hex[x.band.value] }}">{{ x.band.value }} · {{ x.score }}</span></td>
<td>{{ x.territory }} — {{ x.regime }}</td>
<td>{{ x.remedy }}</td></tr>
{% endfor %}
</table>
</div>
{% endif %}

{% set flagged = d.platform_outcomes|selectattr('action.value','in',['CLAIM_LIKELY','CLAIM_POSSIBLE'])|list %}
{% if flagged %}
<div class="platform">
<strong>Platform enforcement — {{ flagged[0].platform }} ({{ flagged|length }}):</strong>
this is separate from legal merit. Automated content matching does not evaluate fair use,
so a finding with a strong legal defence can still be claimed on upload. Ranked by how
likely the platform is to act, which is not the same order as legal risk.
<table>
<tr><th>Finding</th><th>Outcome</th><th>Fix</th><th>Revenue</th></tr>
{% for o in flagged %}
<tr><td>{{ label_for(o.element_id) }}</td>
<td class="pa-{{ o.action.value }}">{{ o.action.value|replace('_',' ') }} · {{ o.confidence }}</td>
<td>{{ o.remedy }}</td><td>{{ o.revenue_impact }}</td></tr>
{% endfor %}
</table>
</div>
{% endif %}

{% if d.sponsor_conflicts %}
<div class="sponsor">
<strong>Sponsor conflicts ({{ d.sponsor_conflicts|length }}):</strong>
these are not infringements. Category exclusivity is standard in sponsorship contracts, so a
rival mark in shot can breach the deal even though the depiction is entirely lawful.
<table>
<tr><th>Finding</th><th>Owner</th><th>Competes with</th><th>Sector</th></tr>
{% for c in d.sponsor_conflicts %}
<tr><td>{{ c.label }}</td><td>{{ c.detected_owner }}</td><td>{{ c.conflicts_with }}</td><td>{{ c.sector }}</td></tr>
{% endfor %}
</table>
</div>
{% endif %}

{% set free = d.entries|selectattr('route')|selectattr('route.tier.value','in',['LOCAL','STATUTE'])|list %}
{% if free %}
<div class="routing">
<strong>Resolved without rights research ({{ free|length }} of {{ d.entries|length }}):</strong>
these findings were answered by settled law or by verified local ownership rather than by an
open-web investigation. They are reported in full, with authority, because E&amp;O carriers do not
accept fair use offered in place of clearance and distributors reject incidental use asserted
without documentation. {{ d.summary.get('deep_research_runs', 0) }} finding(s) required deep research.
<table>
<tr><th>Finding</th><th>Route</th><th>Authority</th><th>Required action</th></tr>
{% for e in free %}
<tr><td>{{ e.element.label }}</td><td><span class="route r-{{ e.route.tier.value }}">{{ e.route.tier.value }}</span></td>
<td>{{ e.route.basis }}</td><td>{{ e.route.disposition }}</td></tr>
{% endfor %}
</table>
</div>
{% endif %}

{% if d.territories %}
<div class="meta" style="margin:-18px 0 24px;">Release territories assessed:
<strong>{{ d.territories|join(', ') }}</strong> — clearance exposure is jurisdictional and is banded per territory below.</div>
{% endif %}

{% if d.unscanned_ranges %}
<div class="unscanned"><strong>Unscanned footage:</strong>
{% for r in d.unscanned_ranges %} {{ tc(r.start_s) }}–{{ tc(r.end_s) }}{% if not loop.last %},{% endif %}{% endfor %}
— these ranges were not analyzed and are NOT covered by this report.</div>
{% endif %}

<h2 class="part">2 · Schedule of findings</h2>
{% for e in d.entries %}
<div class="entry" style="border-left-color: {{ band_hex[e.risk.band.value] }}">
  <span class="label">{{ e.element.label }}</span>
  <span class="chip cat">{{ e.element.category.value }}</span>
  <span class="chip" style="background: {{ band_hex[e.risk.band.value] }}">{{ e.risk.band.value }} · {{ e.risk.score }}</span>
  {% if e.risk.de_minimis %}<span class="chip" style="background:#95a5a6">DE MINIMIS</span>{% endif %}
  {% if e.corroboration %}<span class="verdict v-{{ e.corroboration.verdict.value }}">{{ e.corroboration.verdict.value|replace('_',' ') }}</span>{% endif %}
  {% if e.coverage %}<span class="cov cov-{{ e.coverage.status.value }}">{{ e.coverage.status.value|replace('_',' ') }}</span>{% endif %}
  {% if e.route %}<span class="route r-{{ e.route.tier.value }}">{{ e.route.tier.value }}</span>{% endif %}
  {% if e.element.depiction %}<span class="tone t-{{ e.element.depiction.value }}">SHOWN {{ e.element.depiction.value }}</span>{% endif %}
  <div class="tcs">Appears:
    {% for r in e.element.time_ranges %}{{ tc(r.start_s) }}–{{ tc(r.end_s) }}{% if not loop.last %}, {% endif %}{% endfor %}
    · {{ e.element.description }}</div>
  <div class="factors">Score factors:
    {% for k, v in e.risk.factors.items() %}{{ k }}={{ v }}{% if not loop.last %} · {% endif %}{% endfor %}</div>

  {% if e.route %}
  <div class="section">
    <h4>How this was resolved</h4>
    <div>{{ e.route.rationale }}</div>
    {% if e.route.basis %}<div class="meta"><strong>Authority:</strong> {{ e.route.basis }}</div>{% endif %}
    {% if e.route.disposition %}<div><strong>Required action:</strong> {{ e.route.disposition }}</div>{% endif %}
  </div>
  {% endif %}

  {% set rows = d.defences.get(e.element.id, []) %}
  {% if rows %}
  <div class="section">
    <h4>Defences by jurisdiction</h4>
    <table>
    {% for r in rows %}
      <tr><td><strong>{{ r.territory }}</strong></td>
      <td>{{ 'available' if r.available else 'NOT available' }}</td>
      <td>{{ r.name }}</td>
      <td class="meta">{{ r.authority }}{% if r.note %} — {{ r.note }}{% endif %}</td></tr>
    {% endfor %}
    </table>
  </div>
  {% endif %}

  <div class="section">
    <h4>Rights research</h4>
    {% if not incomplete(e.research) %}
      <div><strong>Owner:</strong> {{ e.research.owner }} ({{ e.research.owner_confidence }} confidence)
        · <strong>Posture:</strong> {{ e.research.licensing_posture.value }}
        {% if e.research.licensing_contact %} · <strong>Contact:</strong> {{ e.research.licensing_contact }}{% endif %}
        {% if e.research.estimated_license_cost_band %} · <strong>Est. cost:</strong> {{ e.research.estimated_license_cost_band }}{% endif %}</div>
      {% if e.research.litigation_history %}
        <div><strong>Enforcement history:</strong>
        <ul>{% for h in e.research.litigation_history %}<li>{{ h }}</li>{% endfor %}</ul></div>
      {% endif %}
    {% else %}
      <div><strong>RESEARCH INCOMPLETE</strong> — rights holder could not be established from open-web sources; manual investigation required.</div>
    {% endif %}
    {% if e.research and e.research.basis %}
      <h4>Evidence basis</h4>
      {% for b in e.research.basis %}
        <div class="citation">[{{ b.field }}] <a href="{{ b.url }}">{{ b.url }}</a>
          — “{{ b.excerpt }}” <em>({{ b.confidence }} confidence: {{ b.reasoning }})</em></div>
      {% endfor %}
    {% endif %}
  </div>

  {% if e.court %}
  <div class="section">
    <h4>Clearance Court opinion</h4>
    <div><strong>Ruling:</strong>
      <span class="chip" style="background: {{ {'clear_required': '#c0392b', 'escalate': '#e67e22', 'defensible': '#27ae60'}[e.court.holding] }}">{{ e.court.holding|replace('_',' ')|upper }}</span>
      ({{ e.court.confidence }} confidence) — {{ e.court.reasoning }}</div>
    {% for b in e.court.briefs %}
      <div class="citation"><strong>{{ 'Studio Counsel' if b.side == 'counsel' else 'Fair Use Advocate' }}:</strong> {{ b.argument }}
      {% for p in b.precedents %}
        <div>· <em>{{ p.case_name }}</em>, {{ p.citation }} — {{ p.holding }} <span style="color:#777">({{ p.relevance }})</span>
        {% if p.quote %}<div style="margin: 3px 0 3px 14px; font-style: italic; color: #555;">“{{ p.quote }}”{% if p.source_url %} <a href="{{ p.source_url }}">[source]</a>{% endif %}</div>{% endif %}
        </div>
      {% endfor %}
      </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if e.coverage %}
  <div class="section">
    <h4>Rights already held</h4>
    <div class="{{ 'gap' if e.coverage.gaps else '' }}">
      {{ e.coverage.note }}
      {% if e.coverage.gaps %}
        <ul style="margin:6px 0 0 18px;">{% for g in e.coverage.gaps %}<li>{{ g }}</li>{% endfor %}</ul>
      {% endif %}
    </div>
  </div>
  {% endif %}

  {% if e.corroboration %}
  <div class="section">
    <h4>Identity verification</h4>
    <div class="{{ 'conflict-note' if e.corroboration.verdict.value == 'CONFLICTED' else '' }}">
      {{ e.corroboration.note }}
      {% if e.corroboration.detected_label %}
        <em>({{ e.corroboration.detector }} read “{{ e.corroboration.detected_label }}”)</em>
      {% endif %}
    </div>
  </div>
  {% endif %}

  {% if e.territory %}
  <div class="section">
    <h4>Territory exposure</h4>
    <table class="terr">
      <tr><th>Territory</th><th>Band</th><th>Basis</th></tr>
      {% for t in e.territory %}
      <tr>
        <td>{{ t.territory }}</td>
        <td><span class="chip" style="background: {{ band_hex[t.band.value] }}">{{ t.band.value }}</span></td>
        <td>{{ t.rationale }}{% if t.authority %}<div style="color:#777; font-size:11px;">{{ t.authority }}</div>{% endif %}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  {% if e.freshness %}
  <div class="section">
    <h4>Live rights-holder signals <span style="font-weight:normal;text-transform:none;letter-spacing:0;color:#777;">(Parallel Search, at report time)</span></h4>
    {% for s in e.freshness %}
      <div class="signal {{ 'material' if s.material else '' }}">
        {% if s.material %}<strong>ENFORCEMENT SIGNAL</strong> — {% endif %}
        <a href="{{ s.url }}">{{ s.title }}</a> — “{{ s.excerpt }}”
      </div>
    {% endfor %}
  </div>
  {% endif %}

  <div class="section">
    <h4>Remediation options</h4>
    {% for o in e.options %}
      <div><strong>{{ o.kind|replace('_',' ')|title }}:</strong> {{ o.summary }}{% if o.est_cost_band %} ({{ o.est_cost_band }}){% endif %}</div>
      {% if o.kind == 'license' %}<pre class="email">{{ o.detail }}</pre>{% else %}<div class="citation">{{ o.detail }}</div>{% endif %}
    {% endfor %}
  </div>

  {% if e.decision %}
    <div class="decision"><strong>Decision:</strong> {{ e.decision.action|replace('_',' ')|upper }}
      — {{ e.decision.note }} <em>({{ e.decision.reviewer }}, {{ e.decision.role }})</em></div>
  {% else %}
    <div class="decision pending"><strong>Decision: PENDING REVIEW</strong></div>
  {% endif %}
</div>
{% endfor %}

{% if audit %}
<h2 class="part">3 · Audit trail</h2>
<table class="summary">
<tr><th>When</th><th>Actor</th><th>Role</th><th>Event</th><th>Detail</th></tr>
{% for a in audit %}
<tr><td>{{ a.at }}</td><td>{{ a.actor }}</td><td>{{ a.role }}</td><td>{{ a.event }}</td><td>{{ a.detail }}</td></tr>
{% endfor %}
</table>
{% endif %}
</body>
</html>
""",
    autoescape=True,
)


def render_dossier_html(d: ClearanceDossier) -> str:
    return _TEMPLATE.render(
        d=d,
        # Computed in `reportmeta`, not here, so the Word rendering of the
        # same report cannot disagree with this one about the reference
        # number, the status or which cut was reviewed.
        confidentiality=CONFIDENTIALITY,
        reference=reference(d.production),
        status=status(d),
        control=control_rows(d),
        signatories=signatories(d),
        band_hex=BAND_HEX,
        tc=lambda s: seconds_to_tc(s, fps=d.production.fps),
        incomplete=research_is_incomplete,
        audit=d.audit,
        # Platform outcomes are keyed by element id; the table needs the label.
        label_for={e.element.id: e.element.label for e in d.entries}.get,
    )
