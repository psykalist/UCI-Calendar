#!/usr/bin/env python3
"""
scrape_letour.py — Scrape letour.fr stage pages for Tour de France 2026.

For each stage fetches:
  /en/stage-{N}  →  route map image (cartepot), elevation profile (profils),
                     full roadbook table (time schedule)

Output:
  letour_stages.json  — raw scraped data per stage
  data.json           — roadbook + letour images injected into TDF stage entries

Usage:
  py scrape_letour.py              # scrape all stages
  py scrape_letour.py --stage 5   # single stage
  py scrape_letour.py --no-inject # scrape only, don't update data.json

Run locally — letour.fr may block cloud IPs.
After running: git add letour_stages.json data.json && git commit -m "data: TDF letour maps + roadbook" && git push
"""

import re, time, json, os, sys, datetime, argparse
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from db_safe import safe_json_write, db_upsert, pre_scrape_check, get_db, ensure_schema

BASE      = Path(__file__).parent
LETOUR    = 'https://www.letour.fr/en/stage-'
OUT_FILE  = BASE / 'letour_stages.json'
DATA_FILE = BASE / 'data.json'
DELAY     = 1.5   # seconds between requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.letour.fr/',
}


# ── HTTP ──────────────────────────────────────────────────────────────────────

def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=20) as r:
                return r.read().decode('utf-8', errors='replace')
        except HTTPError as e:
            if e.code == 404:
                return None
            print(f'    HTTP {e.code} — retry {attempt+1}')
            time.sleep(2 ** attempt)
        except URLError as e:
            print(f'    URLError: {e} — retry {attempt+1}')
            time.sleep(2 ** attempt)
    return None


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_stage(html, stage_num):
    """Parse a letour.fr stage page → dict with map_img, profile_img, roadbook."""
    if not html:
        return {}

    data = {'stage_num': stage_num}

    # Route map image — URL contains 'cartepot'
    m = re.search(r'(https://img\.aso\.fr/[^\s"\'<>)]+cartepot[^\s"\'<>)]+)', html)
    if m:
        data['map_img'] = m.group(1).rstrip('&').rstrip('"').split('"')[0]

    # Elevation profile — URL contains 'profils' or 'profile'
    m = re.search(r'(https://img\.aso\.fr/[^\s"\'<>)]+profil[^\s"\'<>)]+)', html)
    if m:
        data['profile_img'] = m.group(1).rstrip('&').rstrip('"').split('"')[0]

    # Stage title e.g. "Barcelone > Barcelone"
    m = re.search(r'<title>Stage \d+\s*[-–]\s*([^<]+)</title>', html, re.IGNORECASE)
    if m:
        data['title'] = m.group(1).strip()

    # Start time (FIRST START / LAST ARRIVAL block)
    m = re.search(r'FIRST START\s*[:\s]*(\d{1,2}:\d{2})', html, re.IGNORECASE)
    if m:
        data['first_start'] = m.group(1)
    m = re.search(r'LAST ARRIVAL\s*[:\s]*(\d{1,2}:\d{2})', html, re.IGNORECASE)
    if m:
        data['last_arrival'] = m.group(1)

    # Roadbook — parse table.sporting__table
    roadbook = parse_roadbook(html)
    if roadbook:
        data['roadbook'] = roadbook

    return data


def parse_roadbook(html):
    """Extract the sporting__table rows → list of location dicts."""
    # Find the table body content
    m = re.search(r'<table[^>]*sporting__table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        return []

    table_html = m.group(1)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)
    roadbook = []

    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        # Strip tags from each cell
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        # Expect 7 cols: [icon, location, km_finish, km_start, caravan, peloton, director]
        if len(cells) < 4:
            continue
        location = cells[1] if len(cells) > 1 else ''
        if not location or location in ('From the finish', 'From the start', 'Caravan', 'P', 'D'):
            continue  # skip header row
        entry = {'location': location}
        if len(cells) > 2 and cells[2]:
            try: entry['km_finish'] = float(cells[2])
            except ValueError: pass
        if len(cells) > 3 and cells[3]:
            try: entry['km_start'] = float(cells[3])
            except ValueError: pass
        if len(cells) > 4 and cells[4]: entry['caravan_time'] = cells[4]
        if len(cells) > 5 and cells[5]: entry['peloton_time'] = cells[5]
        if len(cells) > 6 and cells[6]: entry['director_time'] = cells[6]
        roadbook.append(entry)

    return roadbook


# ── data.json injection ───────────────────────────────────────────────────────

def inject_into_data(stages_data):
    """Inject letour data into the TDF entries in data.json."""
    if not DATA_FILE.exists():
        print('data.json not found — skipping injection')
        return

    with open(DATA_FILE, 'rb') as f:
        content = f.read().replace(b'\x00', b'').decode('utf-8')
    decoder = json.JSONDecoder()
    d, _ = decoder.raw_decode(content)

    tdf_slug_patterns = ['tour-de-france', 'tdf']
    updated = 0

    for bucket in ('live', 'upcoming', 'recent'):
        for race in d.get(bucket, []):
            slug = race.get('slug', '')
            if not any(p in slug for p in tdf_slug_patterns):
                continue
            for stage in race.get('stages', []):
                snum = stage.get('num')
                sdata = stages_data.get(snum)
                if not sdata:
                    continue
                # Inject map/profile images (only if not already set from cyclingflash)
                if sdata.get('map_img'):
                    stage['letour_map_img'] = sdata['map_img']
                    if not stage.get('route_img'):
                        stage['route_img'] = sdata['map_img']
                if sdata.get('profile_img'):
                    stage['letour_profile_img'] = sdata['profile_img']
                    if not stage.get('height_profile_img'):
                        stage['height_profile_img'] = sdata['profile_img']
                if sdata.get('roadbook'):
                    stage['roadbook'] = sdata['roadbook']
                if sdata.get('first_start') and not stage.get('start_time'):
                    stage['start_time'] = sdata['first_start']
                updated += 1

    if updated:
        safe_json_write(
            DATA_FILE, d,
            required_keys=['live', 'upcoming', 'recent', 'scraped_at'],
            min_ratio=0.90,
            label='data.json (letour inject)',
        )
        print(f'Injected letour data into {updated} TDF stages in data.json')
    else:
        print('No TDF stages found in data.json to inject into')


