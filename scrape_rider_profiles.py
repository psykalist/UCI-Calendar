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
from db_safe import safe_json_write, db_upsert, pre_scrape_check, get_db, ensure_schema
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

    # Photo — PCS now serves relative URLs like "images/riders/vg/dq/slug.jpg"
    m = re.search(r'src="([^"]*images/riders[^"]*\.(?:jpg|png|webp))"', html)
    if m:
        src = m.group(1)
        if src.startswith('http'):
            profile['photo'] = src
        else:
            profile['photo'] = 'https://www.procyclingstats.com/' + src.lstrip('/')

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


def parse_team_history(html):
    """Parse team history from rider profile page HTML.
    Returns list of {year, team, team_slug} sorted newest-first."""
    if not html:
        return []
    teams = []
    seen_years = set()

    # PCS HTML: <a href="team/uae-team-emirates-xrg-2026">UAE Team Emirates - XRG</a>
    # Note: href is relative with NO leading slash
    team_pattern = re.compile(
        r'href=["\'](?:https://www\.procyclingstats\.com)?/?team/([^"\']+)["\'][^>]*>([^<]+)<',
        re.IGNORECASE
    )
    for m in team_pattern.finditer(html):
        team_slug = m.group(1).strip()
        team_name = strip_tags(m.group(2)).strip()
        # Extract year from slug (e.g. "uae-team-emirates-xrg-2026" → 2026)
        yr_m = re.search(r'-(20\d{2})$', team_slug)
        if yr_m and team_name:
            yr = int(yr_m.group(1))
            if yr not in seen_years:
                seen_years.add(yr)
                teams.append({'year': yr, 'team': team_name, 'team_slug': team_slug})

    # Fallback: plain text "YEAR\nTeam Name (CAT)"
    if not teams:
        for m in re.finditer(r'\b(20\d{2})\b\s+([A-Z][A-Za-z0-9 \'\-\.]{4,60}?)(?:\s*\((?:WT|PT|CT|CC|CLUB)\))?(?:\n|<)', html):
            yr = int(m.group(1))
            name = m.group(2).strip()
            if yr not in seen_years and len(name) > 4:
                seen_years.add(yr)
                teams.append({'year': yr, 'team': name, 'team_slug': None})

    return sorted(teams, key=lambda t: t['year'], reverse=True)


def parse_season_results(html):
    """Parse /rider/{slug}/results page -> list of result dicts for current season.
    PCS table columns: # | date | result | race | class | km | pcs_pts | uci_pts | vert
    Each dict: {date, race, stage_pos, distance_km, pcs_points, uci_points}
    """
    if not html:
        return []
    results = []

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        cells_raw = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        cells = [re.sub(r'\s+', ' ', strip_tags(c)).strip() for c in cells_raw]
        # Expect at least 7 cols: #, date, pos, race, class, km, pcs_pts
        if len(cells) < 7:
            continue

        # Col 1: ISO date e.g. "2026-06-12"
        date_str = cells[1]
        if not re.match(r'\d{4}-\d{2}-\d{2}', date_str):
            continue

        pos_raw  = cells[2]   # "1", "DNS", "DNF", "117" etc.
        race_name = re.sub(r'\s*more\s*$', '', cells[3]).strip()
        dist_s   = cells[5]
        pcs_s    = cells[6]
        uci_s    = cells[7] if len(cells) > 7 else ''

        stage_pos = int(pos_raw) if re.match(r'^\d+$', pos_raw) else None
        dist      = float(dist_s) if re.match(r'^\d+\.?\d*$', dist_s) else None
        pcs_pts   = int(pcs_s)    if re.match(r'^\d+$', pcs_s) else 0
        uci_pts   = float(uci_s)  if re.match(r'^\d+\.?\d*$', uci_s) else 0

        results.append({
            'date':        date_str,
            'race':        race_name,
            'stage_pos':   stage_pos,
            'distance_km': dist,
            'pcs_points':  pcs_pts,
            'uci_points':  uci_pts,
        })

    return results


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

