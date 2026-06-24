# UCI Road Calendar — Full Documentation

> **Single source of truth.** Replaces README.md, ARCHITECTURE.md, SCRAPE_PROFILES.md, KNOWN_GAPS.md, and CHANGELOG.md.  
> Last updated: 2026-06-24

---

## Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Architecture & Data Flow](#architecture--data-flow)
4. [Scripts Reference](#scripts-reference)
5. [Scheduled Tasks](#scheduled-tasks)
6. [GitHub Actions](#github-actions)
7. [App Tabs & Features](#app-tabs--features)
8. [Push Notifications](#push-notifications)
9. [Fantasy League](#fantasy-league)
10. [Deployment](#deployment)
11. [Git Workflow](#git-workflow)
12. [Race Filtering](#race-filtering)
13. [Scraping Profiles (HTML Structure)](#scraping-profiles-html-structure)
14. [Known Gaps & Limitations](#known-gaps--limitations)
15. [Self-Healing Runbook](#self-healing-runbook)
16. [Changelog](#changelog)

---

## Overview

A Progressive Web App (PWA) showing live UCI men's road race results, upcoming races, team rosters, rider profiles, statistics, and a fantasy league. Data is scraped from **cyclingflash.com** (race calendar/results/startlists) and **procyclingstats.com** (rider profiles, specialty scores, career wins). All data is stored in flat JSON files committed to GitHub and served via **GitHub Pages** — no backend required.

**Live app:** https://psykalist.github.io/UCI-Calendar/

---

## Quick Start

```bash
# 1. Install Python dependencies (one-time)
pip install requests beautifulsoup4

# 2. Run the scraper to fetch latest results
py scraper.py --results-only

# 3. Rebuild the SQLite database and data.js
py import_to_db.py

# 4. Commit and push to deploy
git add data.json data.js cycling.db
git commit -m "data: update $(date -u +%Y-%m-%d)"
git push
```

---

## Architecture & Data Flow

```
cyclingflash.com ──► scraper.py ─────────────────────────► data.json ──► GitHub Pages ──► index.html (PWA)
                                                                │
procyclingstats.com ─► scrape_rider_profiles.py ──► rider_profiles.json ──────────────────────────────►┘
procyclingstats.com ─► scrape_pcs_stats.py ──────► pcs_stats.json ─────────────────────────────────────►┘

data.json + rider_profiles.json ──► import_to_db.py ──► cycling.db (SQLite) + data.js
```

### Key files

| File | Size | Purpose |
|------|------|---------|
| `data.json` | ~1.7 MB | Race calendar, results, classifications, teams, startlists |
| `rider_profiles.json` | ~4–5 MB | Rider photos, bios, specialty scores, career wins (~1800 riders) |
| `pcs_stats.json` | — | PCS statistics tables powering the Stats tab |
| `cycling.db` | ~3–5 MB | SQLite database — all data in queryable form |
| `data.js` | ~2 MB | `window.UCI_DATA = ...` export built from the DB, loaded by index.html |
| `changelog.json` | — | Recent stage wins / GC changes shown in-app |
| `index.html` | — | Entire PWA — HTML + CSS + JS in one file |
| `sw.js` | — | Service worker — network-first for data, cache-first for static assets |
| `manifest.json` | — | PWA manifest — icons, theme colour, install behaviour |

### data.json structure

All races are stored in a single `races` array with a `status` field (`"upcoming"`, `"live"`, or `"recent"`). **Do not** read top-level `live`/`upcoming`/`recent` keys — they don't exist. Stage winners are in `stage.results[0].slug` (not `stage.top10`).

```json
{
  "exportedAt": "...",
  "races": [
    {
      "name": "Tour de France",
      "status": "live",
      "stages": [
        {
          "num": 1,
          "winner": "Tadej Pogačar",
          "results": [
            { "rank": 1, "slug": "tadej-pogacar", "name": "Tadej Pogačar", ... }
          ]
        }
      ]
    }
  ]
}
```

---

## Scripts Reference

### `scraper.py` — core data scraper

Four modes. Only `--results-only` runs automatically in CI. All others must run locally.

**`py scraper.py --results-only`** *(CI + daily scheduled task)*  
Fetches new stage results and classifications for live/recent races only. Auto-promotes upcoming → live → recent by date. Refreshes career wins for today's stage winners. Does NOT re-scrape teams, calendar, or startlists.

**`py scraper.py --teams-only`** *(manual, local)*  
Refreshes WorldTeam + ProTeam rosters from cyclingflash.com. Run mid-season after transfers.

**`py scraper.py --startlists-only`** *(daily scheduled task, local)*  
Fetches PCS startlists for upcoming/live races that don't have one yet. PCS blocks CI IPs so this must run locally. Startlists are published 2–7 days before race start.

**`py scraper.py`** *(full scrape — manual, local, start of season only)*  
Full calendar discovery, team scrape, rider profile backfill (up to 50 new riders), startlists. Run at season start or when the race calendar changes significantly.

**Key behaviour:**
- All writes use atomic tmp-file replace to prevent corruption (critical on Windows SMB mounts)
- Post-write validation checks file size and JSON validity; restores backup on failure
- Women's races are filtered by UCI category (`1.WWT`, `2.WWT`, etc.) and name keywords

---

### `import_to_db.py` — build SQLite database

Reads `data.json` and `rider_profiles.json`, writes `cycling.db` and `data.js`.

```bash
py import_to_db.py
```

Run after every `scraper.py` run. Builds in `/tmp` first (avoids Windows SMB I/O limits), then copies to `cycling.db`. The DB is append-safe — INSERT OR REPLACE throughout, never deletes rows.

**Tables:** `races`, `stages`, `stage_results`, `race_results`, `classifications`, `riders`, `rider_wins`, `teams`, `team_riders`

**Note:** `cycling.db` was empty as of 2026-06-24 due to an interrupted write. Re-run `import_to_db.py` to rebuild it.

---

### `scrape_rider_profiles.py` — rider profiles from PCS

Builds and maintains `rider_profiles.json` (~1800 riders) with photo, DOB, nationality, height/weight, specialty scores, and full career wins.

```bash
py scrape_rider_profiles.py              # fetch only new riders
py scrape_rider_profiles.py --fix-empty  # re-fetch riders with 0 wins
py scrape_rider_profiles.py --all        # re-fetch everything
py scrape_rider_profiles.py --update-winners  # only today's winners + GC leaders; auto-commits
```

`--update-winners` runs via Cowork scheduled task at 8pm daily. Must run locally (PCS blocks CI IPs).

**Output format (`rider_profiles.json`):**
```json
{
  "riders": {
    "tadej-pogacar": {
      "name": "Tadej Pogačar",
      "nat": "SI", "nat_name": "Slovenia",
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

```bash
py scrape_pcs_stats.py    # manual, run monthly or when stats need refreshing
```

---

### `detect_changes.py`

Diffs old vs new `data.json` and writes notable changes to `changelog.json` (stage wins, GC leader changes). Entries older than 14 days are pruned. Called by CI after every scraper run.

---

### `heal.py` — local watchdog

Run every 5 minutes via Windows Task Scheduler.

| Check | Auto-repair |
|-------|-------------|
| `.git/index.lock` / `HEAD.lock` present | Delete them |
| `data.json` too small or invalid JSON | `git checkout HEAD -- data.json` |
| Local branch behind origin/main | Warn only |

```bash
py heal.py          # check + repair
py heal.py --push   # also commit + push status.json
```

---

### `check_and_fix.py` — data integrity checker

Validates `data.json` for common issues and auto-fixes what it can.

### `pre_push_check.py` — pre-push validator

Validates JSON structure, checks required fields, warns about anomalies. Run before manual pushes.

### `push.bat` / `git-push.sh` / `update.bat` — deploy helpers

Convenience scripts that run the scraper, commit `data.json`, and push to GitHub.

---

## Scheduled Tasks

Three tasks run automatically while the Cowork app is open:

| Time | Task | Command |
|------|------|---------|
| 9am daily | `uci-startlists-daily` | `py scraper.py --startlists-only` |
| 8am / 2pm / 8pm daily | `uci-calendar-daily-update` | `py scraper.py --results-only` |
| 8pm daily | `uci-winner-profiles` | `py scrape_rider_profiles.py --update-winners` |

---

## GitHub Actions

### `scrape.yml` (primary)
Runs `--results-only` + `detect_changes.py`, commits `data.json` + `changelog.json`.  
**Schedule:** 11am UTC and 5pm UTC daily (12pm and 6pm BST).

### `health-check.yml` (watchdog)
Triggered by `heal.py --push` or on a 6-hour schedule. Re-runs scraper if data is stale/corrupt.

---

## App Tabs & Features

| Tab | Data source | Notes |
|-----|-------------|-------|
| Live / Upcoming / Recent | `data.json` via `data.js` | Auto-refreshes every 30 min |
| Teams | `data.json` teams section | Rider rows open modal from `rider_profiles.json` |
| Stats | `pcs_stats.json` | Category filter + accordion rows |
| Fantasy | Browser localStorage | No backend |

**Rider modal:** lazy-loads `rider_profiles.json` on first open, cached in memory. Shows photo, bio, specialty bars, and career wins for any of the ~1800 profiled riders.

**Filter chips:** All / Grand Tours / Monuments / UWT ⭐ / Pro Series / 1.1 / 2.1 / This Week.

---

## Push Notifications

Uses the Web Push API with VAPID authentication.

- **VAPID keys:** private key in `scraper.py`, public key in `index.html` — must be a matched pair. Do not regenerate without clearing all browser subscriptions.
- **Subscription flow:** user clicks 🔔 → browser subscribes → saves `push_subscriptions.json` → copy file to project folder → commit to repo for CI delivery.
- **Triggers:** new stage result detected, race starting tomorrow.
- **Requires:** `pip install pywebpush` locally. CI installs automatically.
- **Note:** Chrome routes subscriptions through FCM (`fcm.googleapis.com`). Corporate networks may block this.

---

## Fantasy League

- Pick 9 riders per race before it starts
- Points scored from stage results (1st = 10pts, 2nd = 7pts, etc.)
- Teams are race-keyed — each race has its own independent team
- No mid-race swaps allowed
- Export code to share; import codes to compare teams
- All data stored in browser `localStorage` (device-local, no backend)

---

## Deployment

```bash
git add data.json data.js cycling.db index.html sw.js
git commit -m "feat/fix/chore: description (vXX)"
git push
```

GitHub Pages deploys within ~1 minute. Check status at:  
`https://github.com/psykalist/UCI-Calendar/actions`

**Version tagging:**
```bash
git tag v26
git push origin v26
```

---

## Git Workflow

CI commits `data.json` at 11am and 5pm UTC. To avoid conflicts on manual pushes:

```bash
git stash && git pull --rebase && git stash pop
py scraper.py --results-only
git add data.json && git commit -m "results: ..." && git push

# If push is rejected
git pull --rebase && git push
```

---

## Race Filtering

**Men's only:** filtered by UCI category (`1.WWT`, `2.WWT`, `1.W`, `2.W`, `1.1W`, `2.1W`) and name keywords (women, ladies, femmes, dames). Applied in scraper and CI post-scrape.

**Grand Tours:** `total_stages >= 21`  
**Monuments:** Milano-Sanremo, Ronde van Vlaanderen, Paris-Roubaix, Liège-Bastogne-Liège, Il Lombardia

---

## Scraping Profiles (HTML Structure)

Per-site HTML structure notes. Update whenever a site changes. Test the scraper against these after any site update.

### procyclingstats.com (PCS)

Base URL: `https://www.procyclingstats.com`

#### Startlist page
URL: `/race/{pcs-slug}/{year}/startlist`

**Confirmed working structure (June 2026):**
```html
<div class="ridersCont">
  <div>
    <span class="confirmed ok"></span>
    <a class="team" href="team/uae-team-emirates-xrg-2026">UAE Team Emirates - XRG (WT)</a>
  </div>
  <ul>
    <li class=" ">
      <span class="bib">1</span>
      <span class="flag si"></span>
      <a href="rider/tadej-pogacar">POGAČAR Tadej</a>
    </li>
  </ul>
</div>
```

**Key patterns:**
- Split on `<div[^>]+class="ridersCont"` to get one block per team
- Team name: `class="team"[^>]*>([^<]+)</a>`
- Nat code: `class="flag (\w+)"></span>` (second CSS class = 2-letter ISO code)
- Rider slug + name: `href="rider/([^"]+)">([^<]+)</a>`

**Broken assumptions (do not use):**
- ~~`<ul class="riders">`~~ — ul has no class
- ~~`<b>Team Name</b>`~~ — team is in `<a class="team">`
- ~~`<span>Name</span>` inside rider link~~ — name is a direct text node
- ~~`/svg/flags/XX.svg`~~ — flags are CSS classes, not SVG URLs

#### Race results / stage winner
URL: `/race/{pcs-slug}/{year}/result/stage-{n}` or `/result`

- First `<tr>` in results table = stage winner
- Nat: `<span class="flag XX">` (same pattern as startlist)

#### Rider profile page
URL: `/rider/{rider-slug}`

- Name: `<h1>` or `<title>`
- Info block: `borderbox left w65` div → `<li>` items for DOB, height, weight, nationality
- Specialty scores: e.g. `"9983Onedayraces"`, `"7594GC"` in li text

### cyclingflash.com (CF)

Base URL: `https://cyclingflash.com`

**Used for:** Race calendar, race metadata, stage listings, linking to PCS.

- Race calendar URL: `/races.php?category=1&filter=Filter&p=uci&s=latest-results`
- Stage links: `href="/race/{cf-slug}/result/stage-{n}"`
- **Flag SVGs:** `cyclingflash.com/svg/flags/XX.svg` — **do NOT use in the app** (cross-origin blocked). Use `flagcdn.com/16x12/XX.png` everywhere instead.

### flagcdn.com

**Used for ALL flag rendering in the app.**

URL: `https://flagcdn.com/16x12/{nat_code_lowercase}.png`

- 2-letter ISO 3166-1 alpha-2 codes (same as PCS CSS classes)
- Render via `<img>` — flag emoji does NOT render on Windows
- App helpers: `flagImg(nat)` and `flag(nat)`

### General scraping notes

- **SMB truncation bug:** Writing large files through the Windows SMB mount silently truncates them. Always write to a temp file then `os.replace()`. Use `tempfile.mkstemp()` in the same directory.
- **PCS rate limits:** `time.sleep(DELAY)` between requests. Use `DELAY = 1.0`.
- **HTTP 500 from PCS:** Retry 3x with exponential backoff.
- **Verbose fetch:** All fetches print URL + byte count to stdout — silent failures are immediately visible.
- **`flush=True`:** All `print()` calls must use `flush=True` on Windows to avoid buffering stalling output.
- **data.json structure:** Races are in `data['races']` filtered by `status` — NOT in top-level `live`/`upcoming`/`recent` keys. Stage winners are in `stage['results'][0]['slug']`, not `stage['top10']`.

---

## Known Gaps & Limitations

### Data gaps

**Stage distance & elevation sometimes blank**  
PCS returns HTTP 500 on some stage detail pages intermittently. Reruns pick up cached data once PCS recovers.

**Rider nationality flags missing for some riders**  
Fixed in v15 for race results. Riders only in team rosters (never appeared in results) may still lack flags until their profile is fetched incrementally.

**Rider photos missing for most riders**  
Capped at 50 new profiles per scraper run (~16 full runs to populate all ~800 riders). Placeholder avatar shown in the meantime.

**Team rosters limited in fantasy**  
`scrape_teams.py` must run separately. Without it, fantasy pool is limited to ~250 riders who have appeared in race results. Run `py scraper.py --teams-only` once to fully populate.

**Startlists missing for far-future races**  
PCS doesn't publish startlists until ~2 weeks before a race. Scraper skips races >21 days out by design. Fetches automatically once the race is within range.

**Stage route/profile images missing on some stages**  
Available from CyclingFlash's CDN only once they publish them (~days before each stage). Picked up automatically on the next scraper run.

### Structural limitations (require a backend to fix)

**Fantasy teams are device-local only** — stored in `localStorage`. Use Export Code to back up.

**No real-time leaderboard sync** — each user's fantasy team lives on their own device. Share via Export Codes.

**No live race tracking / GPS** — live position data requires a paid provider (Velon, ASO). "Live" races show results only after a stage finishes and CyclingFlash publishes.

**PCS rate limiting** — occasional 403/500 errors expected. Just re-run; cached data is never overwritten by a failed fetch.

**cycling.db may fall behind** — the SQLite database must be rebuilt manually with `py import_to_db.py` after each scraper run. It is not updated by CI.

---

## Self-Healing Runbook

**data.json is corrupt:**
```bash
git checkout HEAD -- data.json
```

**cycling.db is empty or corrupt:**
```bash
py import_to_db.py
git add cycling.db data.js && git commit -m "data: rebuild db" && git push
```

**Teams out of date (mid-season transfer):**
```bash
py scraper.py --teams-only
git add data.json && git commit -m "data: refresh teams" && git push
```

**Rider missing from search:**
```bash
py scrape_rider_profiles.py
git add rider_profiles.json && git commit -m "data: rider profiles" && git push
```

**Startlist missing for upcoming race:**
```bash
py scraper.py --startlists-only
git add data.json && git commit -m "data: startlists" && git push
```

**App shows stale data:**
1. Hard-refresh: Ctrl+Shift+R
2. Check GitHub Actions — scraper may have failed
3. Trigger manually: GitHub → Actions → Run workflow

**Push notifications not working:**
- Check `push_subscriptions.json` exists and is committed
- Check `pywebpush` is installed: `pip install pywebpush`
- Corporate networks may block FCM — test on mobile data

---

## Changelog

### v25 — 2026-06-18
- Fix: `normName()` strips Unicode combining marks (NFD) so accented names (Pogačar, Möbius) match correctly across data sources
- Riders with diacritics no longer fall back to 4cr floor cost in fantasy

### v24 — 2026-06-18
- Fix: `riderCost()` normalises input via `normName()` before lookup
- Fix: `buildRiderCosts()` stores all keys as `normName()` so case/punctuation mismatches never cause misses

### v23 — 2026-06-18
- Fix: rider costs now reflect season results for PCS-format startlists (e.g. TdF)
- Frontend: `buildRiderCosts` indexes both "Firstname Surname" and "SURNAME Firstname" orderings
- Scraper: normalize PCS startlist names from "SURNAME Firstname" to "Firstname Surname" on scrape

### v22 — 2026-06-18
- Push notification support (bell button in header, VAPID subscription flow)
- Restricted start riders shown on startlist cards
- Scraper: restricted start rider detection from PCS startlist pages
- In-app notifications fired when a new stage result is detected on background refresh

### v21c — 2026-06-17
- Race selector rendered as dropdown below instructions panel
- All races selectable (not just live races)

### v21b — 2026-06-17
- Fixed `daysUntil()` rounding bug causing today's races to not appear in Upcoming tab

### v21 — 2026-06-16
- Race-keyed fantasy teams: each race has its own independent team
- No mid-race swaps; team codes are race-scoped

### v20 — 2026-06-15
- 9-rider fantasy squads; import fix for team codes; fixed fModal syntax error

### v19 — 2026-06-14
- Fantasy league MVP: pick riders, score points from stage results
- Export/import team codes for sharing

### v18 — 2026-06-13
- Startlists shown on upcoming race cards (within 21 days)
- Rider profile photos fetched incrementally (50/run)

### v17 — 2026-06-12
- Stage classifications: GC, Points, Mountain, Youth tabs
- Stage result tables with time gaps

### v15 — 2026-06-10
- Fixed rider nationality flags in race result rows (`nat_code` field)
- CyclingFlash as primary data source (replaced PCS scraping)

### v1 — 2026-06-01
- Initial release: live/upcoming/recent race tabs, PWA manifest, service worker
