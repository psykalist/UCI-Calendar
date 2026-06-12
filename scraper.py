"""
UCI Race Calendar Scraper
Fetches race data from procyclingstats.com and writes data.json
Run this script to update data: python scraper.py
Scheduled via Task Scheduler to run 3x daily.
"""
import json
import time
import re
import sys
from datetime import datetime, date
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin
from html.parser import HTMLParser

BASE_URL = "https://www.procyclingstats.com"
OUTPUT_FILE = "data.json"
DELAY = 1.5  # seconds between requests (be polite)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}

# ── Country code → flag emoji ──────────────────────────────────────────────
# PCS uses 3-letter UCI codes OR 2-letter ISO codes; we handle both.
# 3-letter → 2-letter mapping
UCI3_TO_ISO2 = {
    "AFG":"AF","ALG":"DZ","AND":"AD","ANG":"AO","ANT":"AG","ARG":"AR","ARM":"AM",
    "AUS":"AU","AUT":"AT","AZE":"AZ","BAH":"BS","BAN":"BD","BAR":"BB","BEL":"BE",
    "BEN":"BJ","BHU":"BT","BIH":"BA","BLR":"BY","BOL":"BO","BOT":"BW","BRA":"BR",
    "BRN":"BH","BUL":"BG","BUR":"BF","CAF":"CF","CAN":"CA","CHI":"CL","CHN":"CN",
    "CIV":"CI","CMR":"CM","COD":"CD","COG":"CG","COL":"CO","COM":"KM","CPV":"CV",
    "CRC":"CR","CRO":"HR","CUB":"CU","CYP":"CY","CZE":"CZ","DEN":"DK","DJI":"DJ",
    "DOM":"DO","ECU":"EC","EGY":"EG","ERI":"ER","ESP":"ES","EST":"EE","ETH":"ET",
    "FIN":"FI","FIJ":"FJ","FRA":"FR","GBR":"GB","GEO":"GE","GER":"DE","GHA":"GH",
    "GRE":"GR","GUA":"GT","GUY":"GY","HON":"HN","HKG":"HK","HUN":"HU","INA":"ID",
    "IND":"IN","IRL":"IE","IRN":"IR","ISL":"IS","ISR":"IL","ITA":"IT","JAM":"JM",
    "JPN":"JP","KAZ":"KZ","KEN":"KE","KGZ":"KG","KOR":"KR","KSA":"SA","KUW":"KW",
    "LAO":"LA","LAT":"LV","LBA":"LY","LIB":"LB","LIE":"LI","LTU":"LT","LUX":"LU",
    "MAD":"MG","MAS":"MY","MAR":"MA","MDA":"MD","MEX":"MX","MGL":"MN","MKD":"MK",
    "MLI":"ML","MLT":"MT","MON":"MC","MOZ":"MZ","MRI":"MU","MTN":"MR","MWI":"MW",
    "NAM":"NA","NED":"NL","NOR":"NO","NZL":"NZ","OMA":"OM","PAN":"PA","PER":"PE",
    "PHI":"PH","PNG":"PG","POL":"PL","POR":"PT","PRK":"KP","PUR":"PR","QAT":"QA",
    "ROU":"RO","RSA":"ZA","RUS":"RU","RWA":"RW","SEN":"SN","SIN":"SG","SLE":"SL",
    "SLO":"SI","SMR":"SM","SOL":"SB","SOM":"SO","SRB":"RS","SRI":"LK","SUI":"CH",
    "SVK":"SK","SWE":"SE","SYR":"SY","TAN":"TZ","THA":"TH","TJK":"TJ","TKM":"TM",
    "TOG":"TG","TPE":"TW","TRI":"TT","TUN":"TN","TUR":"TR","UAE":"AE","UGA":"UG",
    "UKR":"UA","URU":"UY","USA":"US","UZB":"UZ","VEN":"VE","VIE":"VN","YEM":"YE",
    "ZAM":"ZM","ZIM":"ZW",
}

