"""
UCI Race Calendar Scraper - CyclingFlash Edition
Fetches race data from cyclingflash.com and writes data.json
No JavaScript rendering required — CyclingFlash serves fully server-rendered HTML.

URL patterns:
  Race info:     /race/{slug}
  Stage result:  /race/{slug}/result/stage-{n}
  GC:            /race/{slug}/result/stage-{n}/gc
  Points:        /race/{slug}/result/stage-{n}/points
  Mountain:      /race/{slug}/result/stage-{n}/mountain
  Youth:         /race/{slug}/result/stage-{n}/youth

Run:  py scraper.py
"""

import json
import re
import sys
import time
import os
import urllib.parse
from datetime import datetime, date, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Force UTF-8 output so arrow/emoji characters don't crash on Windows cp1252 consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_URL = "https://cyclingflash.com"
OUTPUT_FILE = "data.json"
DELAY = 1.2          # seconds between requests
REQUEST_TIMEOUT = 20  # seconds

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# UCI categories to include (men's only)
UCI_CATS = {"1.UWT", "2.UWT", "1.Pro", "2.Pro", "1.1", "2.1"}
# Women's categories — explicitly excluded (belt-and-braces)
UCI_WOMEN_CATS = {"1.WWT", "2.WWT", "1.W", "2.W", "1.1W", "2.1W"}

# ── Team lists (WorldTeam + ProTeam only) ──────────────────────────────────────

MAX_NEW_RIDERS_PER_RUN = 50    # Max new rider profiles per run (incremental cache)

WORLD_TEAMS = [
    "alpecin-premier-tech-2026",
    "bahrain-victorious-2026",
    "decathlon-cma-cgm-team-2026",
    "ef-education-easypost-2026",
    "groupama-fdj-united-2026",
    "ineos-grenadiers-2026",
    "lidl-trek-2026",
    "lotto-intermarche-2026",
    "movistar-team-2026",
    "netcompany-ineos-cycling-team-2026",
    "nsn-cycling-team-2026",
    "red-bull-bora-hansgrohe-2026",
    "soudal-quick-step-2026",
    "team-jayco-alula-2026",
    "team-picnic-postnl-2026",
    "team-visma-lease-a-bike-2026",
    "uae-emirates-xrg-2026",
    "uno-x-mobility-2026",
    "xds-astana-team-2026",
]

PRO_TEAMS = [
    "bardiani-csf-7-saber-2026",
    "burgos-burpellet-bh-2026",
    "caja-rural-seguros-rga-2026",
    "cofidis-2026",
    "equipo-kern-pharma-2026",
    "euskaltel-euskadi-2026",
    "mbh-bank-csb-telecom-fort-2026",
    "modern-adventure-pro-cycling-2026",
    "pinarello-q36",
    "solution-tech-nippo-rali-2026",
    "team-flanders-baloise-2026",
    "team-novo-nordisk-2026",
    "team-polti-visitmalta-2026",
    "totalenergies-2026",
    "tudor-pro-cycling-team-2026",
    "unibet-rose-rockets-2026",
]

# Grand tours and major races to always track
ALWAYS_INCLUDE = {
    "tour-de-france-2026":        ("Tour de France", "1.UWT"),
    "giro-ditalia-2026":          ("Giro d'Italia", "1.UWT"),
    "vuelta-a-espana-2026":       ("Vuelta a España", "1.UWT"),
    "tour-de-suisse-2026":        ("Tour de Suisse", "1.UWT"),
}


# ── HTML utilities ─────────────────────────────────────────────────────────────

def strip_tags(s):
    """Remove HTML tags and decode common entities."""
    s = re.sub(r'<[^>]+>', ' ', s)
    s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
         .replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
    # Decode decimal entities &#39; and hex entities &#x27;
    s = re.sub(r'&#(\d+);',        lambda m: chr(int(m.group(1))),     s)
    s = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), s)
    return re.sub(r'\s+', ' ', s).strip()


def flag_emoji(code):
    if not code or len(code) != 2:
        return ""
    c = code.upper()
    try:
        return chr(0x1F1E6 + ord(c[0]) - 65) + chr(0x1F1E6 + ord(c[1]) - 65)
    except Exception:
        return ""


# ── HTTP fetch ─────────────────────────────────────────────────────────────────

def fetch(url, retries=3):
    short = url.replace("https://cyclingflash.com", "").replace("https://www.procyclingstats.com", "[PCS]")
    print(f"    GET {short}", flush=True)
    for attempt in range(retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                data = r.read().decode("utf-8", errors="replace")
                # Sanity-check: reject very short responses and obvious error pages
                if len(data) < 500:
                    print(f"        ✗ Response too short ({len(data)} chars) — likely error page", flush=True)
                    if attempt < retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return None
                lowered = data[:2000].lower()
                if any(sig in lowered for sig in ("404 not found", "page not found", "race not found",
                                                   "error occurred", "internal server error")):
                    print(f"        ✗ Error page detected ({len(data):,} chars) — skipping", flush=True)
                    return None
                print(f"        ✓ {len(data):,} chars", flush=True)
                return data
        except HTTPError as e:
            if e.code in (404, 410):
                print(f"        ✗ HTTP {e.code} (skipping)", flush=True)
                return None
            print(f"        ✗ HTTP {e.code} (attempt {attempt+1}/{retries})", flush=True)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except (URLError, OSError) as e:
            print(f"        ✗ {e} (attempt {attempt+1}/{retries})", flush=True)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    print(f"        ✗ All retries failed", flush=True)
    return None


def try_next_data(html):
    """
    Extract the __NEXT_DATA__ JSON from a Next.js page.
    Returns parsed dict or None.
    """
    m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
                  html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


# ── Date helpers ───────────────────────────────────────────────────────────────

def parse_date(s):
    """Parse '7 June 2026' or '7 Jun 2026' → 'YYYY-MM-DD'. Returns None on failure."""
    s = s.strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def classify_status(start_str, end_str):
    today = date.today()
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d").date()
        end   = datetime.strptime(end_str,   "%Y-%m-%d").date()
    except Exception:
        return "upcoming"
    if start > today:
        return "upcoming"
    if end < today:
        return "recent"
    return "live"


# ── Result-table parser (raw HTML) ─────────────────────────────────────────────

def parse_result_rows(html, max_rows=10):
    """
    Parse a CyclingFlash result/classification page (raw HTML) and return
    up to max_rows rider dicts: {rank, name, rider_url, team, nat_code, flag, time_gap}

    Handles the CyclingFlash HTML structure:
      <tr>
        <td>1</td><td>-</td>
        <td><a href=".../profile/SLUG"><img alt="XX flag">NAME</a>
            <a href=".../team/SLUG">TEAM</a></td>
        <td>TIME</td>
      </tr>
    """
    results = []
    prev_time = ""

    for row_m in re.finditer(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL):
        row_html = row_m.group(1)
        cells = [m.group(1) for m in re.finditer(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)]
        if len(cells) < 3:
            continue

        # Rank from first td
        rank_text = strip_tags(cells[0]).strip()
        try:
            rank = int(rank_text)
        except ValueError:
            continue
        if rank < 1 or rank > 999:
            continue

        # Find the td containing a /profile/ link
        rider_cell = next((c for c in cells if '/profile/' in c), None)
        if not rider_cell:
            continue

        # Nationality from flag image alt text: alt="AU flag"
        nat_m = re.search(r'alt=["\']([A-Z]{2}) flag["\']', rider_cell)
        nat_code = nat_m.group(1) if nat_m else ""

        # Rider name and slug from the profile <a> tag
        # The image is inside the link, so we need to extract text from: <a href="...">...IMG...NAME</a>
        name_m = re.search(
            r'href=["\']https://cyclingflash\.com/profile/([^"\']+)["\'][^>]*>(.*?)</a>',
            rider_cell, re.DOTALL
        )
        if not name_m:
            # Try relative URL
            name_m = re.search(
                r'href=["\']/profile/([^"\']+)["\'][^>]*>(.*?)</a>',
                rider_cell, re.DOTALL
            )
        if not name_m:
            continue

        rider_slug = name_m.group(1).strip()
        # Strip inner HTML (the flag img) to get just the name text
        name = strip_tags(name_m.group(2)).strip()
        if not name:
            continue

        # Team name from team link
        team_m = re.search(
            r'href=["\'](?:https://cyclingflash\.com)?/team/[^"\']+["\'][^>]*>([^<]+)',
            rider_cell
        )
        team = team_m.group(1).strip() if team_m else ""

        # Time from last cell text
        time_text = strip_tags(cells[-1]).strip()
        # CyclingFlash uses " (U+201C left double quotation mark) or plain "
        if time_text in ('"', '“', '”', '"'):
            time_gap = prev_time
        elif re.search(r'\d', time_text) and re.match(r'^[\d:+h"“”\s]+$', time_text):
            time_gap = time_text
            prev_time = time_text
        else:
            time_gap = ""

        results.append({
            "rank":      rank,
            "name":      name,
            "rider_url": f"/profile/{rider_slug}",
            "team":      team,
            "nat_code":  nat_code,
            "flag":      flag_emoji(nat_code),
            "time_gap":  time_gap,
        })

        if len(results) >= max_rows:
            break

    return results


# ── Race info parser (raw HTML) ────────────────────────────────────────────────

def parse_race_info(slug, html, debug=False):
    """
    Parse a CyclingFlash race info page and return metadata dict.
    """
    if debug:
        debug_path = f"debug_html_{slug}.txt"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"    [debug] HTML saved to {debug_path}", flush=True)

    info = {"slug": slug, "total_stages": 1}

    # Race name from og:title meta tag
    name_m = (
        re.search(r'property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html) or
        re.search(r'content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']', html)
    )
    if name_m:
        raw = strip_tags(name_m.group(1)).strip()
        # Strip " 2026 Men Elite" / " 2026 Women Elite" suffix
        name = re.sub(r'\s+20\d\d\s+(Men|Women)\s+.*$', '', raw).strip()
        info["name"] = name

    # Dates — Method 1: JSON-LD SportsEvent block (most reliable).
    # CyclingFlash embeds a <script type="application/ld+json"> with clean ISO dates.
    # The HTML date cells use <span> tags which break plain regex.
    start_date = ""
    end_date   = ""

    for ld_m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    ):
        try:
            ld = json.loads(ld_m.group(1))
            items = ld if isinstance(ld, list) else [ld]
            for item in items:
                if item.get("@type") == "SportsEvent":
                    sd = item.get("startDate", "")
                    ed = item.get("endDate",   "")
                    if sd:
                        start_date = sd[:10]   # "2026-06-07T00:00:00+00:00" → "2026-06-07"
                    if ed:
                        end_date = ed[:10]
                    break
        except Exception:
            pass
        if start_date:
            break

    # Fallback Method 2: span-aware HTML parsing (strip span tags, then match dates)
    if not start_date:
        MONTHS = (
            r'(?:January|February|March|April|May|June|July|August|'
            r'September|October|November|December|'
            r'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
        )
        # Extract Date row cell, strip tags, then pattern-match
        date_cell_m = re.search(
            r'<t[dh][^>]*>\s*Date\s*</t[dh]>\s*<t[dh][^>]*>(.*?)</t[dh]>',
            html, re.DOTALL | re.IGNORECASE
        )
        cell_text = strip_tags(date_cell_m.group(1)) if date_cell_m else html
        date_range_m = re.search(
            r'(\d{1,2}\s+' + MONTHS + r'\s+\d{4})\s*[-–—]\s*'
            r'(\d{1,2}\s+' + MONTHS + r'\s+\d{4})',
            cell_text
        )
        if date_range_m:
            start_date = parse_date(date_range_m.group(1)) or ""
            end_date   = parse_date(date_range_m.group(2)) or ""
        else:
            single_m = re.search(
                r'(\d{1,2}\s+' + MONTHS + r'\s+\d{4})',
                cell_text
            )
            if single_m:
                start_date = parse_date(single_m.group(1)) or ""
                end_date   = start_date

    info["start_date"] = start_date
    info["end_date"]   = end_date

    # Category — the cell is plain text so the simple pattern works
    cat_m = re.search(
        r'<t[dh][^>]*>\s*Category\s*</t[dh]>\s*<t[dh][^>]*>([^<]+)</t[dh]>',
        html, re.IGNORECASE
    )
    if cat_m:
        info["category"] = cat_m.group(1).strip()

    # Count stage links to determine total_stages
    stage_nums = re.findall(
        r'/race/' + re.escape(slug) + r'/stages/stage-(\d+)',
        html
    )
    if stage_nums:
        info["total_stages"] = max(int(n) for n in stage_nums)
    else:
        # Fallback: infer from date span when stage links aren't published yet.
        # A span > 1 day means it's a stage race; use (span - rest_days_estimate) as count.
        try:
            from datetime import datetime as _dt
            d1 = _dt.strptime(info.get("start_date", ""), "%Y-%m-%d")
            d2 = _dt.strptime(info.get("end_date", ""), "%Y-%m-%d")
            span = (d2 - d1).days + 1
            if span >= 4:
                # Subtract 1 rest day for races ≥7 days, 0 otherwise
                rest = 1 if span >= 7 else 0
                info["total_stages"] = span - rest
        except Exception:
            pass

    return info


