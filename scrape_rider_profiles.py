#!/usr/bin/env python3
"""
scrape_rider_profiles.py — Fetch rider profiles (bio + full palmares) from PCS.

Collects rider slugs from pcs_stats.json and data.json, then fetches:
  - /rider/{slug}              -> photo, name, DOB, nationality, specialty scores
  - /rider/{slug}/statistics/wins -> full career palmares

Output: rider_profiles.json

Usage:
  py scrape_rider_profiles.py              # fetch only new/unseen riders
  py scrape_rider_profiles.py --fix-empty  # re-fetch riders with 0 wins
  py scrape_rider_profiles.py --all        # re-fetch everything from scratch

Must run locally — PCS blocks CI server IPs.
After running:
  git add rider_profiles.json && git commit -m "data: rider profiles" && git push
"""

import json, os, re, time, sys, datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

BASE          = Path(__file__).parent
PROFILES_FILE = BASE / 'rider_profiles.json'
STATS_FILE    = BASE / 'pcs_stats.json'
DATA_FILE     = BASE / 'data.json'
DELAY         = 0.5   # seconds between requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

COUNTRY_MAP = {
    'Afghanistan': 'AF', 'Albania': 'AL', 'Algeria': 'DZ', 'Andorra': 'AD',
    'Argentina': 'AR', 'Armenia': 'AM', 'Australia': 'AU', 'Austria': 'AT',
    'Azerbaijan': 'AZ', 'Bahrain': 'BH', 'Belgium': 'BE', 'Bolivia': 'BO',
    'Bosnia and Herzegovina': 'BA', 'Brazil': 'BR', 'Bulgaria': 'BG',
    'Cameroon': 'CM', 'Canada': 'CA', 'Chile': 'CL', 'China': 'CN',
    'Colombia': 'CO', 'Costa Rica': 'CR', 'Croatia': 'HR', 'Cuba': 'CU',
    'Czech Republic': 'CZ', 'Czechia': 'CZ', 'Denmark': 'DK', 'Ecuador': 'EC',
    'Egypt': 'EG', 'Eritrea': 'ER', 'Estonia': 'EE', 'Ethiopia': 'ET',
    'Finland': 'FI', 'France': 'FR', 'Georgia': 'GE', 'Germany': 'DE',
    'Ghana': 'GH', 'Great Britain': 'GB', 'Greece': 'GR', 'Hungary': 'HU',
    'Iceland': 'IS', 'India': 'IN', 'Indonesia': 'ID', 'Iran': 'IR',
    'Ireland': 'IE', 'Israel': 'IL', 'Italy': 'IT', 'Japan': 'JP',
    'Kazakhstan': 'KZ', 'Kenya': 'KE', 'Kosovo': 'XK', 'Kyrgyzstan': 'KG',
    'Latvia': 'LV', 'Lithuania': 'LT', 'Luxembourg': 'LU', 'Mexico': 'MX',
    'Moldova': 'MD', 'Monaco': 'MC', 'Morocco': 'MA', 'Netherlands': 'NL',
    'New Zealand': 'NZ', 'Nigeria': 'NG', 'Norway': 'NO', 'Panama': 'PA',
    'Peru': 'PE', 'Poland': 'PL', 'Portugal': 'PT', 'Romania': 'RO',
    'Russia': 'RU', 'Rwanda': 'RW', 'San Marino': 'SM', 'Serbia': 'RS',
    'Slovakia': 'SK', 'Slovenia': 'SI', 'South Africa': 'ZA', 'Spain': 'ES',
    'Sweden': 'SE', 'Switzerland': 'CH', 'Tajikistan': 'TJ', 'Turkey': 'TR',
    'Turkmenistan': 'TM', 'Ukraine': 'UA', 'United States': 'US', 'USA': 'US',
    'Uzbekistan': 'UZ', 'Venezuela': 'VE', 'Vietnam': 'VN',
}

MONTHS = {
    'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
    'jan':1,'feb':2,'mar':3,'apr':4,'jun':6,'jul':7,'aug':8,
    'sep':9,'oct':10,'nov':11,'dec':12,
}

SPEC_KEYS = {
    'gc': 'gc', 'onedayraces': 'oneday', 'oneday': 'oneday',
    'tt': 'tt', 'timetrial': 'tt', 'sprint': 'sprint',
    'climber': 'climber', 'hills': 'hills', 'hill': 'hills',
}