def flag_emoji(code):
    """Convert any country code (2 or 3 letter) to flag emoji."""
    if not code:
        return ""
    code = code.strip().upper()
    # Convert 3-letter to 2-letter if needed
    if len(code) == 3:
        code = UCI3_TO_ISO2.get(code, "")
    if len(code) != 2:
        return ""
    # Unicode regional indicator symbols: A=0x1F1E6, B=0x1F1E7, ...
    try:
        return "".join(chr(0x1F1E0 + ord(c) - ord("A")) for c in code)
    except Exception:
        return ""


# ── Minimal HTML parser ────────────────────────────────────────────────────
def fetch(path, retries=2):
    """Fetch a PCS page and return HTML string."""
    url = path if path.startswith("http") else BASE_URL + path
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return raw.decode("utf-8", errors="replace")
        except HTTPError as e:
            print(f"  HTTP {e.code} for {url}")
            if e.code in (403, 404):
                return None
            time.sleep(3)
        except URLError as e:
            print(f"  URL error for {url}: {e}")
            time.sleep(3)
        except Exception as e:
            print(f"  Error for {url}: {e}")
            time.sleep(3)
    return None


def parse_flag_class(class_str):
    """Extract country code from PCS flag class string like 'flag NZL' or 'flag nzl smflag'."""
    parts = class_str.split()
    for p in parts:
        if p.lower() != "flag" and p.lower() != "smflag":
            return p.upper()
    return ""


# ── BeautifulSoup-lite: regex-based extraction ─────────────────────────────
def parse_stage_results(html):
    """
    Parse a PCS stage result page.
    Returns list of dicts: {rank, name, rider_url, team, nationality_code, flag, time_gap}
    """
    if not html:
        return []

    results = []
    # Find the main results table (class="basic results" or similar)
    # Match table rows with rider links
    # PCS table structure:
    #   <td class="..."><span class="flag NZL smflag"></span><a href="/rider/...">Name</a></td>

    # Find all result rows - look for rank + rider pattern
    # Strategy: find spans with flag class, then walk the surrounding context

    rider_pattern = re.compile(
        r'<span\s+class="flag\s+([A-Za-z]+)[^"]*"[^>]*>.*?'  # flag span with country
        r'<a\s+href="(/rider/[^"]+)"[^>]*>([^<]+)</a>',       # rider link
        re.DOTALL
    )

    # Also try alternate: rider link first, then flag
    rider_pattern2 = re.compile(
        r'<a\s+href="(/rider/[^"]+)"[^>]*>([^<]+)</a>.*?'
        r'<span\s+class="flag\s+([A-Za-z]+)[^"]*"',
        re.DOTALL
    )

    # Simpler: find all table rows in results table
    # Find the results table first
    table_match = re.search(r'class="basic results"(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if not table_match:
        # Try alternate table class patterns
        table_match = re.search(r'<table[^>]*class="[^"]*result[^"]*"(.*?)</table>', html, re.DOTALL | re.IGNORECASE)

    if not table_match:
        # Fall back to searching entire page for rider rows
        table_html = html
    else:
        table_html = table_match.group(0)

    # Find each row with a ranking and rider
    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)

    for row_m in row_pattern.finditer(table_html):
        row = row_m.group(1)

        # Must have a rider link
        rider_m = re.search(r'<a\s+href="(/rider/([^"]+))"[^>]*>([^<]+)</a>', row)
        if not rider_m:
            continue

        rider_url = rider_m.group(1)
        rider_slug = rider_m.group(2)
        rider_name_raw = rider_m.group(3).strip()

        # Skip if this looks like a team link (no /rider/ prefix check)
        if not rider_url.startswith("/rider/"):
            continue

        # Get nationality from flag span
        flag_m = re.search(r'class="flag\s+([A-Za-z]+)', row)
        nat_code = flag_m.group(1).upper() if flag_m else ""

        # Get rank (first numeric td)
        rank_m = re.search(r'<td[^>]*>\s*(\d+)\s*</td>', row)
        rank = int(rank_m.group(1)) if rank_m else 999

        # Skip non-top-10 (but keep up to 20 for safety)
        if rank > 20:
            continue

        # Get time gap - look for time pattern
        time_gaps = re.findall(r'\+?\d+:\d+(?::\d+)?', row)
        time_gap = time_gaps[-1] if time_gaps else ""
        if rank == 1 and not time_gap.startswith("+"):
            time_gap = "Leader"
        elif rank > 1 and time_gap and not time_gap.startswith("+"):
            time_gap = "+" + time_gap

        # Get team
        team_m = re.search(r'<a\s+href="/team/[^"]+">([^<]+)</a>', row)
        team = team_m.group(1).strip() if team_m else ""

        # Compute flag
        flag = flag_emoji(nat_code)

        results.append({
            "rank": rank,
            "name": rider_name_raw,
            "rider_url": rider_url,
            "team": team,
            "nat_code": nat_code,
            "flag": flag,
            "time_gap": time_gap,
        })

    # Sort by rank and keep top 10
    results.sort(key=lambda x: x["rank"])
    return results[:10]