# ── Scrape stage result ────────────────────────────────────────────────────────

def parse_ttt_rows(html, max_rows=10):
    """
    Parse a Team Time Trial result page where rows are teams not riders.
    CyclingFlash TTT table: Rank | Team (flag + name link) | Time
    Returns list of dicts with same shape as parse_result_rows but name=team name, is_ttt=True.
    """
    results = []
    prev_time = ""
    for row_m in re.finditer(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL):
        row_html = row_m.group(1)
        cells = [m.group(1) for m in re.finditer(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)]
        if len(cells) < 3:
            continue
        rank_text = strip_tags(cells[0]).strip()
        try:
            rank = int(rank_text)
        except ValueError:
            continue
        if rank < 1 or rank > 999:
            continue

        # Find cell with /team/ link
        team_cell = next((c for c in cells if '/team/' in c), None)
        if not team_cell:
            continue

        nat_m = re.search(r'alt=["\']([A-Z]{2}) flag["\']', team_cell)
        nat_code = nat_m.group(1) if nat_m else ""

        team_m = re.search(
            r'href=["\'](?:https://cyclingflash\.com)?/team/([^"\']+)["\'][^>]*>(.*?)</a>',
            team_cell, re.DOTALL
        )
        if not team_m:
            continue
        team_name = strip_tags(team_m.group(2)).strip()
        if not team_name:
            continue

        time_text = strip_tags(cells[-1]).strip()
        if time_text in ('"', '“', '”', '"'):
            time_gap = prev_time
        elif re.search(r'\d', time_text):
            time_gap = time_text
            prev_time = time_text
        else:
            time_gap = ""

        results.append({
            "rank":      rank,
            "name":      team_name,
            "rider_url": f"/team/{team_m.group(1)}",
            "team":      "",
            "nat_code":  nat_code,
            "flag":      flag_emoji(nat_code),
            "time_gap":  time_gap,
            "is_ttt":    True,
        })
        if len(results) >= max_rows:
            break
    return results



def validate_result_rows(rows, context="result", min_riders=3):
    """
    Returns (ok, reason) — ok=True means rows look trustworthy.
    Checks: minimum rider count, no empty names, no HTML artefacts in names.
    """
    if not rows:
        return False, "no rows returned"
    if len(rows) < min_riders:
        return False, f"only {len(rows)} rider(s) — expected ≥{min_riders}"
    for r in rows:
        name = r.get("name", "").strip()
        if not name:
            return False, "empty rider name in result"
        if any(c in name for c in ("<", ">", "&", "\n", "\t")):
            return False, f"HTML artefact in rider name: {name!r}"
        if len(name) > 60:
            return False, f"suspiciously long rider name: {name!r}"
    return True, "ok"


def scrape_stage(slug, stage_num):
    """Fetch a stage result page and return (top10_list, winner_dict, height_profile_img, route_img) or (None, None, None, None)."""
    if stage_num == 0:
        url = f"{BASE_URL}/race/{slug}/result"
    else:
        url = f"{BASE_URL}/race/{slug}/result/stage-{stage_num}"

    html = fetch(url)
    if not html:
        return None, None, None, None

    rows = parse_result_rows(html, max_rows=10)
    if not rows:
        # Try TTT parser (team time trial — teams not riders in result table)
        rows = parse_ttt_rows(html, max_rows=10)
    if not rows:
        return None, None, None, None

    ok, reason = validate_result_rows(rows, context=f"stage {stage_num}")
    if not ok:
        print(f"        ✗ Stage {stage_num} result failed validation: {reason}", flush=True)
        return None, None, None, None

    height_profile = _cdn_url(html, '___heightProfile')
    route_img      = _cdn_url(html, '___route_')

    return rows, rows[0], height_profile, route_img


# ── Scrape classification ──────────────────────────────────────────────────────

def scrape_classification(slug, stage_num, cls_type):
    """Fetch GC / points / mountain / youth classification after stage_num."""
    url = f"{BASE_URL}/race/{slug}/result/stage-{stage_num}/{cls_type}"
    html = fetch(url)
    if not html:
        return None
    rows = parse_result_rows(html, max_rows=10)
    if not rows:
        return None
    ok, reason = validate_result_rows(rows, context=f"classification/{cls_type}", min_riders=3)
    if not ok:
        print(f"        ✗ Classification {cls_type} failed validation: {reason}", flush=True)
        return None
    return rows



# ── Stage detail scraping ──────────────────────────────────────────────────────

