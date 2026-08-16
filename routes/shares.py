"""routes/shares.py — time-limited shareable health snapshots.

Authenticated (manage your own links):
  POST   /api/share/snapshot            {label, days_valid}  → create
  GET    /api/share/snapshots                                → list
  POST   /api/share/snapshot/<id>/revoke                     → revoke

Public (no auth — the whole point is a link you can hand to someone):
  GET    /share/<token>                 → read-only HTML snapshot page

The public route reveals nothing for a missing/expired/revoked token, sets
no-store + noindex, and only ever renders the SAFE compiled subset.
"""
from flask import Blueprint, request, jsonify, Response
from markupsafe import escape
from auth import require_auth
from db.shares import (create_snapshot, list_snapshots, revoke_snapshot,
                       resolve_snapshot, compile_snapshot)

bp = Blueprint('shares', __name__)


@bp.route('/api/share/snapshot', methods=['POST'])
@require_auth
def api_create():
    data = request.json or {}
    snap = create_snapshot(label=data.get('label', ''), days_valid=data.get('days_valid', 7),
                           scope=data.get('scope', 'summary'))
    return jsonify({'success': True, 'snapshot': snap})


@bp.route('/api/share/snapshots')
@require_auth
def api_list():
    return jsonify({'snapshots': list_snapshots()})


@bp.route('/api/share/snapshot/<sid>/revoke', methods=['POST'])
@require_auth
def api_revoke(sid):
    revoke_snapshot(sid)
    return jsonify({'success': True})


def _gone(msg):
    """A dead link reveals nothing about whether it ever existed."""
    html = _PAGE_SHELL.format(
        title='Link unavailable',
        body=f'<div class="msg"><h1>This link isn\'t available</h1><p>{escape(msg)}</p>'
             f'<p class="muted">Health snapshots expire and can be turned off by their owner.</p></div>')
    return Response(html, status=410, mimetype='text/html',
                    headers={'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow'})


@bp.route('/share/<token>')
def public_snapshot(token):
    resolved = resolve_snapshot(token)
    if not resolved:
        return _gone('It may have expired or been turned off.')
    d = compile_snapshot(resolved['user_id'], resolved['id'], resolved.get('scope', 'summary'))
    html = _PAGE_SHELL.format(title='Health snapshot', body=_render_snapshot(d, resolved))
    return Response(html, mimetype='text/html',
                    headers={'Cache-Control': 'no-store, max-age=0',
                             'X-Robots-Tag': 'noindex, nofollow'})