def parse_stage_list(html, race_path):
    """
    Parse stage list from race overview or results page.
    Returns list of {num, name, date, winner, winner_url, winner_nat, winner_flag, result_url}
    """
    if not html:
        return []

    stages = []
    # Look for stage links in the format /race/NAME/YEAR/stage-N or /stage-N/result
    stage_pattern = re.compile(
        r'<a\s+href="(' + re.escape(race_path) + r'/stage-(\d+)(?:/result)?)"[^>]*>([^<]*)</a>',
        re.IGNORECASE
    )

    seen = set()
    for m in stage_pattern.finditer(html):
        url = m.group(1)
        num = m.group(2)
        label = m.group(3).strip()
        if num not in seen:
            seen.add(num)
            # Normalize URL to result page
            result_url = url if url.endswith("/result") else url + "/result"
            stages.append({
                "num": int(num),
                "label": f"Stage {num}",
                "result_url": result_url,
                "winner": None,
                "winner_flag": "",
                "winner_nat": "",
                "top10": [],
                "status": "upcoming",
            })

    stages.sort(key=lambda x: x["num"])
    return stages


def parse_latest_results_page(html):
    """
    Parse the main latest-results page.
    Returns list of race entries with basic info.
    """
    if not html:
        return []

    races = []

    # Find race entries - PCS uses a table/list structure
    # Each entry has: race name link, category, date, stage winner
    # Pattern: look for links to /race/NAME/YEAR
    race_link_pattern = re.compile(
        r'<a\s+href="(/race/([^/]+)/(\d{4})(?:/[^"]*)?)"[^>]*>([^<]+)</a>',
    )

    seen_races = set()

    # Split into sections roughly by looking at the HTML structure
    # Find table rows or list items with race data
    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)

    for row_m in row_pattern.finditer(html):
        row = row_m.group(1)

        # Must have a race link
        race_m = re.search(r'<a\s+href="(/race/([^/\"]+)/(\d{4})(?:/([^\"]*))?)\"[^>]*>([^<]+)</a>', row)
        if not race_m:
            continue

        full_url = race_m.group(1)
        race_slug = race_m.group(2)
        year = race_m.group(3)
        extra_path = race_m.group(4) or ""
        race_name = race_m.group(5).strip()

        if int(year) < 2026:
            continue

        race_key = f"{race_slug}/{year}"
        if race_key in seen_races:
            continue
        seen_races.add(race_key)

        # Skip if this is a sub-page of a race (stage result etc)
        if "stage" in extra_path or "result" in extra_path or "gc" in extra_path:
            continue

        # Get category badge (e.g., 2.UWT, 1.Pro, 2.2)
        cat_m = re.search(r'(\d\.(UWT|WWT|Pro|HC|1|2|[A-Z]+)(?:\s+|<))', row, re.IGNORECASE)
        category = cat_m.group(1).strip() if cat_m else ""

        # Try to extract date range
        date_m = re.search(r'(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})', row)

        # Get stage winner name if present
        winner_m = re.search(r'<a\s+href="/rider/([^"]+)"[^>]*>([^<]+)</a>', row)
        winner_name = winner_m.group(2).strip() if winner_m else None
        winner_url = f"/rider/{winner_m.group(1)}" if winner_m else None

        # Get winner nationality
        flag_m = re.search(r'class="flag\s+([A-Za-z]+)', row)
        winner_nat = flag_m.group(1).upper() if flag_m else ""
        winner_flag = flag_emoji(winner_nat)

        races.append({
            "slug": race_slug,
            "year": year,
            "name": race_name,
            "category": category,
            "race_path": f"/race/{race_slug}/{year}",
            "latest_winner": winner_name,
            "latest_winner_url": winner_url,
            "latest_winner_nat": winner_nat,
            "latest_winner_flag": winner_flag,
        })

    return races