# -- HTML helpers --------------------------------------------------------------

def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s).strip()

def fetch_html(url, retries=3):
    for attempt in range(retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=20) as r:
                return r.read().decode('utf-8', errors='replace')
        except HTTPError as e:
            if e.code == 404:
                return None
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


# -- Parsers -------------------------------------------------------------------

def parse_rider_page(html, slug):
    """Parse main rider page -> bio dict."""
    profile = {'slug': slug}

    # Photo
    m = re.search(r'<img[^>]+src="(https://www\.procyclingstats\.com/images/riders/[^"]+)"', html)
    if m:
        profile['photo'] = m.group(1)

    # Info block: the borderbox left w65 div contains the li items
    block_m = re.search(r'borderbox left w65(.*?)(?:borderbox clear|<h4)', html, re.DOTALL)
    block = block_m.group(1) if block_m else html

    li_items = re.findall(r'<li[^>]*>(.*?)</li>', block, re.DOTALL)
    for raw_li in li_items:
        li = re.sub(r'\s+', ' ', strip_tags(raw_li)).strip()
        if not li:
            continue

        if li.startswith('Name:'):
            profile['name'] = li[5:].strip()

        elif 'Date of birth' in li or 'born' in li.lower():
            yr_m = re.search(r'\b(19|20)\d{2}\b', li)
            if yr_m:
                day_m   = re.search(r'\b(\d{1,2})\b', li)
                month_m = re.search(r'(january|february|march|april|may|june|july|'
                                    r'august|september|october|november|december|'
                                    r'jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)',
                                    li.lower())
                yr = int(yr_m.group(0))
                if day_m and month_m:
                    day = int(day_m.group(1))
                    mon = MONTHS[month_m.group(1)]
                    profile['dob'] = f'{yr:04d}-{mon:02d}-{day:02d}'
                else:
                    profile['dob'] = str(yr)

        elif 'Nationality' in li:
            m = re.search(r'Nationality\s*[:\s]+(.+)', li)
            if m:
                country = m.group(1).strip()
                profile['nat_name'] = country
                profile['nat'] = COUNTRY_MAP.get(country, country[:2].upper())

        elif 'Weight' in li or 'Height' in li:
            wm = re.search(r'Weight\s*[:\s]*(\d+)\s*kg', li, re.IGNORECASE)
            hm = re.search(r'Height\s*[:\s]*([\d.]+)\s*m', li, re.IGNORECASE)
            if wm: profile['weight'] = int(wm.group(1))
            if hm: profile['height'] = float(hm.group(1))

        else:
            # Specialty scores, e.g. "9983Onedayraces", "7594GC", "10062Climber"
            spec_hits = re.findall(
                r'(\d+)\s*(GC|One\s*day\s*races?|TT|Time\s*trial|Sprint|Climber|Hills?)',
                li, re.IGNORECASE
            )
            if spec_hits:
                if 'specialties' not in profile:
                    profile['specialties'] = {}
                for score, label in spec_hits:
                    raw_key = label.lower().replace(' ', '').replace('races', '').replace('race', '')
                    key = SPEC_KEYS.get(raw_key, raw_key)
                    profile['specialties'][key] = int(score)

    return profile


def parse_wins_page(html):
    """Parse /statistics/wins page -> list of win dicts."""
    if not html:
        return []
    wins = []
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(tds) < 4:
            continue
        cells = [re.sub(r'\s+', ' ', strip_tags(td)).strip() for td in tds]
        nr_s = cells[0]
        if not re.match(r'^\d+$', nr_s):
            continue

        race_s = cells[1] if len(cells) > 1 else ''
        cls_s  = cells[2] if len(cells) > 2 else ''
        date_s = cells[3] if len(cells) > 3 else ''
        cat_s  = cells[4] if len(cells) > 4 else ''

        # Race slug from link
        race_link_m = re.search(r'href="([^"]*(?:race|stage)[^"]*)"', tds[1] if len(tds) > 1 else '', re.IGNORECASE)
        race_slug = race_link_m.group(1).lstrip('/') if race_link_m else None

        wins.append({
            'nr':       int(nr_s),
            'race':     race_s,
            'class':    cls_s,
            'date':     date_s,
            'cat':      cat_s,
            'race_slug': race_slug,
        })

    return sorted(wins, key=lambda w: w['date'], reverse=True)


