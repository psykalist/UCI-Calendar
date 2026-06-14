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

# UCI categories to include
UCI_CATS = {"1.UWT", "2.UWT", "1.Pro", "2.Pro", "1.1", "2.1"}

# ── Team lists (WorldTeam + ProTeam only) ──────────────────────────────────────

MAX_NEW_RIDERS_PER_RUN = 9999  # No effective cap — fetch all outstanding profiles

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
    for attempt in range(retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                return r.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            if e.code in (404, 410):
                return None          # Not found — don't retry
            print(f"    HTTP {e.code} for {url}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except (URLError, OSError) as e:
            print(f"    Fetch error {url}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
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
        print(f"    [debug] HTML saved to {debug_path}")

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
    return rows if rows else None



# ── Stage detail scraping ──────────────────────────────────────────────────────

def scrape_stage_details(slug, stage_num):
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
        r'(\d+(?:\.\d+)?)\s*km\s+([\w\s]+?)\s+stage\s+from\s+([A-Z][^<\n]+?)\s+to\s+([A-Z][^<\n.,"]{2,40?})(?:[<."&#])',
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

    # ── 4. Stage type classification ──────────────────────────────────────────
    type_combined = (type_raw + " " + stage_type_raw).lower()
    if "team time trial" in type_combined:
        stage_type = "TTT"
    elif "time trial" in type_combined or "individual time trial" in type_combined:
        stage_type = "ITT"
    elif elevation_m and elevation_m > 2500:
        stage_type = "mountain"
    elif elevation_m and elevation_m > 1200:
        stage_type = "hilly"
    else:
        stage_type = "flat"

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
            print(f"    [calendar] Could not fetch {url}")
            continue
        slugs = _slugs_from_html(html)
        new = [s for s in slugs if s not in found]
        for s in new:
            found[s] = {"status": "unknown", "last_stage": None}
        print(f"    [calendar] {url.split('/')[-1]}: {len(slugs)} slugs ({len(new)} new)")
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
                'nat':  flag_m.group(1) if flag_m else '',
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

    return {
        'slug':       slug,
        'photo':      photo,
        'dob':        dob,
        'nat':        nat,
        'wins':       wins,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
    }


def scrape_teams():
    """Scrape all WorldTeam and ProTeam pages. Returns list of team dicts."""
    teams = []
    pairs = [(s, 'UWT') for s in WORLD_TEAMS] + [(s, 'Pro') for s in PRO_TEAMS]
    for slug, cat in pairs:
        print(f"  {slug}")
        team = scrape_team(slug, cat)
        time.sleep(DELAY)
        if team:
            print(f"    {team['name']} — {len(team['riders'])} riders")
            teams.append(team)
        else:
            print(f"    [skip] fetch failed")
    return teams


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    now_human = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nUCI Scraper (CyclingFlash) — {now_human}")
    print("=" * 60)

    # Load existing cache for stage data we don't need to re-fetch
    cache = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                cache = json.load(f)
            print(f"  Cache: {OUTPUT_FILE} loaded")
        except Exception as e:
            print(f"  Cache: could not load ({e})")

    cache_by_slug = {
        r["cf_slug"]: r
        for r in cache.get("live", []) + cache.get("recent", []) + cache.get("upcoming", [])
        if "cf_slug" in r
    }

    # ── 1. Discover races ─────────────────────────────────────────────────────
    print("\n[1/4] Discovering races...")

    # Primary: structured calendar pages (full season)
    print("  Scraping calendar pages...")
    discovered = discover_races_from_calendar()

    # Supplement with homepage (catches live races not yet on calendar)
    print("  Supplementing with homepage...")
    for slug, info in discover_races_from_homepage().items():
        if slug not in discovered:
            discovered[slug] = info

    # Ensure mandatory races are always included
    for slug in ALWAYS_INCLUDE:
        if slug not in discovered:
            discovered[slug] = {"status": "unknown", "last_stage": None}

    print(f"  Found {len(discovered)} candidate races")

    # ── 2. Fetch race details ─────────────────────────────────────────────────
    print("\n[2/4] Fetching race details...")

    live_races     = []
    upcoming_races = []
    recent_races   = []
    stage_winners_to_refresh = set()  # Stage winners from freshly scraped (non-cached) results

    for slug, disc in discovered.items():
        print(f"\n  → {slug}")

        # Fetch race info page
        info_html = fetch(f"{BASE_URL}/race/{slug}")
        time.sleep(DELAY)
        if not info_html:
            print("    [skip] Could not fetch race info")
            continue

        # Enable debug for first qualifying race to inspect raw HTML
        debug_this = slug == "tour-auvergne-rhone-alpes-2026"
        info = parse_race_info(slug, info_html, debug=debug_this)

        # Override name/category for known big races if not parsed
        if slug in ALWAYS_INCLUDE and not info.get("name"):
            info["name"], info["category"] = ALWAYS_INCLUDE[slug]

        if not info.get("name"):
            print("    [skip] Could not parse race name")
            continue

        # Skip cancelled races (CyclingFlash prefixes name with "CANCELLED:")
        if info["name"].upper().startswith("CANCELLED"):
            print(f"    [skip] Cancelled race")
            continue

        # Filter by category
        cat = info.get("category", "")
        if slug not in ALWAYS_INCLUDE and not any(cat.startswith(c) for c in UCI_CATS):
            print(f"    [skip] Category {cat!r} not in target list")
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

        print(f"    {name} | {category} | {total_stages} stages | {status}")

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
        print(f"    Finding completed stages (probing 1-{total_stages})...")
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

        print(f"    Completed: {completed_nums}")
        race_obj["stages_completed"] = len(completed_nums)

        # Build stages list
        stages = []
        for n in range(1, total_stages + 1):
            has_details = n in cached_stages_details

            if n in completed_nums:
                if n in cached_stages_results:
                    stage_obj = dict(cached_stages_results[n])
                    w = stage_obj.get("winner", "cached")
                    print(f"      Stage {n}: cached ({w})")
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
                    print(f"      Stage {n}: {winner['name'] if winner else 'no data'}")
            else:
                # Upcoming stage — start from cached details or blank placeholder
                if has_details:
                    stage_obj = dict(cached_stages_details[n])
                    stage_obj.setdefault("top10", [])
                    print(f"      Stage {n}: upcoming (details cached)")
                else:
                    stage_obj = {
                        "num": n, "label": f"Stage {n}",
                        "result_url": f"/race/{slug}/result/stage-{n}",
                        "winner": None, "winner_flag": "", "winner_nat": "",
                        "top10": [],
                    }

            # Fetch stage details (date, distance, elevation, type, description) if not cached
            if not has_details:
                details = scrape_stage_details(slug, n)
                time.sleep(DELAY)
                if details:
                    # Don't overwrite existing height_profile_img from result page
                    if stage_obj.get("height_profile_img"):
                        details.pop("height_profile_img", None)
                    stage_obj.update(details)
                    print(f"        Stage {n} details: {details.get('distance_km','?')}km {details.get('stage_type','?')}")

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
            print(f"    Classifications after stage {last_n}...")
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
                    print(f"      {cls_key}: {leader['name']}")
                else:
                    print(f"      {cls_key}: no data")

        if status == "upcoming":
            upcoming_races.append(race_obj)
        elif status == "live":
            live_races.append(race_obj)
        else:
            recent_races.append(race_obj)

    # ── 3. Scrape teams ───────────────────────────────────────────────────────
    print("\n[3/4] Scraping teams (WorldTeam + ProTeam)...")
    teams_data = scrape_teams()
    print(f"  Teams scraped: {len(teams_data)}")

    # ── 3b. Rider profiles (incremental cache) ───────────────────────────────
    print("\n[3b/4] Rider profiles (incremental)...")
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
    to_fetch = refresh_existing + uncached[:MAX_NEW_RIDERS_PER_RUN]
    print(f"  Riders total: {len(all_slugs)} | cached: {len(rider_profiles)} | new: {len(uncached)} | refreshing winners: {len(refresh_existing)} | fetching: {len(to_fetch)}")

    for slug in to_fetch:
        profile = scrape_rider_profile(slug)
        if profile:
            rider_profiles[slug] = profile
            tag = "↺" if slug in stage_winners_to_refresh else "+"
            print(f"  {tag} {profile.get('nat','??')} {slug}: {len(profile.get('wins',[]))} wins")
        else:
            print(f"  {slug}: failed")

    # Merge photo + wins into each team's rider list
    for team in teams_data:
        for rider in team.get("riders", []):
            p = rider_profiles.get(rider.get("slug", ""))
            if p:
                rider["photo"] = p.get("photo")
                rider["dob"]   = p.get("dob")
                rider["wins"]  = p.get("wins", [])

    # ── 4. Write output ───────────────────────────────────────────────────────
    print("\n[4/4] Writing data.json...")
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
    print(f"\n✓ data.json written ({size_kb} KB)")
    print(f"  Live:     {len(live_races)}")
    print(f"  Upcoming: {len(upcoming_races)}")
    print(f"  Recent:   {len(recent_races)}")
    print(f"  Teams:    {len(teams_data)}")
    print(f"  Scraped:  {all_data['scraped_at_human']}")


if __name__ == "__main__":
    main()
