"""Print-ready HTML clearance dossier renderer."""

from jinja2 import Template

from clearframe.dossier import ClearanceDossier
from clearframe.models import research_is_incomplete
from clearframe.timecode import seconds_to_tc

BAND_HEX = {"CRITICAL": "#c0392b", "HIGH": "#e67e22", "MEDIUM": "#2980b9", "LOW": "#27ae60"}

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
  .decision { margin-top: 10px; font-size: 13px; padding: 8px 12px; background: #eef5ee; border: 1px solid #cfe3cf; }
  .decision.pending { background: #fbeeee; border-color: #e3cfcf; }
  .unscanned { background: #fbeeee; border: 1px solid #e3cfcf; padding: 10px 14px; font-size: 13px; margin-bottom: 24px; }
</style>
</head>
<body>
<h1>Clearance Report — “{{ d.production.title }}”</h1>
<div class="meta">Generated {{ d.generated_at }} · footage {{ d.production.footage_uri }} ·
{{ '%.1f'|format(d.production.duration_s) }}s @ {{ d.production.fps|int }}fps · ClearFrame automated clearance pipeline</div>
<div class="disclaimer">{{ d.disclaimer }}</div>

<table class="summary">
<tr><th>CRITICAL</th><th>HIGH</th><th>MEDIUM</th><th>LOW</th><th>Incomplete research</th><th>Pending decisions</th></tr>
<tr><td>{{ d.summary['CRITICAL'] }}</td><td>{{ d.summary['HIGH'] }}</td><td>{{ d.summary['MEDIUM'] }}</td>
<td>{{ d.summary['LOW'] }}</td><td>{{ d.summary['incomplete_research'] }}</td><td>{{ d.summary['pending_decisions'] }}</td></tr>
</table>

{% if d.unscanned_ranges %}
<div class="unscanned"><strong>Unscanned footage:</strong>
{% for r in d.unscanned_ranges %} {{ tc(r.start_s) }}–{{ tc(r.end_s) }}{% if not loop.last %},{% endif %}{% endfor %}
— these ranges were not analyzed and are NOT covered by this report.</div>
{% endif %}

{% for e in d.entries %}
<div class="entry" style="border-left-color: {{ band_hex[e.risk.band.value] }}">
  <span class="label">{{ e.element.label }}</span>
  <span class="chip cat">{{ e.element.category.value }}</span>
  <span class="chip" style="background: {{ band_hex[e.risk.band.value] }}">{{ e.risk.band.value }} · {{ e.risk.score }}</span>
  {% if e.risk.de_minimis %}<span class="chip" style="background:#95a5a6">DE MINIMIS</span>{% endif %}
  <div class="tcs">Appears:
    {% for r in e.element.time_ranges %}{{ tc(r.start_s) }}–{{ tc(r.end_s) }}{% if not loop.last %}, {% endif %}{% endfor %}
    · {{ e.element.description }}</div>
  <div class="factors">Score factors:
    {% for k, v in e.risk.factors.items() %}{{ k }}={{ v }}{% if not loop.last %} · {% endif %}{% endfor %}</div>

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
<h3 style="font-size:15px; text-transform:uppercase; letter-spacing:1px;">Audit trail</h3>
<table class="summary">
<tr><th>When</th><th>Actor</th><th>Role</th><th>Event</th><th>Detail</th></tr>
{% for a in audit %}
<tr><td>{{ a.at }}</td><td>{{ a.actor }}</td><td>{{ a.role }}</td><td>{{ a.event }}</td><td>{{ a.detail }}</td></tr>
{% endfor %}
</table>
{% endif %}
</body>
</html>
"""
)


def render_dossier_html(d: ClearanceDossier) -> str:
    return _TEMPLATE.render(
        d=d,
        band_hex=BAND_HEX,
        tc=lambda s: seconds_to_tc(s, fps=d.production.fps),
        incomplete=research_is_incomplete,
        audit=d.audit,
    )