# -- Slug collection -----------------------------------------------------------

def collect_slugs():
    """Collect all rider slugs from pcs_stats.json and data.json."""
    slugs = set()

    if STATS_FILE.exists():
        try:
            stats = json.loads(STATS_FILE.read_text('utf-8')).get('stats', {})
            for s in stats.values():
                for row in s.get('rows', []):
                    if row.get('type') == 'rider' and row.get('slug'):
                        slugs.add(row['slug'])
                    for key in ('rider_slug', 'rider1_slug', 'rider2_slug'):
                        if row.get(key):
                            slugs.add(row[key])
        except Exception as e:
            print(f'  Warning: could not parse {STATS_FILE.name}: {e}')

    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text('utf-8'))
            for race in data.get('live', []) + data.get('upcoming', []) + data.get('recent', []):
                for rider in race.get('startlist', []):
                    if rider.get('slug'):
                        slugs.add(rider['slug'])
                for stage in race.get('stages', []):
                    for res in stage.get('results', []):
                        if isinstance(res, dict) and res.get('rider_slug'):
                            slugs.add(res['rider_slug'])
                for cls_rows in race.get('classifications', {}).values():
                    if isinstance(cls_rows, list):
                        for row in cls_rows:
                            if isinstance(row, dict) and row.get('rider_slug'):
                                slugs.add(row['rider_slug'])
        except Exception as e:
            print(f'  Warning: could not parse {DATA_FILE.name}: {e}')

    # Filter out obviously bad slugs
    return {s for s in slugs if s and re.match(r'^[a-z0-9\-]+$', s)}


# -- Persistence ---------------------------------------------------------------

def save(riders):
    data = {
        'scraped_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'count': len(riders),
        'riders': riders,
    }
    tmp = PROFILES_FILE.with_suffix('.tmp')
    for _ in range(5):
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), 'utf-8')
            os.replace(tmp, PROFILES_FILE)
            return
        except PermissionError:
            time.sleep(0.5)
    raise RuntimeError(f'Could not write {PROFILES_FILE}')


# -- Main ----------------------------------------------------------------------

def collect_winner_slugs():
    """Collect slugs of riders who have won stages in live/recent races."""
    slugs = set()
    if not DATA_FILE.exists():
        return slugs
    try:
        data = json.loads(DATA_FILE.read_text('utf-8'))
        for race in data.get('live', []) + data.get('recent', []):
            for stage in race.get('stages', []):
                results = stage.get('results', [])
                if results and isinstance(results[0], dict):
                    slug = results[0].get('rider_slug')
                    if slug:
                        slugs.add(slug)
            # Also grab GC leaders
            for cls_rows in race.get('classifications', {}).values():
                if isinstance(cls_rows, list) and cls_rows:
                    row = cls_rows[0]
                    if isinstance(row, dict) and row.get('rider_slug'):
                        slugs.add(row['rider_slug'])
    except Exception as e:
        print(f'Warning: could not parse {DATA_FILE.name}: {e}')
    return {s for s in slugs if s and re.match(r'^[a-z0-9\-]+$', s)}


def update_winners():
    """Re-fetch profiles for all current stage winners and GC leaders."""
    print('Scrape rider profiles — UPDATE WINNERS mode')
    print('=' * 60)

    existing = {}
    if PROFILES_FILE.exists():
        try:
            existing = json.loads(PROFILES_FILE.read_text('utf-8')).get('riders', {})
        except Exception as e:
            print(f'Warning: could not load existing profiles: {e}')

    winner_slugs = collect_winner_slugs()
    print(f'Found {len(winner_slugs)} winner/leader slugs in data.json')
    if not winner_slugs:
        print('No winners found — nothing to do.')
        return

    todo = sorted(winner_slugs)
    ok = err = 0

    for i, slug in enumerate(todo, 1):
        print(f'[{i}/{len(todo)}] {slug:<40}', end='', flush=True)

        html_main = fetch_html(f'https://www.procyclingstats.com/rider/{slug}')
        time.sleep(DELAY)
        if html_main is None:
            print('X (not found)')
            err += 1
            continue

        profile = parse_rider_page(html_main, slug)
        html_wins = fetch_html(f'https://www.procyclingstats.com/rider/{slug}/statistics/wins')
        time.sleep(DELAY)
        profile['wins'] = parse_wins_page(html_wins) if html_wins else []
        existing[slug] = profile
        ok += 1
        print(f'ok  {len(profile["wins"]):>3} wins  {profile.get("nat",""):>3}')

    save(existing)
    print(f'\nDone. {ok} updated, {err} errors.')

    # Auto git commit + push (with pull-rebase retry on rejection)
    import subprocess
    try:
        subprocess.run(['git', 'add', 'rider_profiles.json'], cwd=BASE, check=True)
        result = subprocess.run(['git', 'diff', '--staged', '--quiet'], cwd=BASE)
        if result.returncode != 0:
            subprocess.run(
                ['git', 'commit', '-m', f'data: refresh winner profiles ({ok} riders)'],
                cwd=BASE, check=True
            )
            push = subprocess.run(['git', 'push'], cwd=BASE)
            if push.returncode != 0:
                print('Push rejected — pulling and retrying...')
                subprocess.run(['git', 'pull', '--rebase', 'origin', 'main'], cwd=BASE, check=True)
                subprocess.run(['git', 'push'], cwd=BASE, check=True)
            print('Committed and pushed rider_profiles.json')
        else:
            print('No changes to commit.')
    except Exception as e:
        print(f'Git error: {e}')
        print('Manual push: git add rider_profiles.json && git commit -m "data: winner profiles" && git push')