def scrape_stage_details(slug, stage_num, year=None):
    """Fetch /race/{slug}/stages/stage-{n} and return a details dict, or None."""
    url = f"{BASE_URL}/race/{slug}/stages/stage-{stage_num}"
    html = fetch(url)
    if not html:
        return None

    # ── 1. Search full HTML for stage distance/type/towns ────────────────────
    # Pattern appears in meta description AND in body text, e.g.:
    # "140km individual road race stage from Vizille to Saint-Ismier"
    distance_km    = None
    stage_type_raw = ""
    start_town     = ""
    finish_town    = ""

    stage_info_m = re.search(
        r'(\d+(?:\.\d+)?)\s*km\s+([\w\s]+?)\s+(?:stage\s+)?from\s+([A-Z][^<\n]+?)\s+to\s+([A-Z][^<\n.,"]{2,40?})(?:[<."&#])',
        html, re.IGNORECASE
    )
    if stage_info_m:
        distance_km    = float(stage_info_m.group(1))
        stage_type_raw = stage_info_m.group(2).strip().lower()
        start_town     = stage_info_m.group(3).strip()
        finish_town    = stage_info_m.group(4).strip()

    # ── 2. Flexible table extraction (label within ~300 chars of a <td>) ──────
    def find_after_label(label):
        m = re.search(
            re.escape(label) + r'[\s\S]{0,300}?<td[^>]*>([\s\S]*?)</td>',
            html, re.IGNORECASE
        )
        return strip_tags(m.group(1)).strip() if m else ""

    date_str   = find_after_label("Date")
    elev_str   = find_after_label("Elevation gain") or find_after_label("Elevation")
    start_time = find_after_label("Start time") or find_after_label("Start Time")
    type_raw   = find_after_label("Type")

    # Fallback distance from table "Distance" label
    if distance_km is None:
        dist_str = find_after_label("Distance")
        if dist_str:
            dm = re.search(r'(\d+(?:\.\d+)?)', dist_str)
            if dm:
                distance_km = float(dm.group(1))

    if not start_town:
        raw = find_after_label("Start")
        start_town = re.sub(r'https?://\S+', '', raw).strip()
    if not finish_town:
        raw = find_after_label("Finish")
        finish_town = re.sub(r'https?://\S+', '', raw).strip()

    # ── 3. Parse elevation ────────────────────────────────────────────────────
    elevation_m = None
    if elev_str:
        ev = re.search(r'([\d,]+)', elev_str)
        if ev:
            elevation_m = int(ev.group(1).replace(",", ""))
    if not elevation_m:
        ev = re.search(r'(?:elevation|gain)[^\d]{0,40}(\d[\d,]+)\s*m', html, re.IGNORECASE)
        if ev:
            elevation_m = int(ev.group(1).replace(",", ""))

    # ── 4. Stage type classification (with PCS fallback for elevation) ─────────
    type_combined = (type_raw + " " + stage_type_raw).lower()
    pcs_parcours = None
    if not elevation_m and year and "time trial" not in type_combined:
        pcs_elev, pcs_parcours = fetch_pcs_elevation(slug, stage_num, year)
        if pcs_elev:
            elevation_m = pcs_elev
            print(f"          [PCS] stage {stage_num}: {elevation_m}m", flush=True)
    stage_type = classify_stage_type(type_combined, elevation_m, pcs_parcours)

    # ── 5. Description paragraphs ─────────────────────────────────────────────
    body = re.sub(r'<(script|style|nav|header|footer)[^>]*>[\s\S]*?</\1>', '', html, flags=re.IGNORECASE)
    paras = re.findall(r'<p[^>]*>([\s\S]*?)</p>', body, re.DOTALL)
    description_parts = []
    for p in paras:
        text = strip_tags(p).strip()
        if (len(text) > 80
                and re.search(r'\b(km|stage|climb|col|c[oô]te|riders?|race|mountain|sprint|finish|start|ascent)\b', text, re.IGNORECASE)
                and not re.match(r'^(Home|Today|Calendar|Teams|Rankings|News|Results|Startlist|Classification|More|CET)\b', text, re.IGNORECASE)):
            description_parts.append(text)
    description = " ".join(description_parts[:3])

    # ── 6. Height profile image ───────────────────────────────────────────────
    height_profile_img = _cdn_url(html, '___heightProfile')

    details = {
        "date_str":    date_str,
        "start_town":  start_town,
        "finish_town": finish_town,
        "distance_km": distance_km,
        "elevation_m": elevation_m,
        "start_time":  start_time,
        "stage_type":  stage_type,
        "description": description,
    }
    if height_profile_img:
        details["height_profile_img"] = height_profile_img
    return details


# ── ProCyclingStats fallback for elevation ─────────────────────────────────────
PCS_BASE = "https://www.procyclingstats.com"

# Maps cyclingflash slug (without year) → procyclingstats slug
PCS_SLUG_MAP = {
    "vuelta-a-espana":              "vuelta-a-espana",
    "tour-de-france":               "tour-de-france",
    "giro-ditalia":                 "giro-d-italia",
    "tour-de-suisse":               "tour-de-suisse",
    "postnord-tour-of-denmark":     "tour-of-denmark",
    "critarium-du-dauphine":        "criterium-du-dauphine",
    "paris-nice":                   "paris-nice",
    "tirreno-adriatico":            "tirreno-adriatico",
    "volta-a-catalunya":            "volta-a-catalunya",
    "tour-of-the-basque-country":   "itzulia-basque-country",
    "tour-de-romandie":             "tour-de-romandie",
    "tour-de-wallonie":             "tour-de-wallonie",
    "tour-de-pologne":              "tour-de-pologne",
    "benelux-tour":                 "benelux-tour",
    "tour-of-britain":              "tour-of-britain",
    "vuelta-burgos":                "vuelta-a-burgos",
}

def _pcs_slug(cf_slug):
    """Convert a cyclingflash race slug (may include year) to a PCS slug."""
    base = re.sub(r'-20\d{2}$', '', cf_slug)
    return PCS_SLUG_MAP.get(base, base)


def fetch_pcs_elevation(cf_slug, stage_num, year):
    """
    Fallback: fetch vertical meters from procyclingstats.com.
    Returns (elevation_m, parcours_str) or (None, None).
    """
    pcs_slug = _pcs_slug(cf_slug)
    url = f"{PCS_BASE}/race/{pcs_slug}/{year}/stage-{stage_num}"
    html = fetch(url)
    if not html:
        return None, None
    vm_m = re.search(
        r'Vertical meters[\s\S]{0,300}?<div[^>]*>([\d,]+)</div>',
        html, re.IGNORECASE
    )
    elevation_m = int(vm_m.group(1).replace(',', '')) if vm_m else None
    pt_m = re.search(r'parcours[_-]type[^"]*"[^>]*>\s*<img[^>]+alt="([^"]+)"', html, re.IGNORECASE)
    parcours = pt_m.group(1).lower() if pt_m else None
    return elevation_m, parcours


def classify_stage_type(type_combined, elevation_m, parcours=None):
    """Central stage type classifier."""
    if "team time trial" in type_combined:
        return "TTT"
    if "time trial" in type_combined or "individual time trial" in type_combined:
        return "ITT"
    if parcours:
        if "mountain" in parcours and "medium" not in parcours:
            return "mountain"
        if "medium" in parcours:
            return "medium_mountain"
        if "hilly" in parcours or "semi" in parcours or "uphill" in parcours:
            return "hilly"
        if "flat" in parcours:
            return "flat"
    if elevation_m:
        if elevation_m > 2500:
            return "mountain"
        if elevation_m > 1000:
            return "hilly"
        return "flat"
    return "flat"

SKIP_SLUG = re.compile(r'-(we|wj|wu|mu|mj|ju)-|(-we|-wj|-wu|-mu|-mj|-ju)$')


def _slugs_from_html(html):
    """Extract unique men's race slugs from any CyclingFlash HTML page."""
    raw = re.findall(
        r'/race/([a-z0-9-]+-20\d\d)(?:/|["\' <])', html
    )
    seen = {}
    for s in raw:
        if not SKIP_SLUG.search(s) and s not in seen:
            seen[s] = True
    return list(seen)


def discover_races_from_calendar():
    """
    Scrape the structured CyclingFlash calendar pages for the current year.
    Returns {slug: {'status': 'unknown', 'last_stage': None}}
    — status is resolved later from race dates.
    """
    year = datetime.now().year
    sources = [
        f"{BASE_URL}/calendar/road/{year}/UCI%20World%20Tour",
        f"{BASE_URL}/calendar/road/{year}/UCI%20ProSeries",
        f"{BASE_URL}/calendar/road/{year}/Men%20Elite",
    ]
    found = {}
    for url in sources:
        html = fetch(url)
        time.sleep(DELAY)
        if not html:
            print(f"    [calendar] Could not fetch {url}", flush=True)
            continue
        slugs = _slugs_from_html(html)
        new = [s for s in slugs if s not in found]
        for s in new:
            found[s] = {"status": "unknown", "last_stage": None}
        print(f"    [calendar] {url.split('/')[-1]}: {len(slugs)} slugs ({len(new)} new)", flush=True)
    return found


def discover_races_from_homepage():
    """
    Parse the CyclingFlash homepage for any live/current races not on the calendar.
    Returns {slug: {'status': 'unknown', 'last_stage': int|None}}
    """
    html = fetch(BASE_URL + "/")
    if not html:
        return {}
    found = {}
    for m in re.finditer(
        r'/race/([a-z0-9-]+-20\d\d)(?:/result(?:/stage-(\d+))?(?:/[a-z]+)?|/startlist)["\']',
        html
    ):
        slug, stage = m.group(1), m.group(2)
        if SKIP_SLUG.search(slug):
            continue
        s = int(stage) if stage else None
        if slug not in found:
            found[slug] = {"status": "unknown", "last_stage": s}
    return found


# ── Team scraping ──────────────────────────────────────────────────────────────

def _cdn_url(html, keyword):
    """Extract a CDN image URL from a Next.js _next/image url= param by keyword."""
    m = re.search(r'url=([^&"\']+' + keyword + r'[^&"\']*)', html)
    if not m:
        return None
    return urllib.parse.unquote(m.group(1))


def scrape_team(slug, cat):
    """Fetch a CyclingFlash team page and return a team dict."""
    html = fetch(f"{BASE_URL}/team/{slug}")
    if not html:
        return None

    # Team name
    name_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    name = strip_tags(name_m.group(1)) if name_m else slug.replace('-2026','').replace('-',' ').title()

    # Logo and jersey via CDN URL extraction
    logo   = _cdn_url(html, 'logo_600_600')
    jersey = _cdn_url(html, 'shirt_600_600')

    # Rider rows from the roster table
    tr_blocks  = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    rider_rows = [t for t in tr_blocks if '/profile/' in t]
    riders = []
    for row in rider_rows:
        slug_m = re.search(r'/profile/([a-z0-9-]+)', row)
        name_s = re.search(r'<span>([^<]+)</span>', row)
        flag_m = re.search(r'/svg/flags/(\w+)\.svg', row)
        tds    = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        age    = strip_tags(tds[-1]) if tds else ''
        if slug_m and name_s:
            riders.append({
                'slug': slug_m.group(1),
                'name': name_s.group(1),
                'nat':  flag_m.group(1).lower() if flag_m else '',
                'age':  age,
            })

    return {'slug': slug, 'name': name, 'logo': logo, 'jersey': jersey,
            'cat': cat, 'riders': riders}


