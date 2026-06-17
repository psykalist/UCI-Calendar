# Changelog

All notable changes to UCI Road Calendar are documented here.

---

## v25 — 2026-06-18
- Fix: `normName()` now strips Unicode combining marks (NFD decomposition) so accented names like Pogačar, Möbius etc. correctly match across data sources
- Riders with diacritics no longer fall back to 4cr floor cost

## v24 — 2026-06-18
- Fix: `riderCost()` now normalises input via `normName()` before lookup
- Fix: `buildRiderCosts()` stores all keys as `normName()` so case/punctuation differences never cause misses
- Both fixes together resolve TdF (and all PCS-startlist) riders showing 4cr floor cost

## v23 — 2026-06-18
- Fix: rider costs now reflect season results for PCS-format startlists (e.g. TdF)
- Frontend: `buildRiderCosts` indexes both "Firstname Surname" and "SURNAME Firstname" orderings
- Scraper: normalize PCS startlist names from "SURNAME Firstname" to "Firstname Surname" on scrape

## v22 — 2026-06-18
- Push notification support (bell button in header, VAPID subscription flow)
- Restricted start riders shown on startlist cards
- Scraper: restricted start rider detection from PCS startlist pages
- Service worker cache bumped to `uci-calendar-v22`
- In-app notifications fired when a new stage result is detected on background refresh

## v21c — 2026-06-17
- Race selector rendered as dropdown below instructions panel
- All races selectable (not just live races)

## v21b — 2026-06-17
- Fixed `daysUntil()` rounding bug causing today's races to not appear in Upcoming tab

## v21 — 2026-06-16
- Race-keyed fantasy teams: each race has its own independent team
- No mid-race swaps allowed
- Team codes are race-scoped

## v20 — 2026-06-15
- 9-rider fantasy squads
- Import fix for team codes
- Fixed fModal syntax error

## v19 — 2026-06-14
- Fantasy league MVP: pick riders, score points from stage results
- Export/import team codes for sharing

## v18 — 2026-06-13
- Startlists shown on upcoming race cards (within 21 days)
- Rider profile photos fetched incrementally (50/run)

## v17 — 2026-06-12
- Stage classifications: GC, Points, Mountain, Youth tabs
- Stage result tables with time gaps

## v15 — 2026-06-10
- Fixed rider nationality flags in race result rows (`nat_code` field)
- CyclingFlash as primary data source (replaced PCS scraping)

## v1 — 2026-06-01
- Initial release: live/upcoming/recent race tabs, PWA manifest, service worker