def scrape_race_stages(race_path, num_stages_to_fetch=6):
    """
    Fetch stage data for a race: stage list + top-10 results for recent stages.
    Returns list of stage dicts.
    """
    print(f"  Fetching race overview: {race_path}")
    html = fetch(race_path)
    time.sleep(DELAY)
    if not html:
        return []

    stages = parse_stage_list(html, race_path)

    # If no stages found from overview, try /results sub-page
    if not stages:
        html2 = fetch(race_path + "/results")
        time.sleep(DELAY)
        if html2:
            stages = parse_stage_list(html2, race_path)

    if not stages:
        print(f"    No stages found for {race_path}")
        return []

    print(f"    Found {len(stages)} stages. Fetching results...")

    # Fetch results for completed stages (work backwards from most recent)
    fetched = 0
    for stage in reversed(stages):
        if fetched >= num_stages_to_fetch:
            break

        result_url = stage["result_url"]
        print(f"    Fetching {result_url} ...")
        stage_html = fetch(result_url)
        time.sleep(DELAY)

        if not stage_html:
            continue

        # Check if stage has results (look for rider links in results section)
        if "/rider/" not in stage_html or "No results" in stage_html:
            stage["status"] = "upcoming"
            continue

        top10 = parse_stage_results(stage_html)
        if top10:
            stage["top10"] = top10
            stage["status"] = "completed"
            stage["winner"] = top10[0]["name"]
            stage["winner_flag"] = top10[0]["flag"]
            stage["winner_nat"] = top10[0]["nat_code"]
            stage["winner_team"] = top10[0]["team"]
            stage["winner_time_gap"] = top10[1]["time_gap"] if len(top10) > 1 else ""
            fetched += 1
        else:
            stage["status"] = "upcoming"

    return stages


def scrape_race_overview(race_path):
    """
    Fetch race overview for metadata: total km, start/finish city, stage count, dates.
    """
    html = fetch(race_path)
    time.sleep(DELAY)
    if not html:
        return {}

    # Extract metadata from infolist or similar elements
    info = {}

    # Distance
    dist_m = re.search(r'(\d[\d,.]+)\s*km', html, re.IGNORECASE)
    if dist_m:
        info["total_km"] = dist_m.group(1).replace(",", "")

    # Dates from title or meta
    date_m = re.search(r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})', html)
    if date_m:
        info["start_date_text"] = date_m.group(1)

    # Number of stages
    stage_count_m = re.search(r'(\d+)\s+stages?', html, re.IGNORECASE)
    if stage_count_m:
        info["num_stages"] = int(stage_count_m.group(1))

    # Start/finish
    route_m = re.search(r'›\s*([^<\n]+?)\s*(?:›|$)', html)
    if route_m:
        info["route"] = route_m.group(1).strip()

    return info