def scrape_rider_profile(slug):
    """
    Fetch a rider's photo/DOB/nationality from JSON-LD on their profile page,
    and their career wins from /profile/{slug}/wins.
    Returns a dict or None on failure.
    """
    base = f"{BASE_URL}/profile/{slug}"

    # 1. Profile page → JSON-LD Person block
    html = fetch(base)
    time.sleep(DELAY)
    if not html:
        return None

    photo = dob = nat = None
    for ld_m in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            ld = json.loads(ld_m.group(1))
            if isinstance(ld, dict) and ld.get('@type') == 'Person':
                photo = ld.get('image', {}).get('url')
                dob   = ld.get('birthDate')
                nat   = (ld.get('nationality') or {}).get('name')
                break
        except Exception:
            pass

    # Fallback: og:image meta tag if JSON-LD photo is missing
    if not photo:
        og_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
        if not og_m:
            og_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
        if og_m:
            photo = og_m.group(1)

    # 2. Wins page → palmares table
    wins_html = fetch(f"{base}/wins")
    time.sleep(DELAY)
    wins = []
    if wins_html:
        tr_blocks  = re.findall(r'<tr[^>]*>(.*?)</tr>', wins_html, re.DOTALL)
        race_rows  = [t for t in tr_blocks if '/race/' in t]
        for row in race_rows:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(tds) >= 4:
                wins.append({
                    'year': strip_tags(tds[1]),
                    'date': strip_tags(tds[2]),
                    'race': strip_tags(tds[3]),
                    'cat':  strip_tags(tds[4]) if len(tds) > 4 else '',
                })

    # 3. PCS rider page -> specialty scores (GC, One day, Sprint, TT, Climber, Hills)
    specialties = {}
    pcs_html = fetch(f"{PCS_BASE}/rider/{slug}")
    time.sleep(DELAY)
    if pcs_html:
        pps_m = re.search(r'<ul[^>]+class="pps[^"]*"[^>]*>(.*?)</ul>', pcs_html, re.DOTALL)
        if pps_m:
            pps_block = pps_m.group(1)
            for li_m in re.finditer(r'<li[^>]*>(.*?)</li>', pps_block, re.DOTALL):
                li = li_m.group(1)
                score_m = re.search(r'class="xvalue[^"]*"\s*>(\d+)<', li)
                cat_m   = re.search(r'(?:career-points-|/results/)(one-day-races|gc|time-trial|sprint|climbers?|hills)', li)
                bar_m   = re.search(r'class="w(\d+)\s', li)
                if score_m and cat_m:
                    key = cat_m.group(1)
                    specialties[key] = {
                        'score': int(score_m.group(1)),
                        'bar':   int(bar_m.group(1)) if bar_m else 0,
                    }

    return {
        'slug':         slug,
        'photo':        photo,
        'dob':          dob,
        'nat':          nat,
        'wins':         wins,
        'specialties':  specialties,
        'fetched_at':   datetime.now(timezone.utc).isoformat(),
    }



def scrape_startlist(cf_slug, year):
    """
    Fetch the PCS startlist for a race. Returns list of {name, slug, nat, team} dicts.
    Returns [] if not available.

    PCS startlist page structure (2025+):
      <div class="ridersCont">
        <div>...<a class="team" href="team/SLUG">TEAM NAME</a>...</div>
        <ul>
          <li><span class="bib">1</span><span class="flag si"></span>
              <a href="rider/tadej-pogacar">POGAČAR Tadej</a></li>
          ...
        </ul>
      </div>
    """
    pcs_slug = _pcs_slug(cf_slug)
    url = f"{PCS_BASE}/race/{pcs_slug}/{year}/startlist"
    html = fetch(url)
    if not html:
        return []

    entries = []
    seen = set()

    # Split on each ridersCont block (one per team)
    blocks = re.split(r'<div[^>]+class="ridersCont"', html)

    for block in blocks[1:]:
        # Team name from <a class="team" ...>TEAM NAME</a>
        team_m = re.search(r'class="team"[^>]*>([^<]+)</a>', block)
        team_name = re.sub(r'\s+', ' ', team_m.group(1)).strip() if team_m else ''

        # Each rider: <span class="flag XX"></span><a href="rider/SLUG">NAME</a>
        for nat, slug_r, name in re.findall(
            r'class="flag (\w+)"></span>\s*<a href="rider/([^"]+)">([^<]+)</a>',
            block
        ):
            name = name.strip()
            # PCS stores names as "SURNAME Firstname" — convert to "Firstname Surname" title case
            # to match CyclingFlash result names used for scoring.
            parts = name.split()
            if parts and parts[0].isupper() and len(parts) > 1:
                name = ' '.join(parts[1:] + [parts[0].title()])
            if name and name not in seen:
                seen.add(name)
                entries.append({
                    'name': name,
                    'slug': slug_r,
                    'nat':  nat.lower(),
                    'team': team_name,
                })

    if not entries:
        # Fallback: any rider link on the page (no nat info)
        for slug_r, name in re.findall(r'href="rider/([a-z0-9-]+)">([^<]+)</a>', html):
            name = name.strip()
            if name and name not in seen and len(name) > 3:
                seen.add(name)
                entries.append({'name': name, 'slug': slug_r, 'nat': '', 'team': ''})

    return entries


def scrape_teams():
    """Scrape all WorldTeam and ProTeam pages. Returns list of team dicts."""
    teams = []
    pairs = [(s, 'UWT') for s in WORLD_TEAMS] + [(s, 'Pro') for s in PRO_TEAMS]
    for slug, cat in pairs:
        print(f"  {slug}", flush=True)
        team = scrape_team(slug, cat)
        time.sleep(DELAY)
        if team:
            print(f"    {team['name']} — {len(team['riders'])} riders", flush=True)
            teams.append(team)
        else:
            print(f"    [skip] fetch failed", flush=True)
    return teams



# ── Results-only mode ──────────────────────────────────────────────────────────

def refresh_winner_wins(rider_profiles, winner_slugs):
    """
    Fetch only the /wins page for today's stage winners and update their
    career wins list in rider_profiles.  ~1 request per unique winner.
    Called at end of main_results_only() when new stages were found.
    """
    if not winner_slugs:
        return
    print(f"\n  [winners] Refreshing wins for {len(winner_slugs)} stage winner(s):", flush=True)
    for slug in winner_slugs:
        wins_html = fetch(f"{BASE_URL}/profile/{slug}/wins")
        time.sleep(DELAY)
        if not wins_html:
            print(f"    {slug}: wins page fetch failed", flush=True)
            continue
        wins = []
        tr_blocks = re.findall(r'<tr[^>]*>(.*?)</tr>', wins_html, re.DOTALL)
        race_rows = [t for t in tr_blocks if '/race/' in t]
        for row in race_rows:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(tds) >= 4:
                wins.append({
                    'year': strip_tags(tds[1]),
                    'date': strip_tags(tds[2]),
                    'race': strip_tags(tds[3]),
                    'cat':  strip_tags(tds[4]) if len(tds) > 4 else '',
                })
        if slug not in rider_profiles:
            rider_profiles[slug] = {'slug': slug}
        rider_profiles[slug]['wins'] = wins
        rider_profiles[slug]['wins_refreshed_at'] = datetime.now(timezone.utc).isoformat()
        print(f"    {slug}: {len(wins)} wins", flush=True)


