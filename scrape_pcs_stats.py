"""
scrape_pcs_stats.py — scrape all PCS statistics pages into pcs_stats.json.

All pages are server-rendered and don't require JavaScript.
Must be run locally — CI/server IPs are blocked by PCS.

Usage:
    py scrape_pcs_stats.py              # fetch missing pages only
    py scrape_pcs_stats.py --all        # re-fetch everything
    py scrape_pcs_stats.py --fix-empty  # re-fetch pages that returned 0 rows
    py scrape_pcs_stats.py --static     # fetch only static (historical) pages
    py scrape_pcs_stats.py --dynamic    # fetch only dynamic (current season) pages
    py scrape_pcs_stats.py --list       # print all stat IDs and exit

Output: pcs_stats.json

Refresh cadence:
  static   — pull once per season (historical data, pre-2026 entries never change)
  dynamic  — pull weekly during racing season (current-season or career totals
             that grow as riders race)
"""

import json
import os
import re
import sys
import time
import tempfile
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
OUT_FILE    = os.path.join(BASE_DIR, "pcs_stats.json")
PCS         = "https://www.procyclingstats.com"
DELAY       = 5      # seconds between requests — be polite
TIMEOUT     = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# ── Stat registry ──────────────────────────────────────────────────────────────
# Each entry: (id, label, url_path, category, subcategory, is_static, notes)
# is_static=True  → pull once per season; pre-2026 entries frozen
# is_static=False → pull weekly; updates as riders race / decisions are made
STATS = [

    # ── Riders / General ──────────────────────────────────────────────────────
    ("riders/no-starts-yet",         "Riders with no start yet",         "statistics/riders/riders-with-no-starts-yet",              "riders", "general",    False, "Shrinks as season progresses"),
    ("riders/most-races-started",    "Most races started",               "statistics/riders/most-races-started",                     "riders", "general",    False, "Career total; grows for active riders"),
    ("riders/most-competed-one-race","Most competed in one race",        "statistics/riders/most-competed-in-one-race",               "riders", "general",    False, "Career total"),
    ("riders/tallest-shortest",      "Tallest and shortest",             "statistics/riders/tallest-shortest",                       "riders", "general",    True,  "Physical data; never changes"),
    ("riders/king-of-classics",      "King of the classics",             "statistics/riders/king-of-the-classics",                   "riders", "general",    False, "Career points in one-day races; grows"),
    ("riders/nationality-changes",   "Nationality changes",              "statistics/riders/riders-that-changed-nationality",         "riders", "general",    True,  "Historical; rarely changes"),
    ("riders/twins",                 "Twins",                            "statistics/riders/twins",                                  "riders", "general",    True,  "Static novelty stat"),
    ("riders/recently-passed-away",  "Recently passed away",             "statistics/riders/recently-passed-away",                   "riders", "general",    False, "Updated as riders pass away"),
    ("riders/born-on-date",          "Born on date",                     "statistics/riders/born-on-date",                           "riders", "general",    True,  "Historical; never changes"),

    # ── Riders / Age ──────────────────────────────────────────────────────────
    ("riders/youngest-riders",       "Youngest riders",                  "statistics/riders/youngest-riders",                        "riders", "age",         True,  "Current roster; stable"),
    ("riders/oldest-riders",         "Oldest riders",                    "statistics/riders/oldest-riders",                          "riders", "age",         True,  "Current roster; stable"),
    ("riders/youngest-winners",      "Youngest winners per season",      "statistics/riders/youngest-winners-per-season",            "riders", "age",         False, "Past seasons frozen; current season grows"),

    # ── Riders / Badges ───────────────────────────────────────────────────────
    ("riders/most-badges",           "Most badges",                      "statistics/riders/most-badges",                            "riders", "badges",      False, "Career achievement; grows"),
    ("riders/badges",                "Badges list",                      "statistics/riders/badges",                                 "riders", "badges",      True,  "Badge definitions; static"),

    # ── Riders / Results ──────────────────────────────────────────────────────
    ("riders/most-dnf",              "Most DNFs",                        "statistics/riders/most-dnf",                               "riders", "results",     False, "Career total; grows"),
    ("riders/no-dnf",                "Riders without DNF",               "statistics/riders/riders-without-dnf",                     "riders", "results",     False, "Dynamic; shrinks after each DNF"),
    ("riders/points-per-raceday",    "Points per race day",              "statistics/riders/points-per-raceday",                     "riders", "results",     False, "Current season efficiency"),
    ("riders/wins-wt-level",         "Wins on WT level",                 "statistics/riders/wins-on-wt-level",                       "riders", "results",     False, "Career total; grows"),
    ("riders/longest-no-dnf",        "Longest without DNF",              "statistics/riders/longest-without-dnf",                    "riders", "results",     False, "Streak; changes each race"),
    ("riders/wins-world-champions",  "Wins by world champions",          "statistics/riders/wins-by-world-champions",                "riders", "results",     False, "Career total; grows"),
    ("riders/5-continent-winners",   "5 continent winners",              "statistics/riders/riders-winning-on-5-continents",         "riders", "results",     True,  "Very rare; essentially static"),
    ("riders/penalty-points",        "UCI Penalty Points ranking",       "statistics/riders/penalty-points-ranking",                 "riders", "results",     False, "Updated after each ruling"),
    ("riders/penalty-points-teams",  "Penalty points by team",           "statistics/riders/penalty-points-ranking-teams",           "riders", "results",     False, "Updated after each ruling"),
    ("riders/family-stats",          "Family statistics",                "statistics/riders/family-related-riders-winning-on-same-day","riders","results",   True,  "Historical novelty"),
    ("riders/wt-classics-ranking",   "WT one-day races ranking",         "statistics/riders/wt-classics-ranking",                    "riders", "results",     False, "Career total; grows"),
    ("riders/solo-victories",        "Solo victories",                   "statistics/riders/solo-victories",                         "riders", "results",     False, "Career total; grows"),
    ("riders/hometown-winners",      "Hometown winners",                 "statistics/riders/riders-winning-in-their-hometown",       "riders", "results",     True,  "Historical; essentially static"),
    ("riders/u23-points",            "U23 points trend",                 "statistics/riders/points-scored-by-riders-u23",            "riders", "results",     False, "Current U23 cohort"),
    ("riders/age-first-win",         "Average age of first win",         "statistics/riders/age-of-first-win",                       "riders", "results",     True,  "Historical averages; stable"),
    ("riders/last-season-best",      "Last season best season",          "statistics/riders/last-season-best-season",                "riders", "results",     False, "Updates each season"),

    # ── Riders / This season ──────────────────────────────────────────────────
    ("riders/gt-gc-riders",          "Grand tour GC riders",             "statistics/riders/grand-tour-roster-for-top-gc-riders",    "riders", "season",      False, "Current season lineups"),
    ("riders/top100-season-start",   "Season start for top-100",         "statistics/riders/where-will-the-top-100-start-their-season","riders","season",    False, "Current season; updates early in year"),

    # ── Riders / Specialists ──────────────────────────────────────────────────
    ("riders/most-allround",         "Most allround riders",             "statistics/riders/most-allround-riders",                   "riders", "specialists", False, "PCS scores; update seasonally"),
    ("riders/single-specialty",      "Single specialty riders",          "statistics/riders/single-specialty-riders",                "riders", "specialists", False, "PCS scores; update seasonally"),
    ("riders/alltime-tt-ranking",    "All time TT ranking",              "statistics/riders/all-time-time-trial-ranking",            "riders", "specialists", False, "Career total; grows"),

    # ── Riders / Injuries ─────────────────────────────────────────────────────
    ("riders/injuries",              "Injuries (all time)",              "statistics/riders/injuries",                               "riders", "injuries",    True,  "Historical injury records"),
    ("riders/season-injuries",       "Injuries this season",             "statistics/riders/season-injuries",                        "riders", "injuries",    False, "Current season; updates frequently"),
    ("riders/not-returned",          "Not returned after injury",        "statistics/riders/not-back-in-action-after-injury",        "riders", "injuries",    False, "Live; updates as riders return"),

    # ── Grand Tours ───────────────────────────────────────────────────────────
    ("grandtours/most-starts",       "Grand tour most starts",           "statistics/grandtours/most-starts",                        "grandtours", "general", False, "Career total; grows"),
    ("grandtours/most-wins",         "Grand tour most wins",             "statistics/grandtours/most-wins",                          "grandtours", "general", False, "Career total; grows"),
    ("grandtours/all-3-gts",         "Stage winners in all 3 GTs",      "statistics/grandtours/stage-winners-in-all-3-gts",         "grandtours", "general", False, "Career achievement; grows"),
    ("grandtours/most-stage-wins",   "Grand tour most stage wins",       "statistics/grandtours/most-stage-wins",                    "grandtours", "general", False, "Career total; grows"),
    ("grandtours/stage-wins-teams",  "Grand tour stage wins by teams",   "statistics/grandtours/stage-wins-by-teams",                "grandtours", "teams",   False, "Career total; grows"),

    # ── Monuments ─────────────────────────────────────────────────────────────
    ("monuments/most-wins",          "Monument most wins",               "statistics/monuments/most-wins",                           "monuments", "general",  False, "Career total; grows"),
    ("monuments/youngest-winners",   "Monument youngest winners",        "statistics/monuments/youngest-winners",                    "monuments", "age",      True,  "Historical; essentially static"),
    ("monuments/oldest-winners",     "Monument oldest winners",          "statistics/monuments/oldest-winners",                      "monuments", "age",      True,  "Historical; essentially static"),

    # ── Teams ─────────────────────────────────────────────────────────────────
    ("teams/overview",               "Teams statistics",                 "statistics/teams",                                         "teams",  "general",     False, "Current season team stats"),

    # ── Nations ───────────────────────────────────────────────────────────────
    ("nations/overview",             "Nations statistics",               "statistics/nations",                                       "nations", "general",    False, "Current season nation stats"),

    # ── Races ─────────────────────────────────────────────────────────────────
    ("races/fastest-tts",            "Fastest time trials",              "statistics/races/fastest-time-trials",                     "races", "general",     True,  "Historical records; very rarely broken"),

    # ── Major Tours ───────────────────────────────────────────────────────────
    ("major-tours/overview",         "Major tours statistics",           "statistics/major-tours",                                   "major-tours", "general", False, "Career totals; grows"),

    # ── Race Combos ───────────────────────────────────────────────────────────
    ("combos/overview",              "Race combination winners",         "statistics/combos",                                        "combos", "general",     True,  "Historical; very rare"),

    # ── Gear ──────────────────────────────────────────────────────────────────
    ("gear/overview",                "Equipment / gear",                 "statistics/gear",                                          "gear", "general",       False, "Updates as teams change equipment"),

    # ── Climbs ────────────────────────────────────────────────────────────────
    ("climbs/most-visited",          "Most visited climbs",              "statistics/climbs/most-visited",                           "climbs", "general",     False, "Career totals; grows"),
]