def scrape_rider_profile(rider_url):
    """
    Fetch basic rider profile: full name, nationality, team, age, specialty.
    """
    html = fetch(rider_url)
    time.sleep(DELAY)
    if not html:
        return {}

    profile = {"url": rider_url}

    # Nationality - look for flag in header
    flag_m = re.search(r'class="flag\s+([A-Za-z]+)', html)
    if flag_m:
        nat_code = flag_m.group(1).upper()
        profile["nat_code"] = nat_code
        profile["flag"] = flag_emoji(nat_code)

    # Team
    team_m = re.search(r'<a\s+href="/team/[^"]+">([^<]+)</a>', html)
    if team_m:
        profile["team"] = team_m.group(1).strip()

    # Age/DOB
    age_m = re.search(r'Age:\s*</[^>]+>\s*<[^>]+>\s*(\d+)', html, re.IGNORECASE)
    if age_m:
        profile["age"] = int(age_m.group(1))

    # Specialty/score
    spec_m = re.search(r'Specialty.*?<span[^>]*>([^<]+)</span>', html, re.DOTALL | re.IGNORECASE)
    if spec_m:
        profile["specialty"] = spec_m.group(1).strip()

    return profile


# ── Main races to scrape ───────────────────────────────────────────────────
# Hardcoded list for reliability (PCS URL structure can vary)
LIVE_RACES = [
    {
        "slug": "tour-auvergne-rhone-alpes",
        "name": "Tour Auvergne – Rhône-Alpes",
        "year": "2026",
        "category": "2.UWT",
        "status": "live",
        "start_date": "2026-06-07",
        "end_date": "2026-06-14",
        "total_stages": 8,
    },
    {
        "slug": "tour-du-cameroun",
        "name": "Tour du Cameroun",
        "year": "2026",
        "category": "2.2",
        "status": "live",
        "start_date": "2026-06-03",
        "end_date": "2026-06-14",
        "total_stages": 10,
    },
    {
        "slug": "tour-de-gyeongnam",
        "name": "Tour de Gyeongnam",
        "year": "2026",
        "category": "2.2",
        "status": "live",
        "start_date": "2026-06-09",
        "end_date": "2026-06-13",
        "total_stages": 5,
    },
    {
        "slug": "tour-de-beauce",
        "name": "Tour de Beauce",
        "year": "2026",
        "category": "2.2",
        "status": "live",
        "start_date": "2026-06-10",
        "end_date": "2026-06-14",
        "total_stages": 5,
    },
    {
        "slug": "tour-of-malopolska",
        "name": "Tour of Malopolska",
        "year": "2026",
        "category": "2.2",
        "status": "live",
        "start_date": "2026-06-11",
        "end_date": "2026-06-14",
        "total_stages": 4,
        "has_prologue": True,
    },
]

