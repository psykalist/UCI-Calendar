# UCI Calendar — Architecture & Operations Guide

## Overview

A Progressive Web App (PWA) that shows live UCI road race results, upcoming races, team rosters, rider profiles, and a fantasy league. Data is scraped from **cyclingflash.com** (race results) and **procyclingstats.com** (rider specialty scores), stored in `data.json`, and served via **GitHub Pages** at `https://psykalist.github.io/UCI-Calendar/`.

---

## Data Flow

```
cyclingflash.com ──► scraper.py ──► data.json ──► GitHub Pages ──► index.html (PWA)
procyclingstats.com ─► fetch_one_rider.py (Task Scheduler)
                    └► backfill_specialties.py (manual, one-off)
```

---

## Scripts

### Core — runs automatically

#### `scraper.py`
Three modes — only `--results-only` runs automatically. The others are manual.

**`py scraper.py --results-only`** (default for CI)
Fetches only new stage results + classifications for currently live races. Refreshes wins for today's stage winners only (~1-3 extra requests on race days, 0 otherwise). Does NOT re-scrape teams, calendar, all rider profiles, or startlists. This is the safe daily mode.

**When it runs:** Via GitHub Actions (`scrape.yml`) at 11am and 5pm UTC. Also triggered by `health-check.yml` when data is stale.

**`py scraper.py`** (full scrape — manual, local only)
Discovers all calendar races, scrapes team rosters, fetches/updates up to 50 rider profiles, fetches startlists for races within 21 days. Run this at the start of the season, when teams change, or when new races are added. Do not put this in CI — too many requests.

**`py scraper.py --teams-only`** (not yet implemented — see below)
Planned: scrape only team rosters. For now, run the full scrape locally when teams need updating.

**Key behaviour:**
- Caches rider profiles from the previous `data.json` — never re-fetches a profile unless it's a stage winner today or a brand-new rider
- Preserves existing `specialties` data if the new fetch returns empty (CI IPs blocked by PCS)
- Uses `'specialties' not in profile` to detect missing data — `{}` means "checked, no PCS data" and is skipped

