# Arogo — Engineering Case Study

How a feature-complete but unaudited health app became a hardened,
product-focused one: a full QA audit, a systemic bug-class fix, and a
deliberate refocus around a single core loop.

> Stack: Flask + vanilla JS (no framework) + SQLite/PostgreSQL · ~15k lines
> Python, ~10.6k lines JS · 460 automated tests · strict CSP · installable PWA.

---

## The starting point

Arogo had breadth: thirteen tracking surfaces (medications, food, fitness,
labs, vitals, sleep, habits, journal, tasks, body metrics, family sharing,
progress, notifications), multi-user auth, a PWA shell, and Web Push. What it
hadn't had was an adversarial pass — the kind that asks *"what does a hostile
or careless user do to this, and does the product actually make sense?"*

Two questions drove the work:

1. **Is it correct?** Stress-test every input boundary; fix the bugs.
2. **Does it make sense for the user?** Audit each screen as a product designer
   would, and sharpen the app around what it's actually for.

---

## Part 1 — The audit: one systemic bug class

Six domains were audited in parallel (medicines, medical records, food,
fitness/insights, wellness, family/auth). The same defect surfaced in every
one: **request JSON was fed straight into `int()` / `float()` / `dict['key']`.**

A single malformed value — non-numeric, negative, `NaN`, `Infinity`, missing,
or the wrong type — didn't just 500 the request. In several cases it **wrote
poison that permanently bricked a view**:

- A string `amount_ml` made the hydration day-total `sum()` throw on *every
  future load of that day* — the user couldn't see or fix their own data.
- A medicine's `times` submitted as the scalar `"08:00"` was iterated
  character-by-character into **five phantom doses** (`0`, `8`, `:`, `0`, `0`).
- `Infinity` calories serialized fine, then `OverflowError`-ed the food day.
- A new user's dashboard 500'd for *everyone* because `int(target_calories)`
  hit a present-but-`None` value before the profile was complete.

### The fix: one boundary layer, applied everywhere

Rather than patch 40 call sites ad hoc, the fix is a small shared layer in
`db/core.py`:

```python
to_num(v, default, lo, hi)   # finite-coerce + clamp; NaN/Inf/junk → default
to_int(v, default, lo, hi)
valid_date(v)                # real ISO date, or reject
```

with a consistent philosophy:

- **Malformed numbers → coerce and clamp.** Never 500.
- **Missing required identifiers → a clean 400,** raised in the DB layer and
  mapped by the route (`name`, vital `type`, …).
- **No-op mutations → an honest 404,** not `{success: true}`. Toggling,
  deleting, or logging against an id you don't own now tells the truth so the
  client can resync — a trust property that matters in a health app.
- **Physically-impossible readings → rejected with a friendly message.** A
  9,000,000 bpm heart rate is a typo; 160/100 blood pressure and a 101.5 °F
  fever are real and still log. The bounds are deliberately wide — plausibility,
  not clinical judgment.

~40 bugs fixed, **90+ new test cases** added. The audit test suites were
written to pin the *buggy* behavior first (so they were green pre-fix), then
each assertion was flipped to lock in the correct behavior — no lingering
`xfail`s.

---

## Part 2 — The product refocus

The correctness work exposed a product truth: thirteen co-equal trackers read
as a *quantified-self junk drawer*, not a tool with a reason to open it daily.
The strongest, most differentiated surface was **medication adherence** — so
the app was refocused around that one loop, end to end:

| Change | Before | After |
|---|---|---|
| **Dashboard hero** | a grid of tiles | a single "what do I do right now" — *Take your 8am dose* → advances → *All caught up* |
| **Focal stats** | calories/hydration/sleep/… (no meds) | medication leads: *1/2 doses today* with a progress bar |
| **Sidebar** | flat list of 13 | a **Care** group (Medicines primary) → Track → More |
| **Onboarding** | generic checklist | leads with *Add your first medication* |
| **Caregiving** | background push alerts only | a **"People you're caring for"** panel — *Mom: 1 dose overdue*, consent-gated per member |
| **Daily check-in** | auto-modal covering the hero | a dismissible card; doubles as the journal (a note in the mood step becomes the day's entry) |

Two other product bugs — *misleading numbers*, which a health app can't afford:

- New medicines were scored **3.3% adherence** on day one, and courses that
  ended in 2020 still demanded doses today, because start/end dates were stored
  but never checked. Both now respect the course window.
- A brand-new user's Progress screen read **"Needs focus · Tough week"** in
  red — judging an empty week. It now welcomes: *"Start logging to see your
  progress."*

- **Pill stock finally tracks reality.** `decrement_pill_count()` existed but
  nothing called it, so "days left" drifted up forever. Taking a dose now
  consumes stock (and un-taking restores it), guarded on the state transition
  so a double-tap never double-counts.

### A tradeoff worth naming

One proposed step was to *collapse* the Journal / Body / Tasks screens into the
daily check-in "to lean out the nav." I didn't — those are **management**
surfaces (BMI charts, vitals history, task CRUD) that a 30-second modal can't
replace without deleting capability. The right consolidation was the
non-destructive one: quick daily capture lives in the check-in; the full
screens stay (demoted to *More*) for management. Knowing what *not* to build is
part of the job.

---

## How the work was verified

- **460 automated tests** (Python API/isolation/family/auth + 14 JS unit
  tests), gated by a pre-commit hook and CI on every push.
- **`tests/test_conventions.py`** enforces project decisions *statically* — no
  inline event handlers (strict CSP), portable SQL only, no Linux-only
  `strftime` — so regressions fail loudly.
- **Every user-visible change was driven in a real browser** — the meds hero
  through all three states, the caregiver panel's red/amber/green rows, the
  vitals rejection message, the unified check-in writing to the journal — not
  asserted from the code alone.

---

## What this demonstrates

- Finding a **systemic** defect and fixing it *as a class*, not case by case.
- Treating **honesty and trust** (no silent no-ops, no misleading numbers, no
  demoralizing empty states) as correctness, not polish.
- Moving from "a pile of features" to **a product with a point of view**,
  reversibly and with the existing design system.
- Rigor: tests that pin behavior, static convention guards, and live
  verification of every claim.

See [`README.md`](README.md) for setup and architecture, and the git history
for the commit-by-commit story.
