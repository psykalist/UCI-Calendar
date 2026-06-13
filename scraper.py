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
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)
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
    Returns list of dicts: {rank, name, rider_url, team, nat_code, flag, time_gap}

    Actual PCS HTML structure (confirmed from live page):
      <tr>
        <td>1</td>                          ← rank
        <td class="ridername">
          <span class="flag nz"></span>     ← 2-letter ISO code, lowercase
          <a data-ct="OC" href="rider/marshall-erwood">
            <span class="uppercase">erwood</span> Marshall
          </a>
        </td>
        <td class="time ar"><font>4:10:10</font></td>
      </tr>
    """
    if not html:
        return []

    results = []
    seen_ranks = set()

    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)

    for row_m in row_pattern.finditer(html):
        row = row_m.group(1)

        # Must contain a rider link (relative: href="rider/slug")
        if 'href="rider/' not in row:
            continue

        # Extract rider link — may have extra attributes like data-ct before href
        rider_m = re.search(r'<a\b[^>]*\bhref="rider/([^"]+)"[^>]*>(.*?)</a>', row, re.DOTALL)
        if not rider_m:
            continue

        rider_slug = rider_m.group(1)
        rider_url = "/rider/" + rider_slug

        # Build rider name: strip all HTML tags from link content, capitalize
        name_html = rider_m.group(2)
        name_text = re.sub(r'<[^>]+>', ' ', name_html)
        rider_name = ' '.join(p.capitalize() for p in name_text.split())
        if not rider_name:
            continue

        # Rank: first <td> whose entire content is a positive integer
        rank_m = re.search(r'<td[^>]*>\s*([1-9]\d{0,2})\s*</td>', row)
        if not rank_m:
            continue
        rank = int(rank_m.group(1))
        if rank > 150 or rank in seen_ranks:
            continue
        seen_ranks.add(rank)

        # Nationality: <span class="flag XX"> where XX is 2-letter lowercase ISO
        flag_m = re.search(r'class="flag\s+([a-z]{2})\b', row)
        nat_code = flag_m.group(1).upper() if flag_m else ""
        flag = flag_emoji(nat_code)

        # Team: first team link
        team_m = re.search(r'<a\b[^>]*\bhref="team/[^"]+">([^<]+)</a>', row)
        team = team_m.group(1).strip() if team_m else ""

        # Finish/gap time: <td class="time ar ..."><font>VALUE</font>
        time_m = re.search(r'class="time\s+ar[^"]*"[^>]*><font[^>]*>([^<]+)</font>', row)
        raw_time = time_m.group(1).strip() if time_m else ""

        # Build display time gap
        if rank == 1:
            time_gap = raw_time  # winner's finish time e.g. "4:10:10"
        elif raw_time in (",,", ""):
            time_gap = "+0:00"   # same time as winner
        else:
            # Already has + prefix or is a gap like "0:03"
            time_gap = raw_time if raw_time.startswith("+") else "+" + raw_time

        results.append({
            "rank": rank,
            "name": rider_name,
            "rider_url": rider_url,
            "team": team,
            "nat_code": nat_code,
            "flag": flag,
            "time_gap": time_gap,
        })

    results.sort(key=lambda x: x["rank"])
    return results[:10]


def parse_stage_list(html, race_path):
    """
    Parse stage list from race overview or results page.
    Returns list of {num, name, date, winner, winner_url, winner_nat, winner_flag, result_url}
    """
    if not html:
        return []

    # Extract slug and year from race_path like "/race/tour-de-beauce/2026"
    parts = race_path.strip('/').split('/')
    if len(parts) < 3:
        return []
    race_slug = parts[1]
    race_year = parts[2]

    stages = []

    # Match BOTH relative (/race/slug/year/stage-N) and absolute URLs
    # PCS uses absolute URLs in many places: href="https://www.procyclingstats.com/race/..."
    # Also handle /prologue (some races use this instead of /stage-0)
    stage_pattern = re.compile(
        r'href="(?:https?://(?:www\.)?procyclingstats\.com)?'
        r'(/race/' + re.escape(race_slug) + r'/' + re.escape(race_year) + r'/(?:stage-(\d+)|prologue)(?:/result)?)[^"]*"',
        re.IGNORECASE
    )

    seen = set()
    for m in stage_pattern.finditer(html):
        url = m.group(1)
        num_str = m.group(2)  # None if prologue matched
        is_prologue = num_str is None
        num = 0 if is_prologue else int(num_str)
        key = "prologue" if is_prologue else str(num)
        if key not in seen:
            seen.add(key)
            # Normalize URL to result page
            result_url = url if url.endswith("/result") else url + "/result"
            stages.append({
                "num": num,
                "label": "Prologue" if is_prologue else f"Stage {num}",
                "result_url": result_url,
                "winner": None,
                "winner_url": None,
                "winner_flag": "",
                "winner_nat": "",
                "top10": [],
                "status": "upcoming",
            })

    stages.sort(key=lambda x: x["num"])

    # Extract stage winners from overview page stage-winners table.
    # Table pattern: "Stage N" or "Prologue" cell followed by a rider link cell.
    winner_map = {}
    rider_href = r'(?:https?://(?:www\.)?procyclingstats\.com)?(/rider/([^"]+))'

    stage_winner_pattern = re.compile(
        r'(?:Stage\s+(\d+)|Prologue)\s*</td>\s*<td[^>]*>.*?'
        r'<a\s+href="' + rider_href + r'"[^>]*>([^<]+)</a>',
        re.DOTALL | re.IGNORECASE
    )
    for m in stage_winner_pattern.finditer(html):
        stage_num_str = m.group(1)  # None if Prologue matched
        key = "0" if stage_num_str is None else stage_num_str
        rider_url = m.group(2)
        rider_name = m.group(4).strip()
        winner_map[key] = {"winner": rider_name, "winner_url": rider_url}

    # Also try a looser pattern: rows containing both a stage number and rider link
    if not winner_map:
        loose_pattern = re.compile(
            r'<tr[^>]*>.*?(?:Stage\s+(\d+)|Prologue).*?'
            r'href="' + rider_href + r'"[^>]*>([^<]+)</a>.*?</tr>',
            re.DOTALL | re.IGNORECASE
        )
        for m in loose_pattern.finditer(html):
            stage_num_str = m.group(1)
            key = "0" if stage_num_str is None else stage_num_str
            rider_url = m.group(2)
            rider_name = m.group(4).strip()
            if key not in winner_map:
                winner_map[key] = {"winner": rider_name, "winner_url": rider_url}

    # Apply winners to stage entries
    for stage in stages:
        key = str(stage["num"])  # 0 for prologue
        if key in winner_map:
            stage["winner"] = winner_map[key]["winner"]
            stage["winner_url"] = winner_map[key]["winner_url"]
            stage["status"] = "completed"

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


def build_stage_list(race_path, total_stages, has_prologue=False):
    """
    Build stage URL list directly from total_stages count.
    Avoids HTML parsing of overview page (PCS renders stage list via JS).
    """
    stages = []
    if has_prologue:
        stages.append({
            "num": 0,
            "label": "Prologue",
            "result_url": f"{race_path}/prologue/result",
            "winner": None,
            "winner_url": None,
            "winner_flag": "",
            "winner_nat": "",
            "top10": [],
            "status": "upcoming",
        })
    for n in range(1, total_stages + 1):
        stages.append({
            "num": n,
            "label": f"Stage {n}",
            "result_url": f"{race_path}/stage-{n}/result",
            "winner": None,
            "winner_url": None,
            "winner_flag": "",
            "winner_nat": "",
            "top10": [],
            "status": "upcoming",
        })
    return stages


def scrape_race_stages(race_path, total_stages=0, has_prologue=False, num_stages_to_fetch=6):
    """
    Fetch stage data for a race: build stage list from total_stages, then
    fetch top-10 results for the most recent completed stages.
    Returns list of stage dicts.
    """
    # Build stage list from count (reliable) or fall back to HTML parsing
    if total_stages > 0 or has_prologue:
        stages = build_stage_list(race_path, total_stages, has_prologue)
        print(f"  Built {len(stages)} stage URLs for {race_path}")
    else:
        # Fallback: try HTML parsing of overview page
        print(f"  Fetching race overview (fallback): {race_path}")
        html = fetch(race_path)
        time.sleep(DELAY)
        stages = parse_stage_list(html, race_path) if html else []
        if not stages:
            html2 = fetch(race_path + "/results")
            time.sleep(DELAY)
            stages = parse_stage_list(html2, race_path) if html2 else []
        if not stages:
            print(f"    No stages found for {race_path}")
            return []
        print(f"    Found {len(stages)} stages via HTML")

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
            stage["status"] = "upcoming"
            continue

        # Check if stage has results
        # PCS uses relative URLs: href="rider/name" (no leading slash)
        if "rider/" not in stage_html:
            stage["status"] = "upcoming"
            # One-time debug: show what we're actually getting
            if fetched == 0:
                print(f"    [debug] len={len(stage_html)}, has_rider={('rider/' in stage_html)}, has_table={('basic results' in stage_html)}")
                # Look for ERWOOD (known Stage 1 winner of Tour de Beauce)
                erwood_pos = stage_html.lower().find("erwood")
                print(f"    [debug] 'erwood' at pos={erwood_pos}")
                # Show first 600 chars
                snippet = stage_html[:600].replace('\n', ' ').replace('\r', '')
                print(f"    [debug] start: {snippet}")
            continue

        top10 = parse_stage_results(stage_html)
        if top10:
            stage["top10"] = top10
            stage["status"] = "completed"
            stage["winner"] = top10[0]["name"]
            stage["winner_flag"] = top10[0]["flag"]
            stage["winner_nat"] = top10[0]["nat_code"]
            stage["winner_team"] = top10[0].get("team", "")
            stage["winner_time_gap"] = top10[1]["time_gap"] if len(top10) > 1 else ""
            fetched += 1
        else:
            stage["status"] = "upcoming"

    return stages


def _parse_cls_flag(class_str):
    """Extract 2-letter ISO code from rendered flag class like 'flag fr smflag'."""
    m = re.search(r'\bflag\s+([a-z]{2})\b', class_str)
    return m.group(1).upper() if m else ""


def scrape_classifications_playwright(race_path):
    """
    Use headless Chromium (Playwright) to scrape JS-rendered classification pages.
    Passes session cookies from a urllib pre-fetch to bypass Cloudflare.
    Returns same dict format as scrape_classifications(), or None if unavailable.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return None

    parts = race_path.strip('/').split('/')
    race_slug = parts[1] if len(parts) >= 2 else ""
    race_year = parts[2] if len(parts) >= 3 else ""

    # Pre-fetch GC page via urllib to get a valid PHPSESSID cookie
    import http.cookiejar, urllib.request as ur2, urllib.parse as up2
    cj = http.cookiejar.CookieJar()
    opener = ur2.build_opener(ur2.HTTPCookieProcessor(cj))
    gc_url = f"{BASE_URL}/race/{race_slug}/{race_year}/gc"
    try:
        req = ur2.Request(gc_url, headers=HEADERS)
        with opener.open(req, timeout=15) as r:
            r.read()
    except Exception:
        pass
    cookies_list = [{"name": c.name, "value": c.value, "domain": "www.procyclingstats.com", "path": "/"}
                    for c in cj]
    print(f"    [playwright] Session cookies: {[c['name'] for c in cookies_list]}")

    result = {}
    PAGE_TIMEOUT = 15000   # 15s for page load
    WAIT_TIMEOUT = 8000    # 8s to wait for JS render

    print(f"    [playwright] Launching headless browser...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36",
                locale="en-GB",
            )
            if cookies_list:
                ctx.add_cookies(cookies_list)
            page = ctx.new_page()

            for cls_key in ["gc", "points", "kom", "youth"]:
                url = f"{BASE_URL}/race/{race_slug}/{race_year}/{cls_key}"
                print(f"    [playwright] {cls_key} ...", end=" ", flush=True)
                try:
                    page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT)
                    try:
                        page.wait_for_function(
                            "(function(){var d=document.querySelectorAll('td.ridername div.cont');"
                            "for(var i=0;i<d.length;i++){if(d[i].textContent.trim()!='')return true;}"
                            "return false;})()",
                            timeout=WAIT_TIMEOUT * 2
                        )
                    except PWTimeout:
                        # Try scrolling to trigger lazy-load, then wait briefly
                        try:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            page.wait_for_timeout(2000)
                        except Exception:
                            pass

                    rows_data = page.evaluate("""() => {
                        const out = [];
                        const rows = document.querySelectorAll('tbody tr');
                        for (let i = 0; i < rows.length && out.length < 10; i++) {
                            const row = rows[i];
                            const r1 = row.querySelector('td:first-child');
                            const rank = r1 ? parseInt(r1.textContent.trim()) : 0;
                            if (!rank || rank > 150) continue;
                            const a = row.querySelector('td.ridername a') || row.querySelector('div.cont a');
                            if (!a) continue;
                            const fl = row.querySelector('span[class*="flag"]');
                            const tm = row.querySelector('td.cu600 a');
                            const ti = row.querySelector('td.time') || row.querySelector('td.ar');
                            out.push({rank, name: a.textContent.trim(), href: a.getAttribute('href')||'',
                                      flagClass: fl ? fl.className : '',
                                      team: tm ? tm.textContent.trim() : '',
                                      time: ti ? ti.textContent.trim() : ''});
                        }
                        return out;
                    }""")

                    if not rows_data:
                        print("no data")
                        continue

                    top10 = []
                    for i, r in enumerate(rows_data[:10]):
                        nat_code = _parse_cls_flag(r.get("flagClass", ""))
                        flag = flag_emoji(nat_code)
                        href = r.get("href", "")
                        rider_url = href if href.startswith("/") else "/" + href
                        name = " ".join(p.capitalize() for p in r.get("name", "").split())
                        rank = r.get("rank", i + 1)
                        raw_time = r.get("time", "").strip()
                        time_gap = raw_time if rank == 1 else (
                            "+0:00" if raw_time in ("", ",,") else
                            (raw_time if raw_time.startswith("+") else "+" + raw_time))
                        top10.append({"rank": rank, "name": name, "rider_url": rider_url,
                                      "team": r.get("team", ""), "nat_code": nat_code,
                                      "flag": flag, "time_gap": time_gap})

                    if top10:
                        result[f"{cls_key}_top10"] = top10
                        leader = top10[0]
                        result[f"{cls_key}_leader"] = leader.get("flag","") + " " + leader["name"]
                        print(f"leader: {leader['name']}")
                    else:
                        print("empty after extract")
                    time.sleep(1)

                except Exception as e:
                    print(f"error: {e}")

            browser.close()
    except Exception as e:
        print(f"    [playwright] Browser error: {e}")
        return None

    return result