**What is static (pull once, don't re-scrape):**
- Team rosters — set at the start of the season
- Rider photos, DOB, nationality — never change
- Past race results (recent bucket) — already complete
- Stage details (distance, towns, parcours) — fixed once published
- Startlists — fetched once when race is within 21 days, then cached

**What updates automatically (results-only mode):**
- Stage results (top10) for live races — after each stage
- GC / Points / Mountain / Youth classifications — after each stage
- Winner's career wins list — only for today's stage winners

**Failure modes:**
- cyclingflash.com structure change → scraper returns no data for affected races
- `data.json` corrupt after failed write → restore with `py restore_from_git.py` or `git checkout data.json`

---

#### `fetch_one_rider.py`
**What it does:** Fetches PCS specialty data for ONE rider per run — the first rider in `data.json` whose `specialties` key is absent. Saves immediately. Designed for incremental backfill without hammering PCS.

**When it runs:** Windows Task Scheduler, every minute, continuously.

**Key behaviour:**
- Self-throttles: exits silently if called within 50 seconds of the last run (uses `.specialty_last_run` timestamp file)
- Uses a write lock (`.data_write.lock`) to prevent concurrent writes with other scripts
- `'specialties' not in profile` check — skips riders with `{}` (confirmed no PCS block)
- Exit code 0 = success or nothing to do; exit code 1 = fetch failed, retry next minute

**Failure modes:**
- Stale `.data_write.lock` after crash → delete `.data_write.lock` manually
- Stale `.specialty_last_run` → delete it to force an immediate run
- Runs every minute forever even when all riders are done — harmless (exits immediately with "Nothing to do")

---

#### `detect_changes.py`
**What it does:** Diffs old vs new `data.json` and appends human-readable entries to `changelog.json` (stage wins, GC leader changes, etc.). Entries older than 14 days are pruned.

**When it runs:** Called by `scrape.yml` GitHub Action immediately after `scraper.py`, before committing.

---

### Manual — run once when needed

#### `backfill_specialties.py`
**What it does:** Bulk-fetches PCS specialty data for all riders missing from `specialty_cache.json`. Writes ONLY to `specialty_cache.json` — never touches `data.json` during the run, so it cannot corrupt it. Run `apply_specialties.py` afterwards to merge.

**When to run:** After a fresh clone, after CI wipes specialty data, or when many riders are missing bars.

**Usage:**
```
py backfill_specialties.py          # fetch riders not yet in cache
py backfill_specialties.py --all    # re-fetch everything
```
Safe to Ctrl+C and re-run — saves after every rider.

---

#### `apply_specialties.py`
**What it does:** Merges `specialty_cache.json` into `data.json` in a single write. Run after `backfill_specialties.py` finishes.

**Usage:**
```
py apply_specialties.py
git add data.json specialty_cache.json && git commit -m "data: specialty backfill" && git push
```

---

#### `check_and_fix.py`
**What it does:** Health-check that validates `data.json`, `index.html`, `changelog.json`, required files, and git state. Attempts auto-fixes where possible.

**Usage:** `py check_and_fix.py`

#### `restore_from_git.py`
**What it does:** Restores `index.html` and `data.json` from the last git commit. Use when files are corrupted or truncated.

**Usage:** `py restore_from_git.py`

#### `check.sh` / `check.bat`
Quick repo health-check (git locks, JSON validity, JS syntax, sync status with remote). Writes `error.log`.

---

### Debug / one-off (safe to ignore)

`debug_gc.py`, `debug_playwright.py`, `debug_scraper.py`, `diagnose_js.py`, `probe_*.py` — diagnostic scripts used during development. Not part of normal operation.

`patch_v21.py`, `patch_v21b.py`, `patch_v21c.py`, `patch_startlist.py`, `fix_modal.py` — one-off data patches already applied. Can be archived.

`scraper_good.py`, `scraper_original.py`, `scraper_restore2.py`, `scraper_restored.py` — backup snapshots of scraper. `scraper.py` is canonical.

---

## Self-Healing System

### Architecture

```
[Windows Task Scheduler, every 5 min]
    heal.py
      ├── clears stale lock files
      ├── validates + restores data.json if corrupt
      ├── applies specialty_cache.json to fill missing riders
      ├── checks git sync
      └── writes heal.log + status.json
              │
              └──[--push flag]──► git commit + push status.json
                                          │
                                          ▼
                              [GitHub Actions: health-check.yml]
                                ├── reads status.json
                                ├── re-runs scraper if data >26h old or errored
                                ├── restores data.json from last good commit if corrupt
                                ├── writes CI status.json
                                └── posts health table to Actions summary
```

### `heal.py` — local watchdog

Run automatically via Windows Task Scheduler every 5 minutes.

**Checks and repairs:**

| Check | Auto-repair |
|-------|-------------|
| `.data_write.lock` stale (>5 min) | Delete it |
| `.specialty_last_run` stale | Delete it |
| `.git/index.lock` / `HEAD.lock` present | Delete them |
| `data.json` too small (<200 KB) | `git checkout HEAD -- data.json` |
| `data.json` invalid JSON | `git checkout HEAD -- data.json` |
| `specialty_cache.json` has entries for missing riders | Apply cache to data.json |
| Local branch behind origin/main | Warn (can't auto-pull safely) |

**Outputs:**
- `heal.log` — rolling log, last 1000 lines kept
- `status.json` — machine-readable health snapshot (pushed to GitHub with `--push`)

**Usage:**
```
py heal.py              # check + repair
py heal.py --push       # also commit + push status.json to GitHub
py heal.py --status     # print current status.json and exit
```

**status.json format:**
```json
{
  "updated_at": "2026-06-21T10:00:00+00:00",
  "source": "local",
  "overall": "ok | warning | error",
  "errors": [],
  "warnings": ["data.json is 14h old"],
  "repairs": ["Deleted stale .data_write.lock (age 312s)"],
  "data": {
    "data_size_kb": 1250,
    "data_age_hours": 14.2,
    "data_upcoming": 5,
    "data_recent": 10,
    "data_teams": 36,
    "rider_profiles": 500,
    "specialties_missing": 42,
    "specialties_with_data": 293
  }
}
```

### `health-check.yml` — GitHub Actions watchdog

Triggered when `heal.py --push` pushes `status.json`, or on schedule every 6 hours.

**What it does:**
1. Reads `status.json` — decides if scrape is needed (data >26h old, `overall == error`, or unknown)
2. Validates `data.json` — if corrupt, searches git history for last known-good commit and restores
3. Re-runs `scraper.py` + `detect_changes.py` if needed
4. Writes a new `status.json` (source: `ci`) with full health metrics
5. Commits + pushes `data.json`, `changelog.json`, `status.json`
6. Posts a health summary table to the GitHub Actions run page

**When CI can't help (local-only fixes):**
- PCS specialty data — CI IPs are blocked by procyclingstats.com
- Stale lock files on your Windows machine
- `heal.py` handles both of these locally

---

## GitHub Actions Workflows

### `scrape.yml` (primary)
Runs `scraper.py` + `detect_changes.py` and commits `data.json` + `changelog.json`.

**Schedule:** 6am UTC and 4pm UTC daily.

**Trigger manually:** GitHub → Actions tab → "Update UCI Race Data" → Run workflow.

### `update-data.yml` (secondary)
Alternate scraper workflow. Runs at 17:30 UTC daily.

---

## Key Files

| File | Purpose |
|------|---------|
| `data.json` | Master data file — all race, team, rider, and specialty data |
| `specialty_cache.json` | PCS specialty scores cache — separate from data.json to prevent corruption |
| `changelog.json` | Recent notable changes (stage wins, GC changes) shown in the app |
| `index.html` | The entire PWA — HTML + CSS + JS in one file |
| `sw.js` | Service worker — caches static assets, network-first for data.json |
| `manifest.json` | PWA manifest (icons, theme colour, install behaviour) |
| `.specialty_last_run` | Timestamp used by fetch_one_rider.py to throttle runs |
| `.data_write.lock` | Mutex file used by fetch_one_rider.py to prevent concurrent data.json writes |

---

## Self-Healing Runbook

### data.json is corrupt (JSON parse error)
```
py restore_from_git.py
# or
git checkout data.json
git pull
```

### Specialty bars missing for many riders
```
py backfill_specialties.py     # ~30 min, safe to re-run
py apply_specialties.py
git add data.json specialty_cache.json && git commit -m "data: specialty backfill" && git push
```

### fetch_one_rider.py stuck in infinite loop
Check for stale lock or wrong check condition:
```
del .data_write.lock     # if stale lock present
del .specialty_last_run  # to force immediate run
```

### git lock file error (`index.lock` or `HEAD.lock`)
```
rm -f .git/index.lock .git/HEAD.lock
```
Then retry your git command.

### Scraper returns no race data
1. Check cyclingflash.com manually — site may be down or restructured
2. Run `py debug_scraper.py` to probe the HTML structure
3. Check GitHub Actions logs for the failed run

### App shows stale data / not updating
1. Hard-refresh browser: Ctrl+Shift+R (bypasses service worker cache)
2. Check GitHub Actions — scraper may have failed silently
3. Trigger manually: GitHub → Actions → Run workflow

### CI wiped specialty data after a scrape
This was a known bug (now fixed in `scraper.py`). If it recurs:
```
py backfill_specialties.py
py apply_specialties.py
git add data.json && git commit -m "data: restore specialties" && git push
```

---

## Known Limitations

- **PCS specialty data can only be fetched locally** — CI server IPs are blocked by procyclingstats.com. The scraper preserves existing specialty data on CI runs, but newly added riders won't get specialty bars until `fetch_one_rider.py` (Task Scheduler) or a manual `backfill_specialties.py` run picks them up.
- **fetch_one_rider.py and backfill_specialties.py must not write data.json simultaneously** — the write lock prevents this, but a stale `.data_write.lock` file after a crash will block writes. Delete it manually.
- **Specialty bars show "loads on next scrape" for ~75 riders** — these riders have no PCS specialty block (retired riders, neo-pros). This is correct; the message is expected.
