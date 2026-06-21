# UCI Calendar — Architecture & Operations Guide

## Overview

A Progressive Web App (PWA) showing live UCI men's road race results, upcoming races, team rosters, rider profiles, statistics, and a fantasy league. Data is scraped from **cyclingflash.com** (race results/startlists) and **procyclingstats.com** (rider profiles, specialty scores, career wins), stored in `data.json` and `rider_profiles.json`, and served via **GitHub Pages** at `https://psykalist.github.io/UCI-Calendar/`.

---

## Data Flow

```
cyclingflash.com ──► scraper.py ──────────────────► data.json ──► GitHub Pages ──► index.html (PWA)
                                                         │
procyclingstats.com ─► scrape_rider_profiles.py ──► rider_profiles.json ──────────────────────────►┘
procyclingstats.com ─► scrape_pcs_stats.py ──────► pcs_stats.json ───────────────────────────────►┘
```

---

## Scripts

### `scraper.py` — core data scraper

Four modes. Only `--results-only` runs automatically (CI). All others run locally.

**`py scraper.py --results-only`** (CI + daily scheduled task)
Fetches new stage results and classifications for live races only. Auto-promotes upcoming → live and live → recent by date. Refreshes career wins for today's stage winners (~1–3 PCS requests). Does NOT re-scrape teams, calendar, or startlists.

**`py scraper.py --teams-only`** (manual, local)
Refreshes WorldTeam + ProTeam rosters from cyclingflash.com. Run mid-season after transfers. Does NOT embed wins in teams data (those stay in `rider_profiles.json`). Output: updates `data.json` teams section only.

**`py scraper.py --startlists-only`** (daily scheduled task, local)
Fetches PCS startlists for upcoming/live races that don't have one yet. PCS blocks CI IPs so this must run locally. Startlists are published 2–7 days before race start.

**`py scraper.py`** (full scrape — manual, local, start of season only)
Full calendar discovery, team scrape, rider profile backfill (up to 50 new riders), startlists. Run at season start or when the race calendar changes significantly.

**Women's race guard:** the scraper filters out women's races by UCI category (`1.WWT`, `2.WWT`, etc.) and by name keywords. The CI workflow has an additional post-scrape strip step as a belt-and-braces check.

**Key behaviour:**
- All writes use atomic tmp-file replace to prevent corruption
- Post-write validation checks file size and JSON validity; restores backup on failure
- Uses `git pull --rebase` + retry on push rejection (for `--update-winners` mode)

---

### `scrape_rider_profiles.py` — rider profiles from PCS

Builds and maintains `rider_profiles.json` (~4–5 MB, ~1800 riders) with photo, DOB, nationality, height/weight, specialty scores, and full career wins.

**Modes:**
- Default: fetches profiles for new riders only (not yet in JSON)
- `--fix-empty`: re-fetches riders with 0 wins (may have been blocked first time)
- `--all`: re-fetches every rider
- `--update-winners`: fetches only today's stage winners + GC leaders; auto git commit + push

**`--update-winners`** runs via Cowork scheduled task at 8pm daily. Used to keep winner palmares current after race days.

**Data sources:**
- Main rider page (`/rider/{slug}`): photo, bio block (DOB, height, weight, nationality, specialty scores)
- Wins page (`/rider/{slug}/statistics/wins`): full career palmares table

**Output format (`rider_profiles.json`):**
```json
{
  "scraped_at": "...",
  "count": 1800,
  "riders": {
    "tadej-pogacar": {
      "name": "Tadej Pogačar",
      "nat": "si", "nat_name": "Slovenia",
      "photo": "https://...",
      "dob": "1998-09-21",
      "height": 1.76, "weight": 65,
      "specialties": { "gc": 95, "oneday": 89, "climber": 92, "sprint": 61, "tt": 78, "hills": 80 },
      "wins": [{ "year": "2024", "date": "2024-07-21", "race": "Tour de France - Stage 21", "cat": "2.UWT" }]
    }
  }
}
```

---

### `scrape_pcs_stats.py` — PCS statistics tables

Scrapes all statistics pages from procyclingstats.com (most wins, best climbers, sprinters, etc.) and saves to `pcs_stats.json`. Powers the **Stats tab** in the app.

**Usage:** `py scrape_pcs_stats.py` (manual, run monthly or when stats need refreshing)

---

### `detect_changes.py`

Diffs old vs new `data.json` and writes notable changes to `changelog.json` (stage wins, GC leader changes). Entries older than 14 days are pruned. Called by CI after every scraper run.

---

### `heal.py` — local watchdog

Run every 5 minutes via Windows Task Scheduler.

**Checks and repairs:**

| Check | Auto-repair |
|-------|-------------|
| `.git/index.lock` / `HEAD.lock` present | Delete them |
| `data.json` too small or invalid JSON | `git checkout HEAD -- data.json` |
| Local branch behind origin/main | Warn only |

**Usage:**
```
py heal.py          # check + repair
py heal.py --push   # also commit + push status.json
```

---

## Scheduled Tasks (Cowork)

Three tasks run automatically while the Cowork app is open:

| Time | Task | What it does |
|------|------|--------------|
| 9am daily | `uci-startlists-daily` | `py scraper.py --startlists-only` — fetches new startlists from PCS |
| 8am / 2pm / 8pm daily | `uci-calendar-daily-update` | `py scraper.py --results-only` — fetches stage results |
| 8pm daily | `uci-winner-profiles` | `py scrape_rider_profiles.py --update-winners` — refreshes winner profiles |

---

## GitHub Actions Workflows

### `scrape.yml` (primary — runs in cloud)
Runs `--results-only` scrape + `detect_changes.py` and commits `data.json` + `changelog.json`.

**Schedule:** 11am UTC and 5pm UTC daily (12pm and 6pm BST).

**Also installs:** `pywebpush` for push notification delivery.

**Post-scrape:** strips any women's races that slipped through.

**Trigger manually:** GitHub → Actions → "Update UCI Race Data" → Run workflow.

### `health-check.yml` (watchdog)
Triggered by `heal.py --push` or on a 6-hour schedule. Re-runs the scraper if data is stale or corrupt. Restores `data.json` from git history if invalid.

---

## Key Files

| File | Purpose |
|------|---------|
| `data.json` | Race calendar, results, classifications, teams, startlists (~1.7 MB) |
| `rider_profiles.json` | All rider profiles — photo, bio, specialty scores, career wins (~4–5 MB) |
| `pcs_stats.json` | PCS statistics tables powering the Stats tab |
| `changelog.json` | Recent notable changes shown in the app |
| `index.html` | Entire PWA — HTML + CSS + JS in one file (service worker v28) |
| `sw.js` | Service worker — network-first for data files, cache-first for static assets |
| `manifest.json` | PWA manifest — icons, theme colour, install behaviour |
| `push_subscriptions.json` | Browser push subscription endpoints (not in git if not committed) |

---

## App Tabs

| Tab | Data source | Notes |
|-----|-------------|-------|
| Live / Upcoming / Recent | `data.json` | Auto-refreshes every 30 min |
| Teams | `data.json` teams section | Rider rows open modal from `rider_profiles.json` |
| Stats | `pcs_stats.json` | Category filter + accordion rows |
| Fantasy | Local state | No backend |

**Rider modal:** lazy-loads `rider_profiles.json` on first open, cached in memory. Shows photo, bio, specialty bars, and career wins for any of the ~1800 profiled riders. Triggered from race results, team rosters, and stats tables — no external links.

---

## Push Notifications

Uses the Web Push API with VAPID authentication.

- **VAPID keys:** private key in `scraper.py`, public key in `index.html` — must be a matched pair. Do not regenerate without also clearing all existing browser subscriptions.
- **Subscription flow:** user clicks 🔔 in app → browser subscribes → saves `push_subscriptions.json` locally → user copies to project folder → commit to repo for CI delivery.
- **Triggers:** new stage result, race starting tomorrow.
- **Requires:** `pip install pywebpush` locally. CI installs it automatically.
- **Note:** Chrome routes subscriptions through FCM (`fcm.googleapis.com`). Corporate/restricted networks may block this.

---

## Git Workflow (local + CI conflict avoidance)

CI commits `data.json` at 11am and 5pm UTC. To avoid conflicts on manual pushes:

```bash
# Always pull before committing
git stash && git pull --rebase && git stash pop
py scraper.py --results-only
git add data.json && git commit -m "results: ..." && git push

# If push is still rejected
git pull --rebase && git push
```

---

## Race Filtering

**Men's only:** women's races filtered by UCI category (`1.WWT`, `2.WWT`, `1.W`, `2.W`, `1.1W`, `2.1W`) and by name keywords (women, ladies, femmes, dames). Applied in scraper + CI post-scrape.

**Filter chips in app:** All / Grand Tours / Monuments / UWT ⭐ / Pro Series / 1.1 / 2.1 / This Week.

- Grand Tours: `total_stages >= 21`
- Monuments: Milano-Sanremo, Ronde van Vlaanderen, Paris-Roubaix, Liège-Bastogne-Liège, Il Lombardia

---

## Self-Healing Runbook

### data.json is corrupt
```bash
git checkout HEAD -- data.json
```

### Teams out of date (mid-season transfer)
```bash
py scraper.py --teams-only
git add data.json && git commit -m "data: refresh teams" && git push
```

### Rider missing from search
Rider search reads `rider_profiles.json` directly (~1800 riders). If a rider is missing, run:
```bash
py scrape_rider_profiles.py        # picks up any new riders
git add rider_profiles.json && git commit -m "data: rider profiles" && git push
```

### Startlist missing for upcoming race
```bash
py scraper.py --startlists-only
git add data.json && git commit -m "data: startlists" && git push
```

### App shows stale data
1. Hard-refresh: Ctrl+Shift+R
2. Check GitHub Actions — scraper may have failed
3. Trigger manually: GitHub → Actions → Run workflow

### Push notifications not working
- Check `push_subscriptions.json` exists in project folder and is committed
- Check `pywebpush` is installed: `pip install pywebpush`
- Corporate networks may block FCM — test on mobile data
