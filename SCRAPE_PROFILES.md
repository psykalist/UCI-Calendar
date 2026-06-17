# Scraping Profiles

Per-site HTML structure notes. Update this file whenever a site changes structure or
a new pattern is discovered. The scraper should be tested against these profiles after
any site update.

---

## procyclingstats.com (PCS)

Base URL: `https://www.procyclingstats.com`

### Startlist page
URL pattern: `/race/{pcs-slug}/{year}/startlist`

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
      <span class="flag si"></span>          <!-- nat = second CSS class -->
      <a href="rider/tadej-pogacar">POGAČAR Tadej</a>   <!-- no <span> wrapper -->
    </li>
    ...
  </ul>
</div>
```

**Key patterns:**
- Split on `<div[^>]+class="ridersCont"` to get one block per team
- Team name: `class="team"[^>]*>([^<]+)</a>`
- Nat code: `class="flag (\w+)"></span>` (the second CSS class is the 2-letter ISO code)
- Rider slug + name: `href="rider/([^"]+)">([^<]+)</a>`

**Previous broken assumptions (do not use):**
- ~~`<ul class="riders">`~~ — ul has no class
- ~~`<b>Team Name</b>`~~ — team name is in `<a class="team">`
- ~~`<span>Name</span>` inside rider link~~ — name is direct text node
- ~~`/svg/flags/XX.svg`~~ — flags are CSS classes, not SVG URLs

---

### Race results page
URL pattern: `/race/{pcs-slug}/{year}/result/stage-{n}` or `/result`

**GC / classification standings:**
- Table with class `results` or similar
- Rider rows: `<tr>` with rank, nat flag span, rider link, time gap
- Nat: `<span class="flag XX">` pattern (same as startlist)

**Stage winner:**
- First `<tr>` in results table = stage winner

---

### Rider profile page
URL pattern: `/rider/{rider-slug}`

- Name: `<h1>` or `<title>`
- Nat: `<span class="flag XX">` near the name
- Team: link to team page

---

## cyclingflash.com (CF)

Base URL: `https://cyclingflash.com`

**Used for:** Race calendar, race metadata, stage listings, linking to PCS

### Race calendar / listing
URL: `/races.php?category=1&filter=Filter&p=uci&s=latest-results`

- Race cards with links `/race/{cf-slug}`
- Status inferred from card classes or date fields

### Race detail page
URL: `/race/{cf-slug}`

- Stage links pattern: `href="/race/{cf-slug}/result/stage-{n}"`
- Links to PCS race slug embedded in page
- **Flag SVGs**: `cyclingflash.com/svg/flags/XX.svg` — **do NOT use these in the app**
  (cross-origin blocked). Use `flagcdn.com/16x12/XX.png` everywhere instead.

---

## flagcdn.com

**Used for ALL flag rendering in the app.**

URL pattern: `https://flagcdn.com/16x12/{nat_code_lowercase}.png`

- 2-letter ISO 3166-1 alpha-2 codes (same as PCS flag CSS classes)
- Render via `<img>` tag — flag emoji Unicode does NOT render on Windows
- App helper: `flagImg(nat)` and `flag(nat)` both use this CDN

---

## General scraping notes

- **SMB truncation bug**: Writing large files through the Windows SMB mount silently
  truncates them. Always write to a temp file then `os.replace()` to the destination.
  Patch scripts use `tempfile.mkstemp()` in the same directory.
- **PCS rate limits**: Add `time.sleep(DELAY)` between requests. Use `DELAY = 1.0`.
- **HTTP 500 from PCS**: Some race/rider pages return 500 intermittently — retry 3x
  with exponential backoff before giving up.
- **Verbose fetch()**: All fetches print the URL and byte count to stdout so silent
  failures are immediately visible during a run.
- **`flush=True`**: All `print()` calls must use `flush=True` on Windows to avoid
  buffering making the output appear stalled.
