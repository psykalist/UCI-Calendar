#!/usr/bin/env python3
"""
scrape_rider_full.py — Fetch complete rider profiles from PCS into cycling.db.

For each rider scrapes:
  /rider/{slug}                 → photo, DOB, team history by year, specialties, PCS rank
  /rider/{slug}/results         → full season results with PCS & UCI points

Runs incrementally: skips riders already in db with profile_fetched_at set.
Prioritises riders in current startlists (priority=1 in scrape_queue).

Usage:
  python scrape_rider_full.py              # fetch next 50 unfetched, priority order
  python scrape_rider_full.py --limit 100  # fetch next N
  python scrape_rider_full.py --slug tadej-pogacar  # fetch one specific rider
  python scrape_rider_full.py --refetch    # re-fetch all (ignores fetched_at)

Must run locally – PCS may block cloud/CI IPs.
After running:
  git add cycling.db && git commit -m "data: rider profiles batch" && git push
"""

import sqlite3, re, time, sys, datetime, argparse
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

BASE    = Path(__file__).parent
DB_PATH = BASE / "cycling.db"
PCS     = "https://www.procyclingstats.com"
DELAY   = 1.2  # seconds between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── HTTP ─────────────────────────────────────────────────────────────────────

def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            if e.code == 404:
                return None
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None

def strip(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


# ── Parsers ──────────────────────────────────────────────────────────────────

def parse_profile(html, slug):
    """Parse /rider/{slug} → dict with photo, dob, place_of_birth, current_team,
    pcs_rank, specialties, teams_by_year."""
    if not html:
        return {}

    data = {}

    # Photo (og:image or JSON-LD)
    m = re.search(r'"image"\s*:\s*\{\s*"@type"\s*:[^}]*"url"\s*:\s*"([^"]+)"', html)
    if not m:
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
    if m:
        data["photo"] = m.group(1)

    # DOB  e.g. "21st September 1998"
    dob_m = re.search(
        r'(\d{1,2})(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})',
        html, re.IGNORECASE
    )
    if dob_m:
        MONTHS = {
            "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
            "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
        }
        mo = MONTHS.get(dob_m.group(2).lower())
        if mo:
            data["dob"] = f"{dob_m.group(3)}-{mo:02d}-{int(dob_m.group(1)):02d}"

    # Place of birth
    pb_m = re.search(r'Place of birth[:\s]*</[^>]+>\s*([A-Za-z ,\-]+)', html)
    if pb_m:
        data["place_of_birth"] = pb_m.group(1).strip()

    # PCS rank
    rank_m = re.search(r'PCS Ranking\s*</[^>]+>\s*(\d+)', html)
    if rank_m:
        data["pcs_rank"] = int(rank_m.group(1))

    # Specialty scores  – look for pattern like "9983\nOnedayraces"
    spec_map = {
        "onedayraces": "spec_oneday", "gc": "spec_gc", "tt": "spec_tt",
        "sprint": "spec_sprint", "climber": "spec_climber", "hills": "spec_hills",
    }
    for raw, key in spec_map.items():
        sm = re.search(
            rf'(\d+)\s*(?:</[^>]+>\s*)?{raw}',
            html, re.IGNORECASE
        )
        if sm:
            data[key] = int(sm.group(1))

    # Teams by year  e.g. "2026\nUAE Team Emirates - XRG (WT)"
    teams = []
    for tm in re.finditer(
        r'(20\d{2})\s*</[^>]*>\s*<[^>]+>\s*([^<\n]{4,80?})\s*(?:\((?:WT|PT|CT|CC|CLUB)\))?',
        html
    ):
        yr, team_name = tm.group(1), strip(tm.group(2)).strip()
        if team_name and year_plausible(int(tm.group(1))):
            teams.append({"year": int(yr), "team": team_name})

    # Fallback: plain text pattern
    if not teams:
        for tm in re.finditer(
            r'\b(20\d{2})\b\s+([A-Z][A-Za-z \''\-]+(?:\s+\((?:WT|PT|CT|CC|CLUB)\))?)',
            html
        ):
            yr = int(tm.group(1))
            team_name = tm.group(2).strip()
            if year_plausible(yr) and len(team_name) > 4:
                teams.append({"year": yr, "team": team_name})

    data["teams"] = teams
    return data


def year_plausible(y):
    return 2000 <= y <= 2032