# ── Main ──────────────────────────────────────────────────────────────────────

def save_stage_to_db(conn, stage_num, data):
    """Write one letour stage to cycling.db stages table with read-back verification."""
    # Find the stage row by stage_num in the TDF race
    row = conn.execute(
        "SELECT id, race_id FROM stages WHERE stage_num=? AND race_id LIKE '%tour-de-france%'",
        (stage_num,)
    ).fetchone()
    if row is None:
        return  # Stage not in DB yet — will be added by main scraper later

    upsert_row = {
        'id':           row['id'],
        'race_id':      row['race_id'],
        'stage_num':    stage_num,
        'map_img':      data.get('map_img', ''),
        'profile_img':  data.get('profile_img', ''),
        'roadbook_json':json.dumps(data.get('roadbook', []), ensure_ascii=False),
        'start_time':   data.get('first_start', ''),
    }
    db_upsert(conn, 'stages', upsert_row, pk_col='id')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=int, help='Scrape a single stage number')
    parser.add_argument('--no-inject', action='store_true', help='Skip data.json update')
    parser.add_argument('--total', type=int, default=21, help='Total stages (default 21)')
    args = parser.parse_args()

    # ── DB setup ──────────────────────────────────────────────────────────────
    db_conn = get_db()
    ensure_schema(db_conn)

    # Load existing letour data if any
    existing = {}
    if OUT_FILE.exists():
        try:
            existing = json.loads(OUT_FILE.read_text('utf-8'))
        except Exception:
            pass

    # ── Pre-scrape sample check ───────────────────────────────────────────────
    def validate_stage(s):
        if not isinstance(s, dict):
            raise ValueError('not a dict')
        if 'stage_num' not in s:
            raise ValueError('missing stage_num')

    if existing:
        pre_scrape_check(
            list(existing.values()), sample_size=min(3, len(existing)),
            validator=validate_stage, label='letour_stages.json'
        )

    stage_nums = [args.stage] if args.stage else list(range(1, args.total + 1))
    print(f'Scraping {len(stage_nums)} stage(s) from letour.fr...')

    results = dict(existing)
    ok = err = 0

    for n in stage_nums:
        print(f'  Stage {n:>2}', end='  ', flush=True)
        html = fetch(f'{LETOUR}{n}')
        time.sleep(DELAY)

        if html is None:
            print('not found')
            err += 1
            continue

        data = parse_stage(html, n)
        results[n] = data

        # Write to DB with read-back
        try:
            save_stage_to_db(db_conn, n, data)
        except Exception as db_err:
            print(f'  ⚠ DB write failed for stage {n}: {db_err}', flush=True)

        ok += 1
        map_ok     = '✓' if data.get('map_img')     else '✗'
        profile_ok = '✓' if data.get('profile_img') else '✗'
        rb_count   = len(data.get('roadbook', []))
        print(f'map:{map_ok} profile:{profile_ok} roadbook:{rb_count} rows')

    db_conn.close()

    # Save letour_stages.json with full validation
    safe_json_write(
        OUT_FILE,
        results,
        required_keys=[],   # keys are stage numbers, no fixed required keys
        min_ratio=0.80,
        label='letour_stages.json',
    )
    print(f'\nSaved {len(results)} stages to {OUT_FILE.name}')
    print(f'Done: {ok} scraped, {err} errors')

    # Inject into data.json
    if not args.no_inject:
        # Convert string keys back to int (JSON keys are always strings)
        int_results = {int(k): v for k, v in results.items()}
        inject_into_data(int_results)

    # Git commit
    import subprocess
    git_dir = BASE / '.git'
    for lock in ('index.lock', 'HEAD.lock'):
        try:
            lp = git_dir / lock
            if lp.exists(): lp.unlink()
        except Exception:
            pass
    try:
        files = ['letour_stages.json']
        if not args.no_inject:
            files.append('data.json')
        subprocess.run(['git', 'add'] + files, cwd=BASE, check=True)
        result = subprocess.run(['git', 'diff', '--staged', '--quiet'], cwd=BASE)
        if result.returncode != 0:
            msg = f'data: TDF letour maps + roadbook ({ok} stages)'
            subprocess.run(['git', 'commit', '-m', msg], cwd=BASE, check=True)
            push = subprocess.run(['git', 'push'], cwd=BASE)
            if push.returncode != 0:
                subprocess.run(['git', 'pull', '--rebase', 'origin', 'main'], cwd=BASE, check=True)
                subprocess.run(['git', 'push'], cwd=BASE, check=True)
            print('Committed and pushed')
        else:
            print('No changes to commit')
    except Exception as e:
        print('Git error: ' + str(e))
        print('Manual: git add letour_stages.json data.json && git commit -m "data: TDF letour" && git push')


if __name__ == '__main__':
    main()