# ── HTML utilities ─────────────────────────────────────────────────────────────

def strip_tags(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
         .replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
    s = re.sub(r'&#(\d+);',           lambda m: chr(int(m.group(1))),     s)
    s = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), s)
    return re.sub(r'\s+', ' ', s).strip()


def fetch(url):
    for attempt in range(3):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=TIMEOUT) as r:
                data = r.read().decode('utf-8', errors='replace')
            if len(data) < 500:
                raise ValueError(f"Response too short ({len(data)} chars)")
            return data
        except HTTPError as e:
            if e.code == 404:
                return None
            print(f"  HTTP {e.code} (attempt {attempt+1}/3)", flush=True)
            time.sleep(2 ** attempt)
        except (URLError, OSError, ValueError) as e:
            print(f"  Error: {e} (attempt {attempt+1}/3)", flush=True)
            time.sleep(2 ** attempt)
    return None


# ── Generic table parser ───────────────────────────────────────────────────────

def parse_stat_table(html, stat_id):
    """
    Parse the main data table from a PCS statistics page.
    Returns list of row dicts: {pos, name, slug, extra columns...}

    Handles:
    - Standard rider table: Pos | Rider (link) | Value(s)
    - Team table: Pos | Team (link) | Value(s)
    - Nation/other tables: Pos | Name | Value(s)
    """
    rows = []

    # Find the main content table — skip nav tables, look for one with numeric rank
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)

    main_table = None
    for tbl in tables:
        # Must have at least one row with a numeric rank in first td
        if re.search(r'<td[^>]*>\s*\d+\s*</td>', tbl):
            main_table = tbl
            break

    if not main_table:
        return rows

    # Extract header row
    header_row = re.search(r'<thead[^>]*>(.*?)</thead>', main_table, re.DOTALL)
    headers = []
    if header_row:
        ths = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', header_row.group(1), re.DOTALL)
        headers = [strip_tags(h).strip() for h in ths]

    # Extract body rows
    tbody_m = re.search(r'<tbody[^>]*>(.*?)</tbody>', main_table, re.DOTALL)
    tbody   = tbody_m.group(1) if tbody_m else main_table

    for tr_m in re.finditer(r'<tr[^>]*>(.*?)</tr>', tbody, re.DOTALL):
        tr = tr_m.group(1)
        cells = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
        if len(cells) < 2:
            continue

        # Rank must be numeric in first cell
        rank_text = strip_tags(cells[0]).strip()
        try:
            rank = int(rank_text)
        except ValueError:
            continue

        row = {"pos": rank}

        # Look for a rider/team/race link in any cell
        # Handle both absolute (/rider/slug) and relative (rider/slug) hrefs
        link_m = re.search(
            r'href=["\'](?:https://www\.procyclingstats\.com)?/?(rider|team|race|nation)/([^"\'/?]+)["\']',
            tr
        )
        if link_m:
            row["type"] = link_m.group(1)   # rider / team / race / nation
            row["slug"] = link_m.group(2).strip("/")
            # Name: text content of the link
            name_m = re.search(
                r'href=["\'](?:https://www\.procyclingstats\.com)?/?(?:rider|team|race|nation)/[^"\']+["\'][^>]*>(.*?)</a>',
                tr, re.DOTALL
            )
            row["name"] = strip_tags(name_m.group(1)).strip() if name_m else row["slug"]
        else:
            # No link — plain text name (nation, etc.)
            row["type"] = "other"
            row["slug"] = ""
            row["name"] = strip_tags(cells[1]).strip() if len(cells) > 1 else ""

        # Remaining cells as values
        # Map to header names if available, otherwise val1, val2...
        value_cells = cells[2:]
        for i, cell in enumerate(value_cells):
            val = strip_tags(cell).strip()
            if val:
                if headers and i + 2 < len(headers):
                    key = re.sub(r'[^a-z0-9_]', '_', headers[i + 2].lower()).strip('_') or f"val{i+1}"
                else:
                    key = f"val{i+1}"
                row[key] = val

        # If only one value column and no header mapping, alias as "value"
        if "val1" in row and len(value_cells) == 1:
            row["value"] = row.pop("val1")

        rows.append(row)

    return rows