RECENT_RACES = [
    {
        "slug": "tour-de-wallonie",
        "name": "Ethias-Tour de Wallonie",
        "year": "2026",
        "category": "2.Pro",
        "status": "completed",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "total_stages": 5,
        "gc_winner": "Ben Oliver",
        "gc_winner_nat": "NZL",
        "gc_winner_flag": flag_emoji("NZL"),
    },
    {
        "slug": "tour-of-estonia",
        "name": "Tour of Estonia",
        "year": "2026",
        "category": "2.1",
        "status": "completed",
        "start_date": "2026-06-04",
        "end_date": "2026-06-06",
        "total_stages": 3,
        "gc_winner": "Marceli Bogusławski",
        "gc_winner_nat": "POL",
        "gc_winner_flag": flag_emoji("POL"),
    },
    {
        "slug": "oberosterreichrundfahrt",
        "name": "Oberösterreich Rundfahrt",
        "year": "2026",
        "category": "2.2",
        "status": "completed",
        "start_date": "2026-06-04",
        "end_date": "2026-06-07",
        "total_stages": 4,
        "gc_winner": "Henrique Bravo",
        "gc_winner_nat": "POR",
        "gc_winner_flag": flag_emoji("POR"),
    },
    {
        "slug": "ronde-de-l-oise",
        "name": "Ronde de l'Oise",
        "year": "2026",
        "category": "2.2",
        "status": "completed",
        "start_date": "2026-06-04",
        "end_date": "2026-06-07",
        "total_stages": 4,
        "gc_winner": "Patrick Eddy",
        "gc_winner_nat": "AUS",
        "gc_winner_flag": flag_emoji("AUS"),
    },
    {
        "slug": "circuit-franco-belge",
        "name": "Circuit Franco-Belge",
        "year": "2026",
        "category": "1.Pro",
        "status": "completed",
        "start_date": "2026-06-10",
        "end_date": "2026-06-10",
        "total_stages": 1,
        "gc_winner": "Corbin Strong",
        "gc_winner_nat": "NZL",
        "gc_winner_flag": flag_emoji("NZL"),
    },
    {
        "slug": "brussels-cycling-classic",
        "name": "Brussels Cycling Classic",
        "year": "2026",
        "category": "1.Pro",
        "status": "completed",
        "start_date": "2026-06-07",
        "end_date": "2026-06-07",
        "total_stages": 1,
        "gc_winner": "Jordi Meeus",
        "gc_winner_nat": "BEL",
        "gc_winner_flag": flag_emoji("BEL"),
    },
    {
        "slug": "giro-d-italia",
        "name": "Giro d'Italia 2026",
        "year": "2026",
        "category": "2.UWT",
        "status": "completed",
        "start_date": "2026-05-10",
        "end_date": "2026-05-31",
        "total_stages": 21,
        "gc_winner": "Jonas Vingegaard",
        "gc_winner_nat": "DEN",
        "gc_winner_flag": flag_emoji("DEN"),
    },
]

UPCOMING_RACES = [
    {
        "slug": "tour-de-france",
        "name": "Tour de France",
        "year": "2026",
        "category": "2.UWT",
        "status": "upcoming",
        "start_date": "2026-07-04",
        "end_date": "2026-07-26",
        "total_stages": 21,
        "featured": True,
        "contenders": [
            {"name": "Tadej Pogačar", "nat": "SLO", "flag": flag_emoji("SLO")},
            {"name": "Jonas Vingegaard", "nat": "DEN", "flag": flag_emoji("DEN")},
            {"name": "Remco Evenepoel", "nat": "BEL", "flag": flag_emoji("BEL")},
            {"name": "Antonio Del Toro", "nat": "MEX", "flag": flag_emoji("MEX")},
            {"name": "Mathieu van der Poel", "nat": "NED", "flag": flag_emoji("NED")},
            {"name": "Tom Pidcock", "nat": "GBR", "flag": flag_emoji("GBR")},
            {"name": "Jasper Philipsen", "nat": "BEL", "flag": flag_emoji("BEL")},
        ],
        "start_city": "Barcelona",
        "finish_city": "Paris",
        "total_km": "3333",
    },
    {
        "slug": "tour-de-suisse",
        "name": "Tour de Suisse",
        "year": "2026",
        "category": "2.UWT",
        "status": "upcoming",
        "start_date": "2026-06-17",
        "end_date": "2026-06-21",
        "total_stages": 8,
    },
    {
        "slug": "tour-de-suisse-women",
        "name": "Tour de Suisse Women",
        "year": "2026",
        "category": "2.WWT",
        "status": "upcoming",
        "start_date": "2026-06-17",
        "end_date": "2026-06-21",
    },
    {
        "slug": "tour-of-belgium",
        "name": "Baloise Belgium Tour",
        "year": "2026",
        "category": "2.Pro",
        "status": "upcoming",
        "start_date": "2026-06-17",
        "end_date": "2026-06-21",
        "total_stages": 5,
    },
    {
        "slug": "tour-of-slovenia",
        "name": "Tour of Slovenia",
        "year": "2026",
        "category": "2.Pro",
        "status": "upcoming",
        "start_date": "2026-06-17",
        "end_date": "2026-06-21",
        "total_stages": 5,
    },
    {
        "slug": "copenhagen-sprint",
        "name": "Copenhagen Sprint ME",
        "year": "2026",
        "category": "1.UWT",
        "status": "upcoming",
        "start_date": "2026-06-14",
        "end_date": "2026-06-14",
        "total_stages": 1,
    },
    {
        "slug": "giro-ciclistico-d-italia",
        "name": "Giro d'Italia Next Gen",
        "year": "2026",
        "category": "2.2U",
        "status": "upcoming",
        "start_date": "2026-06-14",
        "end_date": "2026-06-21",
    },
]