def main_results_only():
    """
    Lightweight daily update: load cache, fix status buckets, fetch only
    missing stage results + classifications for live races.
    After fetching new results, refreshes wins for today's stage winners only.
    Skips calendar discovery, team scraping, full rider profiles, startlists.
    Run via:  py scraper.py --results-only
    """
    now_human = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nUCI Scraper — RESULTS ONLY — {now_human}", flush=True)
    print("=" * 60, flush=True)

    if not os.path.exists(OUTPUT_FILE):
        print("  No data.json found — run a full scrape first.", flush=True)
        return

    with open(OUTPUT_FILE, encoding="utf-8") as f:
        d = json.load(f)
    print(f"  Cache: {len(d.get('live',[]))} live | {len(d.get('upcoming',[]))} upcoming | {len(d.get('recent',[]))} recent", flush=True)

    today = date.today()

    # Promote upcoming → live
    still_upcoming = []
    for r in d.get("upcoming", []):
        sd, ed = r.get("start_date"), r.get("end_date")
        if sd and ed and date.fromisoformat(sd) <= today <= date.fromisoformat(ed):
            r["status"] = "live"
            if r["name"] not in {x["name"] for x in d.get("live", [])}:
                d.setdefault("live", []).append(r)
                print(f"  → Live: {r['name']}", flush=True)
        else:
            still_upcoming.append(r)
    d["upcoming"] = still_upcoming

    # Demote live → recent
    still_live = []
    for r in d.get("live", []):
        ed = r.get("end_date")
        if ed and date.fromisoformat(ed) < today:
            r["status"] = "recent"
            d.setdefault("recent", []).insert(0, r)
            print(f"  → Recent: {r['name']}", flush=True)
        else:
            still_live.append(r)
    d["live"] = still_live

    # Fetch missing results for live races only
    stages_updated   = 0
    new_winner_slugs = set()   # rider slugs who won a NEW (uncached) stage this run
    for race in d["live"]:
        slug   = race.get("cf_slug") or f"{race.get('slug','')}-{race.get('year','2026')}"
        name   = race.get("name", slug)
        stages = race.get("stages", [])
        total  = race.get("total_stages", len(stages))
        print(f"\n  {name}", flush=True)

        # Find which stages are done (use cache first, probe for new ones)
        completed_nums = []
        for n in range(1, total + 1):
            cached = next((s for s in stages if s.get("num") == n), None)
            if cached and cached.get("top10"):
                completed_nums.append(n)
                continue
            html = fetch(f"{BASE_URL}/race/{slug}/result/stage-{n}")
            time.sleep(DELAY)
            if html and re.search(r'<td[^>]*>\s*1\s*</td>', html):
                completed_nums.append(n)
            elif completed_nums:
                break  # gap = not yet run

        print(f"    Completed: {completed_nums}", flush=True)

        for n in completed_nums:
            stage_obj = next((s for s in stages if s.get("num") == n), None)
            if stage_obj is None:
                stage_obj = {"num": n, "label": f"Stage {n}",
                             "result_url": f"/race/{slug}/result/stage-{n}",
                             "winner": None, "winner_flag": "", "winner_nat": "", "top10": []}
                stages.append(stage_obj)

            if stage_obj.get("top10"):
                print(f"      Stage {n}: cached ({stage_obj.get('winner','?')})", flush=True)
                continue

            rows, winner, hpi, _ = scrape_stage(slug, n)
            time.sleep(DELAY)
            if winner:
                stage_obj["winner"]           = winner["name"]
                stage_obj["winner_flag"]      = winner.get("flag", "")
                stage_obj["winner_nat"]       = winner.get("nat_code", "")
                stage_obj["top10"]            = rows or []
                if hpi and not stage_obj.get("height_profile_img"):
                    stage_obj["height_profile_img"] = hpi
                stages_updated += 1
                win_slug = winner.get("rider_url", "").replace("/profile/", "").strip("/")
                if win_slug:
                    new_winner_slugs.add(win_slug)
                print(f"      Stage {n}: {winner['name']}", flush=True)
            else:
                print(f"      Stage {n}: no result yet", flush=True)

        race["stages"] = sorted(stages, key=lambda s: s.get("num", 0))
        done = [s for s in race["stages"] if s.get("winner")]
        if done:
            last = done[-1]
            race["last_stage_winner"]      = last["winner"]
            race["last_stage_winner_flag"] = last.get("winner_flag", "")
            race["last_stage_num"]         = last["num"]

        # Update classifications after latest completed stage
        if completed_nums:
            last_n = completed_nums[-1]
            for cls_key, (lk, tk) in {"gc": ("gc_leader","gc_top10"),
                                        "points": ("points_leader","points_top10"),
                                        "mountain": ("kom_leader","kom_top10"),
                                        "youth": ("youth_leader","youth_top10")}.items():
                rows = scrape_classification(slug, last_n, cls_key)
                time.sleep(DELAY)
                if rows:
                    race[lk] = f"{rows[0]['flag']} {rows[0]['name']}"
                    race[tk] = rows
                    print(f"      {cls_key}: {rows[0]['name']}", flush=True)

    # ── Refresh wins for today's stage winners only ───────────────────────────
    if new_winner_slugs:
        refresh_winner_wins(d.setdefault("rider_profiles", {}), new_winner_slugs)

    # ── Write output with backup + post-write validation ────────────────────────
    now = datetime.now(timezone.utc)
    d["scraped_at"]       = now.isoformat()
    d["scraped_at_human"] = now.strftime("%d %b %Y %H:%M UTC")

    # Snapshot pre-write size for regression check
    pre_write_size = os.path.getsize(OUTPUT_FILE) if os.path.exists(OUTPUT_FILE) else 0
    backup_file    = OUTPUT_FILE + ".bak"

    # Keep a backup of the last known-good file
    if os.path.exists(OUTPUT_FILE):
        import shutil as _shutil
        _shutil.copy2(OUTPUT_FILE, backup_file)

    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUTPUT_FILE)

    # ── Post-write validation ─────────────────────────────────────────────────
    write_ok = True
    fail_reason = ""

    # 1. JSON round-trip
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            d_check = json.load(f)
    except Exception as e:
        write_ok, fail_reason = False, f"JSON parse failed after write: {e}"

    if write_ok:
        # 2. Required top-level keys present
        for key in ("live", "upcoming", "recent", "scraped_at"):
            if key not in d_check:
                write_ok, fail_reason = False, f"missing key '{key}' in written file"
                break

    if write_ok:
        # 3. File did not shrink by more than 10%
        new_size = os.path.getsize(OUTPUT_FILE)
        if pre_write_size > 0 and new_size < pre_write_size * 0.90:
            write_ok, fail_reason = False, (
                f"file shrank by {(pre_write_size - new_size) // 1024} KB "
                f"({pre_write_size // 1024} KB → {new_size // 1024} KB) — possible truncation"
            )

    if write_ok:
        # 4. Each live race still has a name and slug
        for race in d_check.get("live", []):
            if not race.get("name") or not (race.get("slug") or race.get("cf_slug")):
                write_ok, fail_reason = False, f"live race missing name/slug: {race.get('name','?')}"
                break

    if not write_ok:
        print(f"\n✗ POST-WRITE VALIDATION FAILED: {fail_reason}", flush=True)
        if os.path.exists(backup_file):
            os.replace(backup_file, OUTPUT_FILE)
            print(f"  Restored backup ({os.path.getsize(OUTPUT_FILE) // 1024} KB)", flush=True)
        raise RuntimeError(f"data.json validation failed: {fail_reason}")

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\n✓ data.json written ({size_kb} KB) — {stages_updated} stages updated", flush=True)
    print(f"  Live: {len(d['live'])} | Upcoming: {len(d['upcoming'])} | Recent: {len(d.get('recent',[]))}", flush=True)
    if os.path.exists(backup_file):
        os.remove(backup_file)

    print("\n[push] Checking notification triggers...", flush=True)
    send_push_notifications(d)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    now_human = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nUCI Scraper (CyclingFlash) — {now_human}", flush=True)
    print("=" * 60, flush=True)

    # Load existing cache for stage data we don't need to re-fetch
    cache = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                cache = json.load(f)
            print(f"  Cache: {OUTPUT_FILE} loaded", flush=True)
        except Exception as e:
            print(f"  Cache: could not load ({e})", flush=True)

    cache_by_slug = {
        r["cf_slug"]: r
        for r in cache.get("live", []) + cache.get("recent", []) + cache.get("upcoming", [])
        if "cf_slug" in r
    }

    # ── 1. Discover races ─────────────────────────────────────────────────────
    print("\n[1/4] Discovering races...", flush=True)

    # Primary: structured calendar pages (full season)
    print("  Scraping calendar pages...", flush=True)
    discovered = discover_races_from_calendar()

    # Supplement with homepage (catches live races not yet on calendar)
    print("  Supplementing with homepage...", flush=True)
    for slug, info in discover_races_from_homepage().items():
        if slug not in discovered:
            discovered[slug] = info

    # Ensure mandatory races are always included
    for slug in ALWAYS_INCLUDE:
        if slug not in discovered:
            discovered[slug] = {"status": "unknown", "last_stage": None}

    print(f"  Found {len(discovered)} candidate races", flush=True)

    # ── 2. Fetch race details ─────────────────────────────────────────────────
    print("\n[2/4] Fetching race details...", flush=True)

    live_races     = []
    upcoming_races = []
    recent_races   = []
    stage_winners_to_refresh = set()  # Stage winners from freshly scraped (non-cached) results

    for slug, disc in discovered.items():
        print(f"\n  → {slug}", flush=True)

        # Fetch race info page
        info_html = fetch(f"{BASE_URL}/race/{slug}")
        time.sleep(DELAY)
        if not info_html:
            print("    [skip] Could not fetch race info", flush=True)
            continue

        # Enable debug for first qualifying race to inspect raw HTML
        debug_this = slug == "tour-auvergne-rhone-alpes-2026"
        info = parse_race_info(slug, info_html, debug=debug_this)

        # Override name/category for known big races if not parsed
        if slug in ALWAYS_INCLUDE and not info.get("name"):
            info["name"], info["category"] = ALWAYS_INCLUDE[slug]

        if not info.get("name"):
            print("    [skip] Could not parse race name", flush=True)
            continue

        # Skip cancelled races (CyclingFlash prefixes name with "CANCELLED:")
        if info["name"].upper().startswith("CANCELLED"):
            print(f"    [skip] Cancelled race", flush=True)
            continue

        # Filter by category
        cat = info.get("category", "")
        if slug not in ALWAYS_INCLUDE and not any(cat.startswith(c) for c in UCI_CATS):
            print(f"    [skip] Category {cat!r} not in target list", flush=True)
            continue

        # Skip women's races (category + name-based double check)
        if cat in UCI_WOMEN_CATS or any(cat.startswith(c) for c in UCI_WOMEN_CATS):
            print(f"    [skip] Women's category {cat!r}", flush=True)
            continue
        name_lc = info.get("name", "").lower()
        if any(w in name_lc for w in ("women", "ladies", "femmes", "dames", "féminin")):
            print(f"    [skip] Women's race", flush=True)
            continue

        start_date   = info.get("start_date", "")
        end_date     = info.get("end_date", "")
        total_stages = info.get("total_stages", 1)
        name         = info.get("name", slug)
        category     = cat

        # Determine status from actual dates (more reliable than homepage hints)
        status = classify_status(start_date, end_date)

        year_m = re.search(r'-(20\d\d)$', slug)
        year   = year_m.group(1) if year_m else ""

        print(f"    {name} | {category} | {total_stages} stages | {status}", flush=True)

        race_obj = {
            "slug":         re.sub(r'-20\d\d$', '', slug),   # short slug for compat
            "cf_slug":      slug,                              # full CyclingFlash slug
            "name":         name,
            "year":         year,
            "category":     category,
            "status":       status,
            "start_date":   start_date,
            "end_date":     end_date,
            "total_stages": total_stages,
            "official_url": f"https://cyclingflash.com/race/{slug}",
        }

        # ── Upcoming single-day: no results to fetch ─────────────────────────
        if status == "upcoming" and total_stages <= 1:
            upcoming_races.append(race_obj)
            continue

        # ── Single-day race ──────────────────────────────────────────────────
        if total_stages <= 1:
            rows, winner, height_profile, route_img = scrape_stage(slug, 0)
            time.sleep(DELAY)
            if winner:
                race_obj["winner"]             = winner["name"]
                race_obj["winner_flag"]        = winner["flag"]
                race_obj["winner_nat"]         = winner["nat_code"]
                race_obj["top10"]              = rows or []
                race_obj["height_profile_img"] = height_profile
                race_obj["route_img"]          = route_img
                win_slug = winner.get("rider_url", "").replace("/profile/", "").strip("/")
                if win_slug:
                    stage_winners_to_refresh.add(win_slug)
            (live_races if status == "live" else recent_races).append(race_obj)
            continue

        # ── Multi-stage: find completed stages ───────────────────────────────
        print(f"    Finding completed stages (probing 1-{total_stages})...", flush=True)
        cached_race   = cache_by_slug.get(slug)
        cached_stages_results = {s["num"]: s for s in (cached_race or {}).get("stages", []) if s.get("top10")}
        cached_stages_details = {s["num"]: s for s in (cached_race or {}).get("stages", []) if s.get("distance_km")}

        completed_nums = []
        for n in range(1, total_stages + 1):
            # If we have a cached result with top10 for this stage, count it as done
            if n in cached_stages_results:
                completed_nums.append(n)
                continue
            url = f"{BASE_URL}/race/{slug}/result/stage-{n}"
            html = fetch(url)
            time.sleep(DELAY)
            if html and re.search(r'<td[^>]*>\s*1\s*</td>', html):
                completed_nums.append(n)
            else:
                if completed_nums:
                    break  # First gap after results = not yet run

        print(f"    Completed: {completed_nums}", flush=True)
        race_obj["stages_completed"] = len(completed_nums)

        # Build stages list
        stages = []
        for n in range(1, total_stages + 1):
            has_details = n in cached_stages_details

            if n in completed_nums:
                if n in cached_stages_results:
                    stage_obj = dict(cached_stages_results[n])
                    w = stage_obj.get("winner", "cached")
                    print(f"      Stage {n}: cached ({w})", flush=True)
                else:
                    rows, winner, height_profile, route_img = scrape_stage(slug, n)
                    time.sleep(DELAY)
                    stage_obj = {
                        "num":              n,
                        "label":            f"Stage {n}",
                        "result_url":       f"/race/{slug}/result/stage-{n}",
                        "winner":           winner["name"] if winner else None,
                        "winner_flag":      winner["flag"] if winner else "",
                        "winner_nat":       winner["nat_code"] if winner else "",
                        "top10":            rows or [],
                        "height_profile_img": height_profile,
                        "route_img":        route_img,
                    }
                    if winner:
                        win_slug = winner.get("rider_url", "").replace("/profile/", "").strip("/")
                        if win_slug:
                            stage_winners_to_refresh.add(win_slug)
                    print(f"      Stage {n}: {winner['name'] if winner else 'no data'}", flush=True)
            else:
                # Upcoming stage — start from cached details or blank placeholder
                if has_details:
                    stage_obj = dict(cached_stages_details[n])
                    stage_obj.setdefault("top10", [])
                    print(f"      Stage {n}: upcoming (details cached)", flush=True)
                else:
                    stage_obj = {
                        "num": n, "label": f"Stage {n}",
                        "result_url": f"/race/{slug}/result/stage-{n}",
                        "winner": None, "winner_flag": "", "winner_nat": "",
                        "top10": [],
                    }

            # Fetch stage details (date, distance, elevation, type, description) if not cached
            if not has_details:
                details = scrape_stage_details(slug, n, year=year)
                time.sleep(DELAY)
                if details:
                    # Don't overwrite existing height_profile_img from result page
                    if stage_obj.get("height_profile_img"):
                        details.pop("height_profile_img", None)
                    stage_obj.update(details)
                    print(f"        Stage {n} details: {details.get('distance_km','?')}km {details.get('stage_type','?')}", flush=True)

            stages.append(stage_obj)

        race_obj["stages"] = stages

        done_stages = [s for s in stages if s.get("winner")]
        if done_stages:
            last = done_stages[-1]
            race_obj["last_stage_winner"]      = last["winner"]
            race_obj["last_stage_winner_flag"]  = last["winner_flag"]
            race_obj["last_stage_num"]          = last["num"]

        # ── Classifications ───────────────────────────────────────────────────
        if completed_nums:
            last_n = completed_nums[-1]
            print(f"    Classifications after stage {last_n}...", flush=True)
            cls_map = {
                "gc":       ("gc_leader",     "gc_top10"),
                "points":   ("points_leader", "points_top10"),
                "mountain": ("kom_leader",    "kom_top10"),
                "youth":    ("youth_leader",  "youth_top10"),
            }
            for cls_key, (leader_key, top10_key) in cls_map.items():
                rows = scrape_classification(slug, last_n, cls_key)
                time.sleep(DELAY)
                if rows:
                    leader = rows[0]
                    race_obj[leader_key] = f"{leader['flag']} {leader['name']}"
                    race_obj[top10_key]  = rows
                    print(f"      {cls_key}: {leader['name']}", flush=True)
                else:
                    print(f"      {cls_key}: no data", flush=True)

        if status == "upcoming":
            upcoming_races.append(race_obj)
        elif status == "live":
            live_races.append(race_obj)
        else:
            recent_races.append(race_obj)

    # ── 3. Scrape teams ───────────────────────────────────────────────────────
    print("\n[3/4] Scraping teams (WorldTeam + ProTeam)...", flush=True)
    teams_data = scrape_teams()
    print(f"  Teams scraped: {len(teams_data)}", flush=True)

    # ── 3b. Rider profiles (incremental cache) ───────────────────────────────
    print("\n[3b/4] Rider profiles (incremental)...", flush=True)
    rider_profiles = dict(cache.get("rider_profiles", {}))

    # Collect slugs from race results first (stage top-10, GC/points/KOM/youth top-10)
    result_slugs = []
    seen = set()
    for race in live_races + recent_races:
        for stage in race.get("stages", []):
            for row in stage.get("top10", []):
                slug = row.get("rider_url", "").replace("/profile/", "").strip("/")
                if slug and not row.get("is_ttt") and slug not in seen:
                    result_slugs.append(slug)
                    seen.add(slug)
        for key in ("gc_top10", "points_top10", "kom_top10", "youth_top10"):
            for row in race.get(key, []):
                slug = row.get("rider_url", "").replace("/profile/", "").strip("/")
                if slug and slug not in seen:
                    result_slugs.append(slug)
                    seen.add(slug)

    # Then add team roster riders
    roster_slugs = [
        r["slug"]
        for team in teams_data
        for r in team.get("riders", [])
        if r.get("slug") and r["slug"] not in seen
    ]

    # Priority order: result riders first, then roster
    priority_order = result_slugs + roster_slugs
    all_slugs = set(result_slugs) | set(roster_slugs)
    uncached = [s for s in priority_order if s not in rider_profiles]
    # Always re-fetch profiles for today's stage winners (palmares may have updated)
    refresh_existing = [s for s in priority_order if s in stage_winners_to_refresh and s in rider_profiles]
    # Backfill: re-fetch cached profiles that are missing specialty data.
    # Note: specialties={} means "checked, no PCS block" — exclude those (key must be absent).
    missing_specialties = [s for s in priority_order
                           if s in rider_profiles
                           and 'specialties' not in rider_profiles[s]
                           and s not in stage_winners_to_refresh]
    to_fetch = refresh_existing + missing_specialties[:MAX_NEW_RIDERS_PER_RUN] + uncached[:MAX_NEW_RIDERS_PER_RUN]
    to_fetch = list(dict.fromkeys(to_fetch))  # deduplicate, preserve order
    print(f"  Riders total: {len(all_slugs)} | cached: {len(rider_profiles)} | new: {len(uncached)} | missing specs: {len(missing_specialties)} | refreshing winners: {len(refresh_existing)} | fetching: {len(to_fetch)}", flush=True)

    for slug in to_fetch:
        profile = scrape_rider_profile(slug)
        if profile:
            # Preserve existing specialty data if new fetch returned empty
            # (PCS blocks CI/server IPs — local runs populate specialties, CI must not overwrite)
            if not profile.get('specialties') and rider_profiles.get(slug, {}).get('specialties'):
                profile['specialties'] = rider_profiles[slug]['specialties']
                print(f"    (kept cached specialties)", flush=True)
            rider_profiles[slug] = profile
            tag = "↺" if slug in stage_winners_to_refresh else "+"
            spec_count = len(profile.get('specialties') or {})
            print(f"  {tag} {profile.get('nat','??')} {slug}: {len(profile.get('wins',[]))} wins, {spec_count} specialties", flush=True)
        else:
            print(f"  {slug}: failed", flush=True)

    # Merge photo + wins into each team's rider list
    for team in teams_data:
        for rider in team.get("riders", []):
            p = rider_profiles.get(rider.get("slug", ""))
            if p:
                rider["photo"] = p.get("photo")
                rider["dob"]   = p.get("dob")
                rider["wins"]  = p.get("wins", [])


    # ── 3c. Startlists for upcoming races ────────────────────────────────────
    print("\n[3c/4] Scraping startlists for upcoming races...", flush=True)
    cached_startlists = {
        r.get("cf_slug"): r.get("startlist", [])
        for r in cache.get("upcoming", [])
        if r.get("startlist")
    }
    for race_obj in upcoming_races:
        cf_slug = race_obj.get("cf_slug", "")
        start_date = race_obj.get("start_date", "") or race_obj.get("startdate", "")
        try:
            days_away = (datetime.strptime(start_date, "%Y-%m-%d").date() - datetime.now(timezone.utc).date()).days
        except Exception:
            days_away = 999
        if cf_slug in cached_startlists:
            race_obj["startlist"] = cached_startlists[cf_slug]
            print(f"  {race_obj.get('name','?')} (cached {len(race_obj['startlist'])} riders)", flush=True)
        elif days_away <= 21:
            year_sl = race_obj.get("year", str(datetime.now(timezone.utc).year))
            sl = scrape_startlist(cf_slug, year_sl)
            race_obj["startlist"] = sl
            print(f"  {race_obj.get('name','?')} → {len(sl)} riders", flush=True)
            time.sleep(0.5)
        else:
            race_obj["startlist"] = []
            print(f"  {race_obj.get('name','?')} → {days_away}d away, skipping", flush=True)

    # ── 4. Write output ───────────────────────────────────────────────────────
    print("\n[4/4] Writing data.json...", flush=True)
    now = datetime.now(timezone.utc)
    all_data = {
        "scraped_at":       now.isoformat(),
        "scraped_at_human": now.strftime("%d %b %Y %H:%M UTC"),
        "live":             live_races,
        "upcoming":         upcoming_races,
        "recent":           recent_races,
        "teams":            teams_data,
        "rider_profiles":   rider_profiles,
    }

    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUTPUT_FILE)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\n✓ data.json written ({size_kb} KB)", flush=True)
    print(f"  Live:     {len(live_races)}", flush=True)
    print(f"  Upcoming: {len(upcoming_races)}", flush=True)
    print(f"  Recent:   {len(recent_races)}", flush=True)
    print(f"  Teams:    {len(teams_data)}", flush=True)
    print(f"  Scraped:  {all_data['scraped_at_human']}", flush=True)

    # Send push notifications (runs silently if push_subscriptions.json is absent)
    print("\n[push] Checking notification triggers...", flush=True)
    send_push_notifications(all_data)