def main():
    fix_empty = '--fix-empty' in sys.argv
    fetch_all = '--all' in sys.argv
    update_win = '--update-winners' in sys.argv

    if update_win:
        update_winners()
        return

    # Load existing
    existing = {}
    if PROFILES_FILE.exists():
        try:
            existing = json.loads(PROFILES_FILE.read_text('utf-8')).get('riders', {})
            print(f'Loaded {len(existing)} existing profiles from {PROFILES_FILE.name}')
        except Exception as e:
            print(f'Warning: could not load existing profiles: {e}')

    all_slugs = collect_slugs()
    print(f'Found {len(all_slugs)} unique rider slugs across pcs_stats.json + data.json')

    if fetch_all:
        todo = sorted(all_slugs)
        print(f'--all: re-fetching all {len(todo)} riders')
    elif fix_empty:
        todo = sorted(s for s in all_slugs if not existing.get(s, {}).get('wins'))
        print(f'--fix-empty: fetching {len(todo)} riders with 0 wins')
    else:
        todo = sorted(s for s in all_slugs if s not in existing)
        print(f'Fetching {len(todo)} new riders (skipping {len(all_slugs)-len(todo)} already done)')

    if not todo:
        print('Nothing to do — all riders already fetched.')
        print(f'Use --fix-empty to retry riders with 0 wins, --all to re-fetch everything.')
        return

    ok = err = 0
    start = time.time()

    for i, slug in enumerate(todo, 1):
        elapsed = time.time() - start
        eta = (elapsed / i) * (len(todo) - i) if i > 1 else 0
        print(f'[{i}/{len(todo)}] {slug:<40}', end='', flush=True)

        # Main profile page
        html_main = fetch_html(f'https://www.procyclingstats.com/rider/{slug}')
        time.sleep(DELAY)

        if html_main is None:
            print('X (not found)')
            err += 1
            # Store a stub so we don't retry on next run
            existing[slug] = {'slug': slug, 'wins': [], 'error': 'not_found'}
            continue

        profile = parse_rider_page(html_main, slug)

        # Wins page
        html_wins = fetch_html(f'https://www.procyclingstats.com/rider/{slug}/statistics/wins')
        time.sleep(DELAY)
        wins = parse_wins_page(html_wins) if html_wins else []
        profile['wins'] = wins

        existing[slug] = profile
        ok += 1

        eta_str = f'{eta:.0f}s left' if eta > 0 else ''
        print(f'ok  {len(wins):>3} wins  {profile.get("nat",""):>3}  {eta_str}')

        # Save every 20 riders
        if ok % 20 == 0:
            save(existing)
            print(f'  -> saved checkpoint ({len(existing)} riders)')

    save(existing)
    total_wins = sum(len(r.get('wins', [])) for r in existing.values())
    print(f'\nDone. {ok} fetched, {err} errors.')
    print(f'Total: {len(existing)} rider profiles, {total_wins} career wins stored.')
    print(f'\ngit add rider_profiles.json && git commit -m "data: rider profiles ({len(existing)} riders)" && git push')


if __name__ == '__main__':
    main()