def scrape_classifications(race_path, use_playwright=True):
    """
    Fetch GC/Points/KOM/Youth top-10.
    Static HTML first (fast, works for lower-tier races).
    Falls back to Playwright for JS-rendered pages (if use_playwright=True).
    """
    result = {}
    any_static = False
    for cls_key in ["gc", "points", "kom", "youth"]:
        url = f"{race_path}/{cls_key}"
        html = fetch(url)
        time.sleep(DELAY)
        if not html:
            continue
        top10 = parse_stage_results(html)
        if top10:
            any_static = True
            result[f"{cls_key}_top10"] = top10
            leader = top10[0]
            result[f"{cls_key}_leader"] = leader.get("flag","") + " " + leader["name"]
            print(f"      {cls_key} leader (static): {leader['name']}")

    if any_static:
        return result

    if not use_playwright:
        print(f"    Classifications not available (JS-rendered race, Playwright disabled)")
        return result

    print(f"    Static HTML empty, trying Playwright...")
    pw_result = scrape_classifications_playwright(race_path)
    if pw_result is not None:
        return pw_result

    print(f"    [!] Playwright not installed. Run: pip install playwright && playwright install chromium")
    return result


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
        "js_rendered": True,
        "name": "Tour Auvergne – Rhône-Alpes",
        "year": "2026",
        "category": "2.UWT",
        "status": "live",
        "start_date": "2026-06-07",
        "end_date": "2026-06-14",
        "total_stages": 8,
        "official_url": "https://www.tourauvergnerhoalpes.fr/",
    },
    {
        "slug": "tour-du-cameroun",
        "js_rendered": True,
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
        "js_rendered": True,
        "name": "Tour de Beauce",
        "year": "2026",
        "category": "2.2",
        "status": "live",
        "start_date": "2026-06-10",
        "end_date": "2026-06-14",
        "total_stages": 5,
        "official_url": "https://www.tourdebeauce.com/",
    },
    {
        "slug": "tour-of-malopolska",
        "js_rendered": True,
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
        "official_url": "https://www.letour.fr/en/",
    },
    {
        "slug": "tour-de-suisse",
        "name": "Tour de Suisse",
        "year": "2026",
        "category": "2.UWT",
        "status": "upcoming",
        "start_date": "2026-06-13",
        "end_date": "2026-06-21",
        "total_stages": 8,
        "official_url": "https://www.tourdesuisse.ch/en/",
    },
    {
        "slug": "tour-de-suisse-women",
        "name": "Tour de Suisse Women",
        "year": "2026",
        "category": "2.WWT",
        "status": "upcoming",
        "start_date": "2026-06-13",
        "end_date": "2026-06-21",
        "official_url": "https://www.tourdesuisse.ch/en/",
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
        "official_url": "https://www.touroflovenija.com/",
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
        "total_stages": 8,
    },
    {
        "slug": "national-championships",
        "name": "National Championships",
        "year": "2026",
        "category": "NC",
        "status": "upcoming",
        "start_date": "2026-06-20",
        "end_date": "2026-06-28",
        "total_stages": 1,
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


def load_cache():
    """Load existing data.json as a cache to avoid re-scraping completed races."""
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def is_complete_recent(race, cache):
    """
    Return True if this completed race already has full stage data cached.
    Skips re-scraping if every expected stage has a top10.
    """
    if not cache:
        return False
    cached_recent = {r["slug"]: r for r in cache.get("recent", [])}
    cached = cached_recent.get(race["slug"])
    if not cached:
        return False
    total = race.get("total_stages", 1)
    if total <= 1:
        return True  # one-day race, nothing to scrape
    stages = cached.get("stages", [])
    completed = [s for s in stages if s.get("status") == "completed" and s.get("top10")]
    # Consider complete if we have top10 for all expected stages
    return len(completed) >= total


def main():
    print(f"UCI Scraper starting — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Load cache so we can skip re-scraping completed races
    cache = load_cache()
    if cache:
        print(f"  Cache loaded from {OUTPUT_FILE}")

    all_data = {
        "scraped_at": datetime.now().isoformat(),
        "scraped_at_human": datetime.now().strftime("%d %b %Y %H:%M"),
        "live": [],
        "upcoming": UPCOMING_RACES[:],
        "recent": RECENT_RACES[:],
        "rider_profiles": cache.get("rider_profiles", {}),  # reuse cached profiles
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
            stages = scrape_race_stages(
                race_path,
                total_stages=race.get("total_stages", 0),
                has_prologue=race.get("has_prologue", False),
                num_stages_to_fetch=8,
            )
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

            # Fetch classification leaders (GC, Points, KOM, Youth)
            if race_data.get("total_stages", 1) > 1:
                print(f"    Fetching classifications...")
                cls_data = scrape_classifications(race_path, use_playwright=True)
                race_data.update(cls_data)

        except Exception as e:
            print(f"    ERROR: {e}")

        all_data["live"].append(race_data)
        time.sleep(DELAY)

    # ── 2. Scrape recent race stages ───────────────────────────────────────
    print("\n[2/3] Scraping recent races for stage results...")
    cached_recent = {r["slug"]: r for r in cache.get("recent", [])}
    for race in all_data["recent"]:
        if race.get("total_stages", 1) <= 1:
            race["stages"] = cached_recent.get(race["slug"], {}).get("stages", [])
            continue

        if is_complete_recent(race, cache):
            cached = cached_recent[race["slug"]]
            race["stages"] = cached.get("stages", [])
            print(f"  {race['name']}: cached ({len(race['stages'])} stages, skipping)")
            continue

        print(f"\n  Race: {race['name']}")
        race_path = f"/race/{race['slug']}/{race['year']}"
        race["pcs_url"] = BASE_URL + race_path

        try:
            stages = scrape_race_stages(
                race_path,
                total_stages=race.get("total_stages", 0),
                has_prologue=race.get("has_prologue", False),
                num_stages_to_fetch=race.get("total_stages", 5),
            )
            race["stages"] = stages
            print(f"    Done: {len(stages)} stages")
        except Exception as e:
            print(f"    ERROR: {e}")
            race["stages"] = cached_recent.get(race["slug"], {}).get("stages", [])

        time.sleep(DELAY)

    # ── 3. Fetch key rider profiles ────────────────────────────────────────
    print("\n[3/3] Fetching rider profiles...")
    existing_profiles = all_data["rider_profiles"]
    for url in TDF_CONTENDER_URLS:
       
        slug = url.replace("/rider/", "")
        if slug in existing_profiles:
            print(f"  {url}: cached")
            continue
        print(f"  {url}")
        try:
            profile = scrape_rider_profile(url)
            if profile:
                existing_profiles[slug] = profile
        except Exception as e:
            print(f"    ERROR: {e}")
        time.sleep(DELAY)

    # ── Write output (atomic: write temp then rename) ─────────────────────
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    import os
    os.replace(tmp, OUTPUT_FILE)

    print(f"\n[OK] data.json written ({len(json.dumps(all_data)) // 1024} KB)")
    print(f"   Live races: {len(all_data['live'])}")
    print(f"   Upcoming: {len(all_data['upcoming'])}")
    print(f"   Recent: {len(all_data['recent'])}")


if __name__ == "__main__":
    main()
files: {len(all_data['rider_profiles'])}")
    print(f"   Scraped at: {all_data['scraped_at_human']}")


if __name__ == "__main__":
    main()