# ── Web Push notifications ─────────────────────────────────────────────────────
# Requires: pip install pywebpush
#
# Push subscriptions are saved from the browser via the 🔔 button in the app.
# They live in push_subscriptions.json alongside this script.
#
# VAPID keys (generated once — do not regenerate or existing subscriptions break):
VAPID_PRIVATE_KEY_PEM = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIJMZj4xLkQLtrv8oUg7kd8EnMMVOt3LlWn1Xvp9DPTpUoAoGCCqGSM49
AwEHoUQDQgAEzJQYP8qFlqtCe6Jubs2pQwKIKT9qhhTn5pA0SGeZfACC4YhtEvMP
YtwwEDCrMJMkobdQ1FY2Osef8g8Yq8C1YQ==
-----END EC PRIVATE KEY-----"""

VAPID_CLAIMS = {"sub": "mailto:kieransemail@gmail.com"}


def _load_push_subscriptions():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "push_subscriptions.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [push] Could not read push_subscriptions.json: {e}", flush=True)
        return []


def send_push_notifications(all_data):
    """
    Send Web Push notifications to all subscribed browsers.
    Triggers:
      • Race starting tomorrow → 'Set your team!' alert
      • New stage result today → winner + GC leader
    Call this at the end of main() once VAPID_PRIVATE_KEY_PEM is set.
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("  [push] pywebpush not installed — run: pip install pywebpush", flush=True)
        return

    subscriptions = _load_push_subscriptions()
    if not subscriptions:
        print("  [push] No push subscriptions found", flush=True)
        return

    today    = date.today()
    tomorrow = date.fromordinal(today.toordinal() + 1)
    notifications = []

    # Race starts tomorrow → remind to set fantasy team
    for race in all_data.get("upcoming", []):
        sd = race.get("start_date", "")
        if not sd:
            continue
        try:
            if date.fromisoformat(sd) == tomorrow:
                sl_count = len(race.get("startlist", []))
                notifications.append({
                    "title": f"🚴 {race['name']} starts tomorrow!",
                    "body":  f"Set your fantasy team before the flag drops — {race.get('total_stages',1)} stages · {race.get('category','')}",
                    "tag":   f"race-start-{race.get('slug','')}",
                })
        except ValueError:
            pass

    # New stage results today
    for race in all_data.get("live", []):
        for stage in race.get("stages", []):
            winner = stage.get("winner")
            if not winner:
                continue
            # Rough date check: stage date_str contains today's day number
            ds = stage.get("date_str", "")
            if str(today.day) not in ds:
                continue
            gc     = race.get("classifications", {}).get("gc", [])
            leader = gc[0]["name"] if gc else ""
            body   = f"{winner} wins"
            if leader:
                body += f"  ·  GC: {leader}"
            notifications.append({
                "title": f"🏁 {race['name']} — Stage {stage['num']}",
                "body":  body,
                "tag":   f"stage-{race.get('slug','')}-{stage['num']}",
            })

    if not notifications:
        print("  [push] No notification triggers matched today", flush=True)
        return

    sent = failed = 0
    for sub in subscriptions:
        for notif in notifications:
            try:
                webpush(
                    subscription_info  = sub,
                    data               = json.dumps(notif),
                    vapid_private_key  = VAPID_PRIVATE_KEY_PEM,
                    vapid_claims       = VAPID_CLAIMS,
                )
                sent += 1
            except Exception as e:
                failed += 1
                print(f"  [push] Failed to send to subscription: {e}", flush=True)

    print(f"  [push] {sent} sent, {failed} failed", flush=True)