# ── Custom parser helpers ──────────────────────────────────────────────────────

def _get_table_rows(html):
    """Return list of raw <table>…</table> inner HTML strings."""
    return re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)


def _get_tr_cells(tbl):
    """Yield list of raw <td>…</td> inner HTML strings for each <tr>."""
    for tr_m in re.finditer(r'<tr[^>]*>(.*?)</tr>', tbl, re.DOTALL):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', tr_m.group(1), re.DOTALL)
        if cells:
            yield cells


def _rider_link(cell_html):
    """Extract (slug, name) from a cell containing a rider link."""
    m = re.search(
        r'href=["\'](?:https://www\.procyclingstats\.com)?/?rider/([^"\'/?]+)["\'][^>]*>(.*?)</a>',
        cell_html, re.DOTALL
    )
    if m:
        return m.group(1).strip('/'), strip_tags(m.group(2)).strip()
    return '', strip_tags(cell_html).strip()


def _team_link(cell_html):
    """Extract (slug, name) from a cell containing a team link."""
    m = re.search(
        r'href=["\'](?:https://www\.procyclingstats\.com)?/?team/([^"\'/?]+)["\'][^>]*>(.*?)</a>',
        cell_html, re.DOTALL
    )
    if m:
        return m.group(1).strip('/'), strip_tags(m.group(2)).strip()
    return '', strip_tags(cell_html).strip()