def git_commit_push(msg):
    """Stage rider_profiles.json, commit and push. Clears stale git lock files first."""
    import subprocess
    git_dir = BASE / '.git'
    for lock in ('index.lock', 'HEAD.lock', 'config.lock'):
        p = git_dir / lock
        try:
            if p.exists():
                p.unlink()
                print(f'Removed stale {lock}')
        except Exception:
            pass  # non-fatal if we can't remove it

    try:
        subprocess.run(['git', 'add', 'rider_profiles.json'], cwd=BASE, check=True)
        result = subprocess.run(['git', 'diff', '--staged', '--quiet'], cwd=BASE)
        if result.returncode != 0:
            subprocess.run(['git', 'commit', '-m', msg], cwd=BASE, check=True)
            push = subprocess.run(['git', 'push'], cwd=BASE)
            if push.returncode != 0:
                print('Push rejected - pulling and retrying...')
                subprocess.run(['git', 'pull', '--rebase', 'origin', 'main'], cwd=BASE, check=True)
                subprocess.run(['git', 'push'], cwd=BASE, check=True)
            print('Committed and pushed rider_profiles.json')
        else:
            print('No changes to commit.')
    except Exception as e:
        print('Git error: ' + str(e))
        print('Manual push: git add rider_profiles.json && git commit -m "' + msg + '" && git push')


def save(riders):
    data = {
        'scraped_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'count': len(riders),
        'riders': riders,
    }
    safe_json_write(
        PROFILES_FILE,
        data,
        required_keys=['riders', 'count', 'scraped_at'],
        min_ratio=0.85,
        label='rider_profiles.json',
    )


def save_rider_to_db(conn, slug, profile):
    """Write one rider profile to cycling.db with read-back verification."""
    sp = profile.get('specialties', {})
    row = {
        'slug':                 slug,
        'name':                 profile.get('name', slug),
        'nat':                  profile.get('nat', ''),
        'nat_name':             profile.get('nat_name', ''),
        'dob':                  profile.get('dob', ''),
        'height':               profile.get('height'),
        'weight':               profile.get('weight'),
        'photo_url':            profile.get('photo', ''),
        'sp_oneday':            sp.get('oneday', 0),
        'sp_gc':                sp.get('gc', 0),
        'sp_tt':                sp.get('tt', 0),
        'sp_sprint':            sp.get('sprint', 0),
        'sp_climber':           sp.get('climber', 0),
        'sp_hills':             sp.get('hills', 0),
        'wins_json':            json.dumps(profile.get('wins', []), ensure_ascii=False),
        'team_history_json':    json.dumps(profile.get('team_history', []), ensure_ascii=False),
        'season_results_json':  json.dumps(profile.get('season_results', []), ensure_ascii=False),
        'fetched_at':           profile.get('fetched_at', ''),
    }
    db_upsert(conn, 'riders', row, pk_col='slug')


# -- Main ----------------------------------------------------------------------