# ── Email notifications ────────────────────────────────────────────────────────
# To activate: fill in SMTP_USER and SMTP_PASS below.
# Recommended: create a Gmail App Password at
#   https://myaccount.google.com/apppasswords
# (requires 2FA enabled on your Google account).
#
# Then call send_notifications(all_data) at the end of main() if you want
# automatic alerts.  The function reads subscribers.json from the same
# folder as this script.

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = ""          # ← your Gmail address, e.g. "you@gmail.com"
SMTP_PASS = ""          # ← your Gmail App Password (16-char, no spaces)
FROM_ADDR = SMTP_USER   # can differ if using SendGrid etc.


def _load_subscribers():
    """Return list of subscriber dicts from subscribers.json, or []."""
    path = os.path.join(os.path.dirname(__file__), "subscribers.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [email] Could not read subscribers.json: {e}", flush=True)
        return []


def _send_email(to_addr, subject, body_html):
    """Send a single HTML email via SMTP.  Returns True on success."""
    if not SMTP_USER or not SMTP_PASS:
        print(f"  [email] SMTP not configured — skipping send to {to_addr}", flush=True)
        return False
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_ADDR
    msg["To"]      = to_addr
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_ADDR, to_addr, msg.as_string())
        return True
    except Exception as e:
        print(f"  [email] Failed to send to {to_addr}: {e}", flush=True)
        return False