# Key rider profiles to pre-fetch
TDF_CONTENDER_URLS = [
    "/rider/tadej-pogacar",
    "/rider/jonas-vingegaard",
    "/rider/remco-evenepoel",
    "/rider/mathieu-van-der-poel",
    "/rider/jasper-philipsen",
    "/rider/wout-van-aert",
]


def main():
    print(f"UCI Scraper starting — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_data = {
        "scraped_at": datetime.now().isoformat(),
        "scraped_at_human": datetime.now().strftime("%d %b %Y %H:%M"),
        "live": [],
        "upcoming": UPCOMING_RACES[:],
        "recent": RECENT_RACES[:],
        "rider_profiles": {},
    }

    # ── 1. Scrape live race stages ─────────────────────────────────────────
    print("\n[1/3] Scraping live races...")
    for race in LIVE_RACES:
        print(f"\n  Race: {race['name']}")
        race_path = f"/race/{race['slug']}/{race['year']}"

        race_data = dict(race)
        race_data["stages"] = []
        race_data["pcs_url"] = BASE_URL + race_path

        try:
            stages = scrape_race_stages(race_path, num_stages_to_fetch=8)
            if stages:
                race_data["stages"] = stages
                completed = [s for s in stages if s.get("status") == "completed"]
                if completed:
                    last = completed[-1]
                    race_data["last_stage_winner"] = last.get("winner")
                    race_data["last_stage_winner_flag"] = last.get("winner_flag", "")
                    race_data["last_stage_num"] = last["num"]
                race_data["stages_completed"] = len(completed)
            print(f"    Done: {len(race_data['stages'])} stages, {race_data.get('stages_completed', 0)} completed")
        except Exception as e:
            print(f"    ERROR: {e}")

        all_data["live"].append(race_data)
        time.sleep(DELAY)

    # ── 2. Scrape recent race stages ───────────────────────────────────────
    print("\n[2/3] Scraping recent races for stage results...")
    for race in all_data["recent"]:
        if race.get("total_stages", 1) <= 1:
            # One-day race, no stages to fetch
            race["stages"] = []
            continue

        print(f"\n  Race: {race['name']}")
        race_path = f"/race/{race['slug']}/{race['year']}"
        race["pcs_url"] = BASE_URL + race_path

        try:
            stages = scrape_race_stages(race_path, num_stages_to_fetch=race.get("total_stages", 5))
            race["stages"] = stages
            print(f"    Done: {len(stages)} stages")
        except Exception as e:
            print(f"    ERROR: {e}")
            race["stages"] = []

        time.sleep(DELAY)

    # ── 3. Fetch key rider profiles ────────────────────────────────────────
    print("\n[3/3] Fetching rider profiles...")
    for url in TDF_CONTENDER_URLS:
        print(f"  {url}")
        try:
            profile = scrape_rider_profile(url)
            if profile:
                slug = url.replace("/rider/", "")
                all_data["rider_profiles"][slug] = profile
        except Exception as e:
            print(f"    ERROR: {e}")
        time.sleep(DELAY)

    # ── Write output ───────────────────────────────────────────────────────
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ data.json written ({len(json.dumps(all_data)) // 1024} KB)")
    print(f"   Live races: {len(all_data['live'])}")
    print(f"   Upcoming: {len(all_data['upcoming'])}")
    print(f"   Recent: {len(all_data['recent'])}")
    print(f"   Rider profiles: {len(all_data['rider_profiles'])}")
    print(f"   Scraped at: {all_data['scraped_at_human']}")


if __name__ == "__main__":
    main()