def _race_link(cell_html):
    """Extract (slug, name) from a cell containing a race link."""
    m = re.search(
        r'href=["\'](?:https://www\.procyclingstats\.com)?/?race/([^"\'/?]+)["\'][^>]*>(.*?)</a>',
        cell_html, re.DOTALL
    )
    if m:
        return m.group(1).strip('/'), strip_tags(m.group(2)).strip()
    return '', strip_tags(cell_html).strip()


def _valuebar(cell_html):
    """Extract the numeric label from a PCS valuebar div."""
    m = re.search(r'class="title[^"]*">([^<]+)<', cell_html)
    return m.group(1).strip() if m else strip_tags(cell_html).strip()


# ── Custom parsers ─────────────────────────────────────────────────────────────

def parse_recently_passed_away(html, stat_id):
    """Date | Rider | Age — no numeric rank column."""
    rows = []
    for tbl in _get_table_rows(html):
        for cells in _get_tr_cells(tbl):
            if len(cells) < 2:
                continue
            date = strip_tags(cells[0]).strip()
            if not re.match(r'\d{4}-\d{2}-\d{2}', date):
                continue
            slug, name = _rider_link(cells[1])
            row = {'date': date, 'type': 'rider', 'slug': slug, 'name': name}
            if len(cells) >= 3:
                row['age'] = strip_tags(cells[2]).strip()
            rows.append(row)
        if rows:
            break
    return rows