def send_notifications(all_data):
    """
    Send email notifications to subscribers.
    Called automatically at the end of main() if SMTP is configured.

    Triggers:
      • Race starting within 24 h  → 'Set your team!' alert with startlist
      • New stage result posted     → stage winner + updated GC top-5
    """
    subscribers = _load_subscribers()
    if not subscribers:
        print("  [email] No subscribers found in subscribers.json", flush=True)
        return

    today = date.today()
    tomorrow = today.replace(day=today.day + 1) if today.day < 28 else (
        date(today.year, today.month + 1, 1) if today.month < 12 else date(today.year + 1, 1, 1)
    )

    sent = 0
    for race in all_data.get("upcoming", []):
        sd = race.get("start_date", "")
        if not sd:
            continue
        try:
            start = date.fromisoformat(sd)
        except ValueError:
            continue
        if start != tomorrow:
            continue

        # Build startlist summary (top 20 riders by bib if available)
        sl = race.get("startlist", [])
        rider_rows = "".join(
            f"<tr><td style='padding:3px 8px'>{r.get('name','')}</td>"
            f"<td style='padding:3px 8px;color:#888'>{r.get('team','')}</td></tr>"
            for r in sl[:20]
        ) or "<tr><td colspan='2' style='padding:3px 8px;color:#888'>Startlist not yet available</td></tr>"

        subject = f"🚴 {race['name']} starts tomorrow — set your fantasy team!"
        body = f"""
<div style="font-family:sans-serif;max-width:520px;margin:auto;background:#0f1117;color:#e8eaf0;padding:24px;border-radius:12px">
  <h2 style="color:#f4a261;margin-top:0">{race['name']}</h2>
  <p style="color:#8890b0">{race.get('category','')} · {sd} → {race.get('end_date','')}</p>
  <p><strong>The race starts tomorrow.</strong> Make sure your fantasy team is set before the gun goes!</p>
  <h3 style="color:#4361ee;margin-bottom:6px">Startlist (first 20)</h3>
  <table style="border-collapse:collapse;font-size:.9rem;width:100%">{rider_rows}</table>
  <p style="margin-top:20px;font-size:.8rem;color:#8890b0">
    Open the app: <a href="https://kieransemail.github.io/uci-calendar" style="color:#4361ee">UCI Calendar</a>
  </p>
</div>"""
        for sub in subscribers:
            if _send_email(sub["email"], subject, body):
                sent += 1
                print(f"  [email] Sent race-start alert to {sub['email']}", flush=True)

    # Stage results: notify if any new stage winner appeared since last run
    for race in all_data.get("live", []) + all_data.get("recent", []):
        stages = race.get("stages", [])
        new_stages = [s for s in stages if s.get("winner") and s.get("date_str", "").endswith(str(today.day))]
        if not new_stages:
            continue
        s = new_stages[-1]
        gc = race.get("classifications", {}).get("gc", [])
        gc_rows = "".join(
            f"<tr><td style='padding:3px 8px;color:#ffd700'>{'🥇' if r['rank']==1 else r['rank']}</td>"
            f"<td style='padding:3px 8px'>{r.get('name','')}</td>"
            f"<td style='padding:3px 8px;color:#888'>{r.get('time','')}</td></tr>"
            for r in gc[:5]
        ) or ""
        subject = f"🏁 {race['name']} Stage {s['num']} — {s.get('winner','?')} wins"
        body = f"""
<div style="font-family:sans-serif;max-width:520px;margin:auto;background:#0f1117;color:#e8eaf0;padding:24px;border-radius:12px">
  <h2 style="color:#f4a261;margin-top:0">{race['name']}</h2>
  <h3 style="color:#e63946">Stage {s['num']} result</h3>
  <p style="font-size:1.1rem">🏆 <strong>{s.get('winner','')}</strong></p>
  {'<h3 style="color:#4361ee;margin-bottom:6px">GC Top 5</h3><table style="border-collapse:collapse;font-size:.9rem;width:100%">'+gc_rows+'</table>' if gc_rows else ''}
  <p style="margin-top:20px;font-size:.8rem;color:#8890b0">
    Open the app: <a href="https://kieransemail.github.io/uci-calendar" style="color:#4361ee">UCI Calendar</a>
  </p>
</div>"""
        for sub in subscribers:
            if _send_email(sub["email"], subject, body):
                sent += 1
                print(f"  [email] Sent stage result to {sub['email']}", flush=True)

    if sent == 0:
        print("  [email] No notifications sent (either SMTP not set, or no triggers matched)", flush=True)
    else:
        print(f"  [email] {sent} notification(s) sent", flush=True)


def main_teams_only():
    """
    Refresh team rosters only — scrapes all WorldTeam + ProTeam pages and
    merges the updated rosters into data.json, preserving all race/rider data.
    Run mid-season when transfers happen or a team is renamed.
    Run via:  py scraper.py --teams-only
    """
    now_human = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nUCI Scraper — TEAMS ONLY — {now_human}", flush=True)
    print("=" * 60, flush=True)

    if not os.path.exists(OUTPUT_FILE):
        print("  No data.json found — run a full scrape first.", flush=True)
        return

    with open(OUTPUT_FILE, encoding="utf-8") as f:
        d = json.load(f)

    rider_profiles = d.get("rider_profiles", {})
    print(f"  Existing: {len(d.get('teams', []))} teams, {len(rider_profiles)} rider profiles\n", flush=True)

    print("[1/2] Scraping teams...", flush=True)
    teams_data = scrape_teams()
    print(f"\n  Fetched {len(teams_data)} teams", flush=True)

    # Merge only lightweight fields — wins stay in rider_profiles.json
    print("\n[2/2] Merging cached rider data into rosters...", flush=True)
    merged = 0
    for team in teams_data:
        for rider in team.get("riders", []):
            p = rider_profiles.get(rider.get("slug", ""))
            if p:
                rider["photo"] = p.get("photo")
                rider["dob"]   = p.get("dob")
                merged += 1
    print(f"  Merged cached data for {merged} riders", flush=True)

    d["teams"] = teams_data
    d["teams_refreshed_at"] = datetime.now(timezone.utc).isoformat()

    pre_write_size = os.path.getsize(OUTPUT_FILE)
    tmp = OUTPUT_FILE + f".tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))

    for _ in range(10):
        try:
            os.replace(tmp, OUTPUT_FILE)
            break
        except PermissionError:
            time.sleep(0.3)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\n✓ data.json updated ({size_kb} KB) — {len(teams_data)} teams written", flush=True)
    print(f"  Now run: git add data.json && git commit -m 'data: refresh teams' && git push", flush=True)


def main_startlists_only():
    """
    Fetch missing startlists for all upcoming and live races.
    Also rebuilds the startlists_needed list in data.json.

    Must run locally — PCS blocks CI server IPs.
    Run via:  py scraper.py --startlists-only
    Schedule: Windows Task Scheduler, daily at 8am local time.

    Skips races that already have a startlist (len > 0).
    PCS startlists are usually published 2–7 days before race start.
    """
    now_human = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nUCI Scraper — STARTLISTS ONLY — {now_human}", flush=True)
    print("=" * 60, flush=True)

    if not os.path.exists(OUTPUT_FILE):
        print("  No data.json found — run a full scrape first.", flush=True)
        return

    with open(OUTPUT_FILE, encoding="utf-8") as f:
        d = json.load(f)

    today = date.today()
    all_races = list(d.get("upcoming", [])) + list(d.get("live", []))

    # Build startlists_needed: upcoming races without startlists, within 60 days
    def _days_away(r):
        try:
            return (date.fromisoformat(r.get("start_date", "9999-01-01")) - today).days
        except ValueError:
            return 999

    startlists_needed = []
    to_fetch = []
    for r in all_races:
        sl = r.get("startlist", [])
        days = _days_away(r)
        if not sl and 0 <= days <= 60:
            startlists_needed.append({
                "name":       r.get("name", "?"),
                "cf_slug":    r.get("cf_slug", r.get("slug", "")),
                "start_date": r.get("start_date", ""),
                "days_away":  days,
            })
            to_fetch.append((r, days))
        elif not sl and days > 60:
            # Track but don't fetch — too far out
            startlists_needed.append({
                "name":       r.get("name", "?"),
                "cf_slug":    r.get("cf_slug", r.get("slug", "")),
                "start_date": r.get("start_date", ""),
                "days_away":  days,
            })

    d["startlists_needed"] = sorted(startlists_needed, key=lambda x: x["days_away"])

    print(f"  Upcoming races without startlist: {len(startlists_needed)}", flush=True)
    for entry in d["startlists_needed"]:
        print(f"    {entry['days_away']:>3}d  {entry['name']}", flush=True)

    # Fetch startlists for races within 60 days
    fetched = skipped = failed = 0
    to_fetch.sort(key=lambda x: x[1])   # closest first

    if not to_fetch:
        print("\n  Nothing to fetch — all upcoming races either have startlists or are >60 days away.", flush=True)
    else:
        print(f"\n  Fetching startlists for {len(to_fetch)} races (~{len(to_fetch) * DELAY // 60 + 1} min)...\n", flush=True)

    for race_obj, days in to_fetch:
        name     = race_obj.get("name", "?")
        cf_slug  = race_obj.get("cf_slug", race_obj.get("slug", ""))
        year_sl  = race_obj.get("start_date", str(today.year))[:4]

        print(f"  [{days}d] {name}", flush=True)
        sl = scrape_startlist(cf_slug, year_sl)
        time.sleep(DELAY)

        if sl:
            # Update the race in-place within the correct bucket
            for bucket in ("upcoming", "live"):
                for r in d.get(bucket, []):
                    rkey = r.get("cf_slug") or r.get("slug", "")
                    if rkey == cf_slug:
                        r["startlist"] = sl
                        break
            # Remove from startlists_needed
            d["startlists_needed"] = [
                e for e in d["startlists_needed"] if e["cf_slug"] != cf_slug
            ]
            print(f"    ✓ {len(sl)} riders", flush=True)
            fetched += 1
        else:
            print(f"    ✗ Not yet available", flush=True)
            failed += 1

    # Atomic write
    pre_write_size = os.path.getsize(OUTPUT_FILE)
    tmp = OUTPUT_FILE + f".tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    for _ in range(10):
        try:
            os.replace(tmp, OUTPUT_FILE)
            break
        except PermissionError:
            time.sleep(0.3)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\n{'='*60}", flush=True)
    print(f"✓ data.json updated ({size_kb} KB)", flush=True)
    print(f"  {fetched} startlists fetched | {failed} not yet available", flush=True)
    remaining = len(d.get("startlists_needed", []))
    if remaining:
        print(f"  {remaining} races still awaiting startlists — re-run daily", flush=True)
    print(f"\nNext: git add data.json && git commit -m 'data: startlists update' && git push", flush=True)


if __name__ == "__main__":
    import sys
    if "--results-only" in sys.argv:
        main_results_only()
    elif "--teams-only" in sys.argv:
        main_teams_only()
    elif "--startlists-only" in sys.argv:
        main_startlists_only()
    else:
        main()
