# MediScan Health OS

A personal health portal built with Flask + vanilla JS + SQLite.

---

## Project Structure

```
mediscan/
├── app.py                   # Flask application factory (50 lines)
├── config.py                # All configuration in one place
├── database.py              # Legacy monolith — kept for backward compatibility
│
├── db/                      # Database layer — split by domain
│   ├── __init__.py          # Re-exports everything; the only import you need
│   ├── core.py              # SQLite connection, schema, execute(), helpers
│   ├── reports.py           # Medical reports CRUD
│   ├── medicines.py         # Medicines, doses, stock/refill tracking
│   ├── fitness.py           # Activities, OAuth tokens, sync log
│   ├── food.py              # Food logs, nutrition, profile, TDEE
│   ├── wellness.py          # Thoughts, todos, hydration, sleep, body metrics
│   ├── health.py            # Habits, symptoms, vitals, emergency info
│   └── insights.py          # Notifications, weekly report, search, progress
│
├── routes/                  # Flask Blueprints — split by domain
│   ├── __init__.py          # Blueprint registry documentation
│   ├── reports.py           # /api/reports, /api/upload, /api/stats
│   ├── medicines.py         # /api/medicines, /api/medicines/*/stock
│   ├── fitness.py           # /api/fitness/*, /api/fitness/calendar
│   ├── oauth.py             # /oauth/strava, /oauth/garmin, /oauth/google
│   ├── food.py              # /api/food/*
│   ├── wellness.py          # /api/thoughts, /api/todos, /api/hydration,
│   │                        # /api/sleep, /api/body-metrics, /api/habits,
│   │                        # /api/symptoms, /api/vitals, /api/emergency
│   └── insights.py          # /api/report, /api/progress, /api/search,
│                            # /api/export, /api/notifications
│
├── static/
│   ├── js/
│   │   ├── app.js           # Deployed bundle (5 400 lines) — served to browser
│   │   └── modules/         # Split source — edit these, then concat to app.js
│   │       ├── 01-core.js          # State, init, navigation, modals
│   │       ├── 02-dashboard.js     # Hero cards, wellness strip, calorie breakdown
│   │       ├── 03-reports.js       # Medical reports UI
│   │       ├── 04-medicines.js     # Medicine tracker, dose timeline, stock
│   │       ├── 05-fitness.js       # Fitness page, activity form, gym fields
│   │       ├── 06-consistency.js   # Calendar, streaks, habits
│   │       ├── 07-food.js          # Food tracker, macro rings, dropdown
│   │       ├── 08-wellness.js      # Thoughts, sleep, body, symptoms, vitals, hydration
│   │       ├── 09-search.js        # Global search overlay, date parsing
│   │       ├── 10-notifications.js # Notification centre, daily nudges
│   │       ├── 11-progress-report.js # Progress charts, health report PDF
│   │       └── 12-export.js        # Data export, restock modal, nudge scheduler
│   │
│   └── css/
│       ├── style.css         # Deployed bundle (3 170 lines) — served to browser
│       ├── main.css          # @import manifest — use this to rebuild bundle
│       └── modules/
│           ├── 01-base.css         # Variables, reset, typography, layout, buttons
│           ├── 02-dashboard.css    # Dashboard cards, quick-log bar
│           ├── 03-medical.css      # Reports grid, dropzone, medicine tracker
│           ├── 04-fitness.css      # Fitness page, calendar, activity history
│           ├── 05-food.css         # Food tracker, hydration bottle
│           ├── 06-wellness.css     # Journal, sleep, body, mood, habits
│           ├── 07-medical2.css     # Symptoms, vitals, emergency card
│           └── 08-features.css     # Progress, report, notifications, search, export
│
├── templates/
│   └── index.html            # Single-page app shell (2 500 lines)
│
├── food_data.py              # 400+ item food database with nutrition data
├── fitness_sync.py           # Strava / Garmin / Google Fit sync helpers
├── scheduler.py              # Background job scheduler (medicine reminders)
├── mediscan.db               # SQLite database (created on first run)
└── uploads/                  # Uploaded medical report files
```

---

## Quick Start

```bash
# Install dependencies
pip install flask

# Run (creates DB automatically)
python app.py
# → http://localhost:5000
```

---

## Development Workflow

### Adding a new API endpoint
1. Decide which **domain** it belongs to (food, fitness, wellness, etc.)
2. Add the DB function to `db/<domain>.py`
3. Re-export it from `db/__init__.py`
4. Add the Flask route to `routes/<domain>.py` using `@bp.route`
5. No changes needed to `app.py`

### Adding new frontend JS
1. Edit the relevant `static/js/modules/XX-<name>.js`
2. Rebuild the bundle: `cat static/js/modules/*.js > static/js/app.js`
3. The `<script src="/static/js/app.js">` in `index.html` picks it up

### Adding new CSS
1. Edit the relevant `static/css/modules/XX-<name>.css`
2. Rebuild the bundle: `cat static/css/modules/*.css > static/css/style.css`

### Rebuild scripts
```bash
# Rebuild JS bundle
cat static/js/modules/*.js > static/js/app.js

# Rebuild CSS bundle
cat static/css/modules/*.css > static/css/style.css
```

---

## Database Schema

| Table               | Domain        | Purpose |
|---------------------|---------------|---------|
| reports             | Medical       | Uploaded health reports |
| medicines           | Medical       | Medicine list with stock tracking |
| dose_logs           | Medical       | Per-dose taken/missed log |
| fitness_activities  | Fitness       | Workouts, runs, gym sessions |
| oauth_tokens        | Fitness       | Strava/Garmin/Google tokens |
| sync_log            | Fitness       | Sync history per service |
| user_profile        | Profile       | Name, weight, height, goal |
| food_logs           | Nutrition     | Every logged meal |
| custom_foods        | Nutrition     | User-created food items |
| thoughts            | Wellness      | Daily journal entries |
| todos               | Wellness      | Tasks with reminders |
| hydration_logs      | Wellness      | Water intake per day |
| sleep_logs          | Wellness      | Sleep duration & quality |
| body_metrics        | Wellness      | Weight, BMI, body fat |
| habits              | Habits        | Habit definitions |
| habit_logs          | Habits        | Daily completion records |
| symptoms            | Medical       | Logged symptoms with severity |
| vitals              | Medical       | BP, blood sugar, heart rate |
| emergency_info      | Medical       | Blood type, contacts, insurance |
| notification_log    | System        | All app notifications |