def parse_results(html, slug):
    """Parse /rider/{slug}/results → list of season result rows."""
    if not html:
        return []
    rows = []
    # Table rows: date | result | race | distance | pcs_pts | uci_pts
    # Pattern from PCS results page (plain text rendering)
    # e.g. "21.06 1 Stage 5 - Villars 150.7 50 60"
    current_year = datetime.date.today().year
    year = current_year  # will update when we see year headers

    for line in html.split("\n"):
        line = line.strip()
        # Year header
        ym = re.match(r"^(20\d{2})$", line)
        if ym:
            year = int(ym.group(1))
            continue

        # Result line: DD.MM [gc_pos] [stage_pos] Race text [distance] [pcs] [uci]
        rm = re.match(
            r"^(\d{2}\.\d{2})\s+"          # date DD.MM
            r"(?:(\d+)\s+)?"               # optional GC pos
            r"(\d+)\s+"                    # stage/result pos
            r"(.+?)\s+"                    # race name
            r"(\d+(?:\.\d+)?)\s+"         # distance
            r"(\d+)\s+"                   # pcs pts
            r"(\d+)",                     # uci pts
            line
        )
        if rm:
            date_str = f"{year}-{rm.group(1)[3:5]}-{rm.group(1)[:2]}"
            rows.append({
                "year": year,
                "date": date_str,
                "gc_pos": int(rm.group(2)) if rm.group(2) else None,
                "stage_pos": int(rm.group(3)),
                "race_raw": rm.group(4).strip(),
                "distance_km": float(rm.group(5)),
                "pcs_points": int(rm.group(6)),
                "uci_points": int(rm.group(7)),
            })

    return rows


# ── Database helpers ──────────────────────────────────────────────────────────

def open_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def save_profile(conn, slug, profile):
    now = datetime.datetime.utcnow().isoformat()
    c = conn.cursor()

    update_fields = {"profile_fetched_at": now}
    for k in ("photo","dob","place_of_birth","pcs_rank",
               "spec_oneday","spec_gc","spec_tt","spec_sprint","spec_climber","spec_hills"):
        if k in profile:
            update_fields[k] = profile[k]

    set_clause = ", ".join(f"{k}=?" for k in update_fields)
    c.execute(
        f"UPDATE riders SET {set_clause} WHERE slug=?",
        list(update_fields.values()) + [slug]
    )

    # Teams
    for t in profile.get("teams", []):
        c.execute("""INSERT OR REPLACE INTO rider_teams(rider_slug,year,team)
            VALUES(?,?,?)""", (slug, t["year"], t["team"]))

    # Current team = most recent year's team
    if profile.get("teams"):
        most_recent = max(profile["teams"], key=lambda x: x["year"])
        c.execute("UPDATE riders SET current_team=? WHERE slug=?",
                  (most_recent["team"], slug))

    # Mark queue done
    c.execute("UPDATE scrape_queue SET fetched_at=?,attempts=attempts+1 WHERE slug=? AND type='rider_full'",
              (now, slug))
    conn.commit()


def save_career(conn, slug, rows):
    now = datetime.datetime.utcnow().isoformat()
    c = conn.cursor()
    inserted = 0
    for row in rows:
        race_raw = row.get("race_raw","")
        # Try to extract race_slug from race_raw (simplified)
        stage_m = re.search(r"Stage (\d+)", race_raw)
        stage_label = f"Stage {stage_m.group(1)}" if stage_m else ""
        try:
            c.execute("""INSERT OR IGNORE INTO rider_season_results
                (rider_slug,year,date,race_name,stage_label,gc_pos,stage_pos,distance_km,pcs_points,uci_points)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (slug, row["year"], row["date"], race_raw, stage_label,
                 row.get("gc_pos"), row.get("stage_pos"),
                 row.get("distance_km"), row.get("pcs_points",0), row.get("uci_points",0)))
            if c.rowcount: inserted += 1
        except Exception:
            pass
    c.execute("UPDATE riders SET career_fetched_at=? WHERE slug=?", (now, slug))
    conn.commit()
    return inserted


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50, help="Max riders to fetch")
    parser.add_argument("--slug", help="Fetch a single specific rider slug")
    parser.add_argument("--refetch", action="store_true", help="Re-fetch already-fetched riders")
    args = parser.parse_args()

    conn = open_db()
    c = conn.cursor()

    if args.slug:
        slugs = [args.slug]
    else:
        if args.refetch:
            c.execute("""SELECT slug FROM scrape_queue
                WHERE type='rider_full' ORDER BY priority, slug LIMIT ?""", (args.limit,))
        else:
            c.execute("""SELECT q.slug FROM scrape_queue q
                JOIN riders r ON r.slug=q.slug
                WHERE q.type='rider_full' AND r.profile_fetched_at IS NULL
                ORDER BY q.priority, q.slug LIMIT ?""", (args.limit,))
        slugs = [r[0] for r in c.fetchall()]

    print(f"Fetching {len(slugs)} rider profiles...")
    ok = skipped = errors = 0

    for i, slug in enumerate(slugs, 1):
        print(f"  [{i}/{len(slugs)}] {slug}", end="  ", flush=True)

        # Profile page
        html = fetch(f"{PCS}/rider/{slug}")
        time.sleep(DELAY)

        if html is None:
            print("404 – skipped")
            skipped += 1
            continue

        profile = parse_profile(html, slug)
        save_profile(conn, slug, profile)

        # Career results page
        html2 = fetch(f"{PCS}/rider/{slug}/results")
        time.sleep(DELAY)
        if html2:
            rows = parse_results(html2, slug)
            n = save_career(conn, slug, rows)
            print(f"teams={len(profile.get('teams',[]))} career_rows={n}")
        else:
            print(f"teams={len(profile.get('teams',[]))} career=none")

        ok += 1

    print(f"\nDone. fetched={ok} skipped={skipped} errors={errors}")
    conn.close()


if __name__ == "__main__":
    main()
