# Known Gaps & Limitations

A reference for what's missing from the UCI Calendar app, why, and whether it can be fixed.

---

## Data Gaps

### Stage distance & elevation showing blank
**Why:** The scraper fetches these from ProcyclingStats (PCS). PCS returns HTTP 500 on some stage detail pages — this is a server-side error on their end, not a bug in the scraper.  
**Impact:** Stage cards show "Nonekm" or blank elevation for affected stages.  
**Fix:** Reruns automatically pick up cached data once PCS recovers. No action needed.

### Rider nationality flags missing on some riders
**Why:** Race result entries from CyclingFlash store nationality as `nat_code` (e.g. `"GB"`) not `nat`. Older scraper versions didn't handle this. Fixed in v15 — flags now show correctly for any rider in race results.  
**Impact:** Riders only in team rosters (not yet in any race result) may still lack flags until their profile is fetched.  
**Fix:** Runs incrementally — 50 rider profiles per scraper run, flags fill in over time.

### Rider photos missing for most riders
**Why:** Photos are scraped from individual rider profile pages on CyclingFlash. With ~800 pro riders, fetching all at once would take 20+ minutes. Capped at 50 new profiles per scraper run.  
**Impact:** Placeholder avatar shown instead of photo.  
**Fix:** Runs incrementally each time the scraper runs. Fully populated after ~16 runs.

### Team rosters empty (fantasy rider pool limited)
**Why:** `scrape_teams.py` must be run separately. It scrapes all 35 WorldTeam + ProTeam rosters (~800 riders total, ~2 minutes).  
**Impact:** Fantasy league only shows riders who have appeared in race results (~250 riders). Many riders unavailable to pick.  
**Fix:** Run `python3 scrape_teams.py` once from Git Bash. Only needs re-running if rosters change mid-season.

### Startlists missing for races more than 21 days away
**Why:** PCS often doesn't publish startlists until ~2 weeks before a race. Fetching them early returns empty or partial data. Scraper intentionally skips races >21 days out.  
**Impact:** No startlist shown on upcoming race cards for far-future races.  
**Fix:** Automatically fetches on the next scraper run once the race is within 21 days.

### Stage route map / height profile images missing on some stages
**Why:** These images are served from CyclingFlash's CDN and are only available once they publish them, typically a few days before each stage.  
**Impact:** No profile image shown on stage cards.  
**Fix:** Scraper picks them up automatically once CyclingFlash publishes them.

---

## Structural Limitations (by design — cannot be fixed without a backend)

### Fantasy teams are device-local only
**Why:** All data is stored in browser `localStorage`. There is no server or database.  
**Impact:** Your team only exists on the device/browser where you created it. Clearing browser data deletes it.  
**Workaround:** Use the Export Code to back up your team. Share the code with others to import your team on their device.

### No real-time leaderboard sync
**Why:** Same reason — no backend. Each user's team lives on their own device.  
**Workaround:** Everyone exports their code and pastes it into a shared channel/group chat. The leaderboard is built from imported codes.

### No live race tracking / GPS
**Why:** Live position data requires a paid race data provider (e.g. Velon, ASO). Not available from any free source.  
**Impact:** "Live" races show stage results only after the stage finishes and CyclingFlash publishes results.

### PCS rate limiting / blocks
**Why:** ProcyclingStats blocks automated scrapers intermittently. The scraper uses polite delays (1.2s between requests) and a browser User-Agent to reduce this, but occasional 403/500 errors are expected.  
**Impact:** Some stage details or startlists may fail on a given run and succeed on the next.  
**Fix:** Just re-run the scraper. Cached data from previous runs is never overwritten by a failed fetch.

---

## How the Scraper Runs

| Step | What it does | Typical time |
|------|-------------|-------------|
| 1/4 | Discovers all UCI races from CyclingFlash calendar | ~10s |
| 2/4 | Fetches race info, stage results, classifications | 3–8 min |
| 3/4 | Scrapes team rosters (35 teams, ~800 riders) | ~2 min |
| 3b/4 | Fetches up to 50 new rider profiles (incremental) | ~1 min |
| 3c/4 | Fetches startlists for races within 21 days | ~30s |
| 4/4 | Writes data.json and pushes to GitHub | ~10s |

Run daily or after major race stages finish to keep data current.