def parse_family_stats(html, stat_id):
    """
    Table 0: Date | Rider1 | Rider2              (same-day wins)
    Table 1: Date | Rider1 | Rider2 | Race        (same-race wins)
    """
    rows = []
    section_labels = ['same_day_wins', 'same_race_wins']
    for tbl_idx, tbl in enumerate(_get_table_rows(html)):
        section = section_labels[tbl_idx] if tbl_idx < 2 else f'section_{tbl_idx}'
        for cells in _get_tr_cells(tbl):
            if len(cells) < 3:
                continue
            date = strip_tags(cells[0]).strip()
            if not re.match(r'\d{4}-\d{2}-\d{2}', date):
                continue
            s1, n1 = _rider_link(cells[1])
            s2, n2 = _rider_link(cells[2])
            row = {
                'section': section, 'date': date,
                'rider1_slug': s1, 'rider1_name': n1,
                'rider2_slug': s2, 'rider2_name': n2,
            }
            if len(cells) >= 4:
                rs, rn = _race_link(cells[3])
                row['race_slug'] = rs
                row['race_name'] = rn
            rows.append(row)
    return rows


def parse_solo_victories(html, stat_id):
    """
    Table 0: Date | Race | Winner | KM Solo           (latest, date-keyed)
    Table 1: # | Rider | flag | KM(valuebar) | | Race (longest, rank-keyed)
    """
    rows = []
    for tbl_idx, tbl in enumerate(_get_table_rows(html)):
        section = 'latest' if tbl_idx == 0 else 'longest'
        for cells in _get_tr_cells(tbl):
            if len(cells) < 3:
                continue
            first = strip_tags(cells[0]).strip()
            row = {'section': section}
            if section == 'latest':
                if not re.match(r'\d{4}-\d{2}-\d{2}', first):
                    continue
                row['date'] = first
                rs, rn = _race_link(cells[1])
                row['race_slug'] = rs
                row['race_name'] = rn
                ws, wn = _rider_link(cells[2])
                row['rider_slug'] = ws
                row['rider_name'] = wn
                if len(cells) >= 4:
                    row['km_solo'] = strip_tags(cells[3]).strip()
            else:  # longest — # | Rider | flag | valuebar(km) | | Race
                try:
                    row['pos'] = int(first)
                except ValueError:
                    continue
                s, n = _rider_link(cells[1])
                row['rider_slug'] = s
                row['rider_name'] = n
                if len(cells) >= 4:
                    row['km_solo'] = _valuebar(cells[3])
                if len(cells) >= 6:
                    rs, rn = _race_link(cells[5])
                    row['race_slug'] = rs
                    row['race_name'] = rn
                elif len(cells) >= 5:
                    rs, rn = _race_link(cells[4])
                    row['race_slug'] = rs
                    row['race_name'] = rn
            rows.append(row)
    return rows


