# Arogo Mobile App — Decision Document (Phase D)

_Status: pre-work complete; app build starts after the website is live
and the PWA has real usage data._

## What's already done (backend is app-ready)

- **Auth:** `POST /api/v1/auth/token` `{email, password}` →
  `{token, token_type: "Bearer", expires_in}`. Send as
  `Authorization: Bearer <token>` on every call. Tokens live 7 days and
  are revoked on password change (`token_version`).
- **Versioned surface:** all 148 routes under `/api/v1/*`
  (see `docs/API.md`, regenerate with `python scripts/gen_api_docs.py`).
- **Errors:** always JSON `{"error": "..."}` with a proper status code.
- **Validated on PostgreSQL** (the production database).

## Stack recommendation: React Native + Expo

| Criterion | Why Expo wins here |
|---|---|
| API reuse | Pure REST client — zero logic rebuilt |
| Solo-dev speed | EAS builds, OTA updates, no Xcode/Gradle wrangling |
| Notifications | expo-notifications handles both platforms |
| Health APIs | expo modules / dev clients for HealthKit + Health Connect |
| Hiring signal | JS skills carry over from the vanilla-JS web app |

Flutter is the fallback if RN performance disappoints — but at this
app's complexity (forms + lists + one chart lib) it won't.

## MVP scope — deliberately tiny (4 screens)

1. **Today** — health score ring, due doses with one-tap "taken",
   water progress + quick add, habit check-offs.
   (`/api/v1/health-score`, `/api/v1/medicines/today`,
   `/api/v1/hydration/<date>`, `/api/v1/habits`)
2. **Log** — the quick-log sheet as a native screen: water / mood /
   weight / repeat-yesterday. (`/api/v1/hydration`, `/api/v1/thoughts`,
   `/api/v1/body-metrics`, `/api/v1/food/recent-meals` + `/food/log`)
3. **Meds** — list, dose timeline, local notifications scheduled from
   `times[]` (works offline; server push is the backstop).
4. **Family** — group view + consent toggles + member summaries.
   (`/api/v1/family*`)

Everything else (reports, fitness, progress charts, export) stays
web-only until usage data argues otherwise.

## Explicitly out of MVP

Barcode scanning, HealthKit/Google Fit sync, widgets, offline queue of
writes, tablet layouts. Each earns its way in via the roadmap.

## Build sequence (when it starts)

1. `npx create-expo-app medeasy-mobile` (separate repo)
2. Auth screen → token storage in SecureStore → API client wrapper
3. Today screen end-to-end (proves the whole stack)
4. Remaining 3 screens
5. Local dose notifications
6. EAS internal build → TestFlight/Play internal testing with the
   same 5–10 family users

## What the PWA teaches us first

The installed PWA is the scout: which quick-log actions get used,
whether push reminders convert to taken doses, whether Family view is
opened on phones. That data decides the MVP's screen priorities before
a single native line is written.