def _render_snapshot(d, resolved):
    e = lambda s: str(escape('' if s is None else s))
    meta = ' · '.join(filter(None, [
        f'Age {e(d["age"])}' if d.get('age') else '',
        e(d['gender']) if d.get('gender') else '',
        f'Blood type {e(d["blood_type"])}' if d.get('blood_type') else '',
    ]))
    meds = ''.join(
        f'<tr><td>{e(m.get("name"))}</td><td>{e((str(m.get("dosage") or "") + " " + (m.get("unit") or "")).strip())}</td>'
        f'<td>{e(", ".join(m.get("times") or []))}</td></tr>'
        for m in d.get('medications', []))
    meds_block = (f'<table><thead><tr><th>Medicine</th><th>Dose</th><th>Times</th></tr></thead><tbody>{meds}</tbody></table>'
                  if meds else '<p class="muted">No active medicines.</p>')
    vrows = ''.join(
        f'<tr><td>{e(k.replace("_", " "))}</td>'
        f'<td>{e(v.get("value1"))}{("/" + e(v.get("value2"))) if v.get("value2") else ""} {e(v.get("unit"))}</td>'
        f'<td>{e(v.get("date"))}</td></tr>'
        for k, v in (d.get('vitals') or {}).items())
    vitals_block = (f'<table><thead><tr><th>Vital</th><th>Latest</th><th>Measured</th></tr></thead><tbody>{vrows}</tbody></table>'
                    if vrows else '<p class="muted">No vitals recorded.</p>')
    adh = d.get('adherence_30d') or {}
    adh_line = (f'{e(adh.get("pct"))}% ({e(adh.get("taken"))}/{e(adh.get("total"))} scheduled doses, last 30 days)'
                if adh.get('total') else 'No dose history yet')
    flags = ''
    if d.get('conditions') or d.get('allergies'):
        flags = '<div class="flags">' + \
            (f'<div><b>Conditions:</b> {e(d["conditions"])}</div>' if d.get('conditions') else '') + \
            (f'<div><b>Allergies:</b> {e(d["allergies"])}</div>' if d.get('allergies') else '') + '</div>'
    label = f' · {e(resolved["label"])}' if resolved.get('label') else ''

    # Binder scope adds the extra doctor-relevant sections (labs, vaccines,
    # advance-care wishes, dental/vision, emergency contacts).
    binder_html = ''
    if d.get('scope') == 'binder':
        ac = d.get('advance_care') or {}
        ac_rows = ''.join(f'<div><b>{lbl}:</b> {e(val)}</div>' for lbl, val in (
            ('Organ donor', ac.get('organ_donor')), ('Medical wishes', ac.get('directive_wishes')),
            ('Directives kept', ac.get('directive_location'))) if val)
        ac_block = f'<h2>Advance care &amp; wishes</h2><div class="flags">{ac_rows}</div>' if ac_rows else ''

        labs = ''.join(f'<tr><td>{e(l.get("name"))}</td><td>{e(l.get("value"))} {e(l.get("unit"))}</td>'
                       f'<td>{e(l.get("date"))}</td></tr>' for l in (d.get('labs') or []))
        labs_block = (f'<h2>Recent labs</h2><table><thead><tr><th>Test</th><th>Value</th><th>Date</th></tr></thead>'
                      f'<tbody>{labs}</tbody></table>') if labs else ''

        vax = ''.join(f'<tr><td>{e(v.get("name"))}</td><td>{e(v.get("last_date"))}</td></tr>'
                      for v in (d.get('vaccines') or []))
        vax_block = (f'<h2>Vaccines</h2><table><thead><tr><th>Vaccine</th><th>Last dose</th></tr></thead>'
                     f'<tbody>{vax}</tbody></table>') if vax else ''

        contacts = ''.join(f'<div>{e(c.get("name"))} — {e(c.get("phone"))}</div>' for c in (d.get('contacts') or []))
        contacts_block = f'<h2>In an emergency, call</h2><div class="flags">{contacts}</div>' if contacts else ''

        binder_html = ac_block + labs_block + vax_block + contacts_block

    return f'''<div class="sheet">
      <div class="brand">🌱 Arogo — Health snapshot{label}</div>
      <div class="name">{e(d.get("name") or "Someone")}</div>
      <div class="meta">{meta}</div>
      {flags}
      <h2>Current medications</h2>{meds_block}
      <div class="muted small">Adherence: {e(adh_line)}</div>
      <h2>Latest vitals</h2>{vitals_block}
      {binder_html}
      <div class="foot muted">Shared by the person from self-tracked data in Arogo. Read-only, expiring link.
      Not an official medical record. Does not include private journal, cycle, or mood entries.</div>
    </div>'''


# Standalone page — no SPA, no external assets (matches the app's strict CSP).
_PAGE_SHELL = '''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>{title} · Arogo</title>
<style>
  :root {{ --sage:#6B8F71; --ink:#2C3A2E; --muted:#77857A; --line:#E4E9E2; --bg:#F7F8F5; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; padding:24px 14px; }}
  .sheet, .msg {{ max-width:640px; margin:0 auto; background:#fff; border:1px solid var(--line); border-radius:16px; padding:26px 28px; box-shadow:0 4px 18px rgba(0,0,0,.05); }}
  .brand {{ font-size:13px; color:var(--sage); font-weight:700; letter-spacing:.01em; }}
  .name {{ font-size:26px; font-weight:700; margin-top:8px; }}
  .meta {{ color:var(--muted); font-size:13px; margin-top:2px; }}
  .flags {{ margin-top:12px; font-size:14px; }} .flags div {{ margin:2px 0; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:22px 0 8px; border-top:1px solid var(--line); padding-top:14px; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.03em; color:var(--muted); padding:4px 8px 4px 0; }}
  td {{ padding:5px 8px 5px 0; border-top:1px solid var(--line); }}
  .muted {{ color:var(--muted); }} .small {{ font-size:12px; margin-top:6px; }}
  .foot {{ font-size:11.5px; margin-top:20px; border-top:1px solid var(--line); padding-top:12px; }}
  .msg h1 {{ font-size:20px; }} .msg {{ text-align:center; }}
</style></head><body>{body}</body></html>'''