def parse_not_returned(html, stat_id):
    """Date of injury | Days since injury | Rider | Injury description."""
    rows = []
    for tbl in _get_table_rows(html):
        for cells in _get_tr_cells(tbl):
            if len(cells) < 3:
                continue
            date = strip_tags(cells[0]).strip()
            if not re.match(r'\d{4}-\d{2}-\d{2}', date):
                continue
            days = strip_tags(cells[1]).strip()
            slug, name = _rider_link(cells[2])
            row = {
                'date_of_injury': date,
                'days_since_injury': days,
                'type': 'rider', 'slug': slug, 'name': name,
            }
            if len(cells) >= 4:
                row['injury'] = strip_tags(cells[3]).strip()
            rows.append(row)
        if rows:
            break
    return rows


def parse_teams_overview(html, stat_id):
    """
    Team | flag | Wins(valuebar) — no numeric rank, two tables (men, women).
    Assigns pos 1..N within each section based on page order.
    """
    rows = []
    section_labels = ['men', 'women']
    for tbl_idx, tbl in enumerate(_get_table_rows(html)):
        section = section_labels[tbl_idx] if tbl_idx < 2 else f'section_{tbl_idx}'
        pos = 1
        for cells in _get_tr_cells(tbl):
            if len(cells) < 2:
                continue
            slug, name = _team_link(cells[0])
            if not slug:
                continue
            wins = _valuebar(cells[-1]) if len(cells) >= 3 else strip_tags(cells[-1]).strip()
            rows.append({
                'pos': pos, 'section': section,
                'type': 'team', 'slug': slug, 'name': name, 'wins': wins,
            })
            pos += 1
    return rows


def parse_combos_overview(html, stat_id):
    """Landing/nav page only — no data table."""
    return []


CUSTOM_PARSERS = {
    "riders/recently-passed-away": parse_recently_passed_away,
    "riders/family-stats":         parse_family_stats,
    "riders/solo-victories":       parse_solo_victories,
    "riders/not-returned":         parse_not_returned,
    "teams/overview":              parse_teams_overview,
    "combos/overview":             parse_combos_overview,
}


# ── Cache helpers ──────────────────────────────────────────────────────────────

def load_cache():
    try:
        with open(OUT_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"updated_at": None, "stats": {}}


