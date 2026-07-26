# Security Policy

Arogo stores personal health data. We take reports seriously and want to fix
issues quickly and transparently.

## Reporting a vulnerability

Please email **security@arogo.app** (update this to your real inbox before
launch) with:

- a description of the issue and where it is,
- steps to reproduce (a proof-of-concept if you have one),
- the impact you think it has.

We aim to acknowledge within **72 hours** and to keep you updated as we work on
a fix. Please give us a reasonable window to remediate before any public
disclosure.

### Safe harbour

We will not pursue or support legal action against researchers who:

- act in good faith and avoid privacy violations, data destruction, and service
  degradation,
- test only against their **own** account and data,
- do not access, modify, or retain other users' data, and
- give us reasonable time to fix the issue before disclosing it.

### Out of scope

Reports that are theoretical with no demonstrated impact, findings from
automated scanners without a working exploit, social-engineering of staff or
users, and denial-of-service testing.

---

## Data-breach response procedure

Arogo handles individually identifiable health information, so the **FTC Health
Breach Notification Rule** applies even though Arogo is not a HIPAA-covered
entity. India's DPDP also requires prompt breach notification. This is the
procedure we follow if a breach is suspected — written down **before** we need
it so an incident does not become a scramble.

1. **Detect & triage** — Whoever notices logs the time, what was seen, and how.
   The on-call owner is paged and becomes incident lead.
2. **Contain** — Stop the bleeding: rotate leaked credentials/keys
   (`SECRET_KEY`, SMTP, Twilio, VAPID, OAuth secrets), revoke sessions
   (`bump_token_version`), disable the affected path, and preserve logs for
   investigation. Do not destroy evidence.
3. **Assess** — Determine what data was exposed, for how many users, and
   whether it was actually accessed (not just exposed). Record the findings.
4. **Notify** — If personal health data was, or is reasonably believed to have
   been, acquired without authorisation:
   - Notify **affected individuals without unreasonable delay and no later than
     60 calendar days** after discovery (FTC Health Breach Notification Rule),
     in plain language: what happened, what data, what we're doing, what they
     can do.
   - Notify the **FTC** (and, for ≥500 people, do so within 60 days); notify
     **media** if a breach affects ≥500 residents of a state/jurisdiction.
   - For Indian users, notify the **Data Protection Board** per DPDP timelines.
5. **Remediate** — Fix the root cause, add a regression test, and verify.
6. **Post-mortem** — Within two weeks, write a blameless post-mortem: timeline,
   root cause, what worked, what to change. Update this procedure.

### Notification contacts to fill in before launch

- Incident lead / on-call: _______________________
- FTC Health Breach Notification portal: reportbreach.ftc.gov
- India Data Protection Board: _______________________
- Legal / DPO (if any): _______________________

---

## Hardening checklist (must be true in production)

- [ ] `SECRET_KEY` set to a real random value (app refuses to start otherwise).
- [ ] `COOKIE_SECURE` — on by default when `FLASK_DEBUG=0`; keep it on.
- [ ] `FLASK_DEBUG=0`.
- [ ] HTTPS everywhere (HSTS at the proxy).
- [ ] Provider secrets set via env, never committed (`.db`, `.env` are
      git-ignored).
- [ ] Database backups tested for restore.
- [ ] `security.txt` contact points at a monitored inbox.