def collect_winner_slugs():
    """Collect slugs of riders who have won stages in live/recent races."""
    slugs = set()
    if not DATA_FILE.exists():
        return slugs

    def slug_from_url(url):
        """Extract slug from /profile/{slug} or /rider/{slug} URLs."""
        if not url:
            return None
        return url.strip().rstrip('/').split('/')[-1] or None

    try:
        data = json.loads(DATA_FILE.read_text('utf-8'))
        # data.json stores all races under 'races' with a 'status' field;
        # also check legacy top-level 'live'/'recent' lists if present.
        all_races = [r for r in data.get('races', [])
                     if r.get('status') in ('live', 'recent')]
        for legacy_key in ('live', 'recent'):
            val = data.get(legacy_key)
            if isinstance(val, list):
                all_races += val

        cls_keys = ['gc_top10', 'points_top10', 'kom_top10', 'youth_top10']
        for race in all_races:
            # Stage winners — results[0]['slug'] is the winner
            for stage in race.get('stages', []):
                results = stage.get('results', [])
                if results and isinstance(results[0], dict):
                    s = results[0].get('slug')
                    if s:
                        slugs.add(s)
                # Legacy: top10[0]['rider_url']
                top10 = stage.get('top10', [])
                if top10 and isinstance(top10[0], dict):
                    s = slug_from_url(top10[0].get('rider_url'))
                    if s:
                        slugs.add(s)
            # Classification leaders (GC, points, KOM, youth)
            for key in cls_keys:
                rows = race.get(key, [])
                if rows and isinstance(rows[0], dict):
                    s = rows[0].get('slug') or slug_from_url(rows[0].get('rider_url'))
                    if s:
                        slugs.add(s)
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
        profile['team_history'] = parse_team_history(html_main)

        html_wins = fetch_html(f'https://www.procyclingstats.com/rider/{slug}/statistics/wins')
        time.sleep(DELAY)
        profile['wins'] = parse_wins_page(html_wins) if html_wins else []

        html_results = fetch_html(f'https://www.procyclingstats.com/rider/{slug}/results')
        time.sleep(DELAY)
        profile['season_results'] = parse_season_results(html_results) if html_results else []
        profile['fetched_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        existing[slug] = profile
        ok += 1
        print(f'ok  {len(profile["wins"]):>3} wins  {len(profile.get("team_history",[]))} teams  {profile.get("nat",""):>3}')

    save(existing)
    print(f'\nDone. {ok} updated, {err} errors.')
    git_commit_push('data: refresh winner profiles (' + str(ok) + ' riders)')


def main():
    fix_empty  = '--fix-empty' in sys.argv
    fetch_all  = '--all' in sys.argv
    update_win = '--update-winners' in sys.argv

    if update_win:
        update_winners()
        return

    # ── DB setup ──────────────────────────────────────────────────────────────
    db_conn = get_db()
    ensure_schema(db_conn)

    existing = {}
    if PROFILES_FILE.exists():
        try:
            existing = json.loads(PROFILES_FILE.read_text('utf-8')).get('riders', {})
            print('Loaded ' + str(len(existing)) + ' existing profiles')
        except Exception as e:
            print('Warning: could not load existing profiles: ' + str(e))

    # ── Pre-scrape sample check ───────────────────────────────────────────────
    def validate_rider(r):
        if not isinstance(r, dict):
            raise ValueError('not a dict')
        if not r.get('slug'):
            raise ValueError('missing slug')
        if 'fetched_at' not in r:
            raise ValueError('missing fetched_at')

    if existing:
        pre_scrape_check(existing, sample_size=5, validator=validate_rider, label='rider_profiles.json')

    all_slugs = collect_slugs()
    print('Found ' + str(len(all_slugs)) + ' unique rider slugs')

    if fetch_all:
        todo = sorted(all_slugs)
    elif fix_empty:
        todo = sorted(s for s in all_slugs if not existing.get(s, {}).get('wins'))
        print('--fix-empty: fetching ' + str(len(todo)) + ' riders with 0 wins')
    else:
        todo = sorted(s for s in all_slugs if s not in existing)
        print('Fetching ' + str(len(todo)) + ' new riders (skipping ' + str(len(all_slugs)-len(todo)) + ' already done)')

    if not todo:
        print('Nothing to do -- all riders already fetched.')
        return

    ok = err = 0
    start = time.time()

    for i, slug in enumerate(todo, 1):
        print('[' + str(i) + '/' + str(len(todo)) + '] ' + slug.ljust(40), end='', flush=True)

        html_main = fetch_html('https://www.procyclingstats.com/rider/' + slug)
        time.sleep(DELAY)

        if html_main is None:
            print('X (not found)')
            err += 1
            existing[slug] = {'slug': slug, 'wins': [], 'error': 'not_found'}
            continue

        profile = parse_rider_page(html_main, slug)
        profile['team_history'] = parse_team_history(html_main)

        html_wins = fetch_html('https://www.procyclingstats.com/rider/' + slug + '/statistics/wins')
        time.sleep(DELAY)
        profile['wins'] = parse_wins_page(html_wins) if html_wins else []

        html_results = fetch_html('https://www.procyclingstats.com/rider/' + slug + '/results')
        time.sleep(DELAY)
        profile['season_results'] = parse_season_results(html_results) if html_results else []
        profile['fetched_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        existing[slug] = profile

        # Write to DB with read-back verification
        try:
            save_rider_to_db(db_conn, slug, profile)
        except Exception as db_err:
            print(f'  ⚠ DB write failed for {slug}: {db_err}', flush=True)

        ok += 1
        print('ok  ' + str(len(profile['wins'])).rjust(3) + ' wins  ' + str(len(profile.get('team_history',[]))).rjust(2) + ' teams')

    db_conn.close()
    save(existing)
    print('Done. ' + str(ok) + ' updated, ' + str(err) + ' errors.')
    git_commit_push('data: refresh rider profiles (' + str(ok) + ' riders)')


if __name__ == '__main__':
    main()