def save_cache(cache):
    cache["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = OUT_FILE + f".tmp{os.getpid()}"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    for _ in range(10):
        try:
            os.replace(tmp, OUT_FILE)
            return
        except PermissionError:
            time.sleep(0.2)
    os.remove(tmp)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args = set(sys.argv[1:])

    if "--list" in args:
        print(f"\n{'ID':<40} {'Static':<8} Label")
        print("-" * 80)
        for sid, label, path, cat, subcat, is_static, notes in STATS:
            print(f"  {sid:<40} {'yes' if is_static else 'no':<8} {label}")
        print(f"\nTotal: {len(STATS)} stat pages")
        return

    refetch_all  = "--all"        in args
    fix_empty    = "--fix-empty"  in args
    only_static  = "--static"     in args
    only_dynamic = "--dynamic"    in args

    # Build work list
    work = STATS
    if only_static:
        work = [s for s in STATS if s[5]]
        print(f"Mode: static pages only ({len(work)})")
    elif only_dynamic:
        work = [s for s in STATS if not s[5]]
        print(f"Mode: dynamic pages only ({len(work)})")
    elif fix_empty:
        print("Mode: re-fetch pages with 0 rows (custom parsers)")
    else:
        print(f"Mode: {'all' if refetch_all else 'missing only'} ({len(work)} pages)")

    cache = load_cache()
    stats = cache.setdefault("stats", {})

    if fix_empty:
        missing = [s for s in work if stats.get(s[0], {}).get("row_count", 0) == 0]
    elif not refetch_all:
        missing = [s for s in work if s[0] not in stats]
    else:
        missing = work

    total = len(missing)
    if total == 0:
        already = len(stats)
        print(f"\nAll {already} stat pages already in cache. Nothing to do.")
        print("Use --all to re-fetch everything.")
        return

    est_min = (total * DELAY) // 60
    print(f"\nFetching {total} stat pages (~{est_min} min at {DELAY}s delay)...")
    print(f"Output: pcs_stats.json\n")

    ok = skipped = failed = 0

    for i, (sid, label, path, cat, subcat, is_static, notes) in enumerate(missing, 1):
        url = f"{PCS}/{path}"
        print(f"[{i}/{total}] {label}", flush=True)
        print(f"  {url}", flush=True)

        html = fetch(url)
        if not html:
            print(f"  FAILED — will retry on next run", flush=True)
            failed += 1
            time.sleep(DELAY)
            continue

        parser = CUSTOM_PARSERS.get(sid, parse_stat_table)
        rows = parser(html, sid)

        # Extract page description from meta or h1
        desc_m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html)
        if not desc_m:
            desc_m = re.search(r'content=["\']([^"\']+)["\'][^>]*name=["\']description["\']', html)
        description = strip_tags(desc_m.group(1)) if desc_m else ""

        entry = {
            "label":       label,
            "category":    cat,
            "subcategory": subcat,
            "is_static":   is_static,
            "notes":       notes,
            "description": description,
            "url":         url,
            "fetched_at":  datetime.now(timezone.utc).isoformat(),
            "row_count":   len(rows),
            "rows":        rows,
        }

        stats[sid] = entry
        save_cache(cache)

        if rows:
            top = rows[0]
            print(f"  OK — {len(rows)} rows. Top: {top.get('name','?')} ({top.get('value') or list(top.values())[-1]})", flush=True)
            ok += 1
        else:
            print(f"  OK but no rows parsed (page may use non-standard format)", flush=True)
            skipped += 1

        if i < total:
            time.sleep(DELAY)

    print(f"\n{'='*52}")
    print(f"Done. {ok} fetched, {skipped} empty, {failed} failed.")
    if failed:
        print("Re-run to retry failures.")
    print(f"Total in cache: {len(stats)} stat pages")
    print(f"Output: pcs_stats.json")
    print("\nNext: git add pcs_stats.json scrape_pcs_stats.py && git commit -m \'data: PCS stats\' && git push")


if __name__ == "__main__":
    main()
