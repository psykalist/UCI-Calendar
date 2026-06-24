#!/usr/bin/env python3
"""
import_to_db.py — UCI Cycling Data → SQLite

Run this after every scraper.py run to keep cycling.db in sync:
    py scraper.py
    py import_to_db.py

The database is append-safe (INSERT OR REPLACE throughout).
It never removes existing rows — only adds or updates.
Build happens in /tmp to avoid Windows-mount I/O limits, then copies over.
"""

import json, sqlite3, shutil, os
from datetime import datetime

BASE    = os.path.dirname(os.path.abspath(__file__))
TMP_DB  = '/tmp/cycling_import.db'  # build here
DEST_DB = os.path.join(BASE, 'cycling.db')
NOW     = datetime.utcnow().isoformat()


# ── Schema ─────────────────────────────────────────────────────────────────────

SCHEMA = '''
CREATE TABLE IF NOT EXISTS races (
    id               TEXT PRIMARY KEY,
    slug             TEXT,
    cf_slug          TEXT,
    name             TEXT NOT NULL,
    year             INTEGER,
    category         TEXT,
    start_date       TEXT,
    end_date         TEXT,
    status           TEXT,
    race_type        TEXT,
    total_stages     INTEGER DEFAULT 1,
    stages_completed INTEGER DEFAULT 0,
    winner_name      TEXT,
    winner_flag      TEXT,
    winner_nat       TEXT,
    gc_leader        TEXT,
    official_url     TEXT,
    scraped_at       TEXT
);
CREATE TABLE IF NOT EXISTS stages (
    id               TEXT PRIMARY KEY,
    race_id          TEXT REFERENCES races(id),
    stage_num        INTEGER,
    label            TEXT,
    stage_type       TEXT,
    date_str         TEXT,
    start_town       TEXT,
    finish_town      TEXT,
    distance_km      REAL,
    elevation_m      INTEGER,
    winner_name      TEXT,
    winner_nat       TEXT,
    winner_flag      TEXT,
    height_profile_img TEXT,
    route_img        TEXT,
    UNIQUE(race_id, stage_num)
);
CREATE TABLE IF NOT EXISTS stage_results (
    id          TEXT PRIMARY KEY,
    stage_id    TEXT REFERENCES stages(id),
    race_id     TEXT REFERENCES races(id),
    rank        INTEGER,
    rider_slug  TEXT,
    rider_name  TEXT,
    team        TEXT,
    nat_code    TEXT,
    flag        TEXT,
    time_gap    TEXT,
    UNIQUE(stage_id, rank)
);
CREATE TABLE IF NOT EXISTS race_results (
    id          TEXT PRIMARY KEY,
    race_id     TEXT REFERENCES races(id),
    rank        INTEGER,
    rider_slug  TEXT,
    rider_name  TEXT,
    team        TEXT,
    nat_code    TEXT,
    flag        TEXT,
    time_gap    TEXT,
    UNIQUE(race_id, rank)
);
CREATE TABLE IF NOT EXISTS classifications (
    id          TEXT PRIMARY KEY,
    race_id     TEXT REFERENCES races(id),
    type        TEXT,
    rank        INTEGER,
    rider_slug  TEXT,
    rider_name  TEXT,
    team        TEXT,
    nat_code    TEXT,
    flag        TEXT,
    value       TEXT,
    UNIQUE(race_id, type, rank)
);
CREATE TABLE IF NOT EXISTS riders (
    slug        TEXT PRIMARY KEY,
    name        TEXT,
    nat         TEXT,
    nat_name    TEXT,
    dob         TEXT,
    height      REAL,
    weight      REAL,
    photo_url   TEXT,
    sp_oneday   INTEGER,
    sp_gc       INTEGER,
    sp_tt       INTEGER,
    sp_sprint   INTEGER,
    sp_climber  INTEGER,
    sp_hills    INTEGER,
    fetched_at  TEXT
);
CREATE TABLE IF NOT EXISTS rider_wins (
    id          TEXT PRIMARY KEY,
    rider_slug  TEXT REFERENCES riders(slug),
    year        TEXT,
    date        TEXT,
    race        TEXT,
    cat         TEXT
);
CREATE TABLE IF NOT EXISTS teams (
    slug        TEXT PRIMARY KEY,
    name        TEXT,
    category    TEXT,
    logo_url    TEXT,
    jersey_url  TEXT
);
CREATE TABLE IF NOT EXISTS team_riders (
    id          TEXT PRIMARY KEY,
    team_slug   TEXT,
    rider_slug  TEXT,
    UNIQUE(team_slug, rider_slug)
);
CREATE INDEX IF NOT EXISTS idx_sr_race   ON stage_results(race_id);
CREATE INDEX IF NOT EXISTS idx_sr_stage  ON stage_results(stage_id);
CREATE INDEX IF NOT EXISTS idx_sr_rider  ON stage_results(rider_slug);
CREATE INDEX IF NOT EXISTS idx_rr_race   ON race_results(race_id);
CREATE INDEX IF NOT EXISTS idx_cl_race   ON classifications(race_id);
CREATE INDEX IF NOT EXISTS idx_cl_type   ON classifications(race_id, type);
CREATE INDEX IF NOT EXISTS idx_st_race   ON stages(race_id);
CREATE INDEX IF NOT EXISTS idx_rw_rider  ON rider_wins(rider_slug);
CREATE TABLE IF NOT EXISTS race_palmares (
    id           TEXT PRIMARY KEY,
    race_slug    TEXT NOT NULL,
    year         INTEGER NOT NULL,
    winner       TEXT,
    winner_slug  TEXT,
    second       TEXT,
    second_slug  TEXT,
    third        TEXT,
    third_slug   TEXT,
    UNIQUE(race_slug, year)
);
CREATE INDEX IF NOT EXISTS idx_rp_race ON race_palmares(race_slug);
'''

def open_db():
    # Seed from existing DB if present, else create fresh
    if os.path.exists(DEST_DB):
        shutil.copy2(DEST_DB, TMP_DB)
        print(f'  Seeded from existing cycling.db ({os.path.getsize(DEST_DB)//1024} KB)')
    elif os.path.exists(TMP_DB):
        os.remove(TMP_DB)
    conn = sqlite3.connect(TMP_DB)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def slug_from_url(url):
    return (url or '').replace('/profile/', '').strip('/')


# ── Import data.json ───────────────────────────────────────────────────────────

def import_data_json(conn):
    path = os.path.join(BASE, 'data.json')
    if not os.path.exists(path):
        print('  ✗ data.json not found — skipping')
        return
    with open(path, encoding='utf-8') as f:
        d = json.load(f)

    # Build rider→team lookup from teams section
    slug_to_team = {}
    for team in d.get('teams', []):
        tname = team.get('name', '')
        tslug = team.get('slug', '')
        for rider in team.get('riders', []):
            rslug = rider.get('slug', '')
            if rslug:
                slug_to_team[rslug] = tname
        # Upsert team
        conn.execute(
            'INSERT OR REPLACE INTO teams (slug, name, category, logo_url, jersey_url) VALUES (?,?,?,?,?)',
            [tslug, tname, team.get('cat', ''), team.get('logo', ''), team.get('jersey', '')]
        )
        for rider in team.get('riders', []):
            rslug = rider.get('slug', '')
            if rslug:
                conn.execute(
                    'INSERT OR REPLACE INTO team_riders (id, team_slug, rider_slug) VALUES (?,?,?)',
                    [f'{tslug}_{rslug}', tslug, rslug]
                )
                conn.execute(
                    'INSERT OR IGNORE INTO riders (slug, name, nat) VALUES (?,?,?)',
                    [rslug, rider.get('name', ''), rider.get('nat', '')]
                )

    rc = sc = results = cl = 0
    # data.json stores all races in d['races'] with a 'status' field.
    # Legacy top-level 'live'/'upcoming'/'recent' lists are also checked for compatibility.
    all_races = list(d.get('races', []))
    for section in ['live', 'upcoming', 'recent']:
        val = d.get(section)
        if isinstance(val, list):
            all_races += val
    for race in all_races:
            slug    = race.get('slug') or race.get('cf_slug', '')
            cf_slug = race.get('cf_slug', slug)
            ts      = race.get('total_stages', 1)
            race_id = cf_slug or slug

            conn.execute('''INSERT OR REPLACE INTO races
                (id,slug,cf_slug,name,year,category,start_date,end_date,
                 status,race_type,total_stages,stages_completed,
                 winner_name,winner_flag,winner_nat,gc_leader,official_url,scraped_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', [
                race_id, slug, cf_slug, race.get('name', ''), race.get('year', 2026),
                race.get('category', ''), race.get('start_date', ''), race.get('end_date', ''),
                race.get('status', section), 'stage' if ts > 1 else 'oneday',
                ts, race.get('stages_completed', 0),
                race.get('winner') or race.get('last_stage_winner', ''),
                race.get('winner_flag', '') or race.get('last_stage_winner_flag', ''),
                race.get('winner_nat', ''), race.get('gc_leader', ''),
                race.get('official_url', ''), NOW
            ])
            rc += 1

            # One-day top10
            for row in race.get('top10', []):
                rslug = slug_from_url(row.get('rider_url', ''))
                conn.execute('''INSERT OR REPLACE INTO race_results
                    (id,race_id,rank,rider_slug,rider_name,team,nat_code,flag,time_gap)
                    VALUES(?,?,?,?,?,?,?,?,?)''', [
                    f'{race_id}-r{row["rank"]}', race_id, row['rank'],
                    rslug, row.get('name', ''), row.get('team') or slug_to_team.get(rslug, ''),
                    row.get('nat_code', ''), row.get('flag', ''), row.get('time_gap', '')
                ])
                results += 1
                if rslug:
                    conn.execute('INSERT OR IGNORE INTO riders(slug,name) VALUES(?,?)',
                                 [rslug, row.get('name', '')])

            # Stages
            for stage in race.get('stages', []):
                n   = stage.get('num', 0)
                sid = f'{race_id}-stage-{n}'
                conn.execute('''INSERT OR REPLACE INTO stages
                    (id,race_id,stage_num,label,stage_type,date_str,
                     start_town,finish_town,distance_km,elevation_m,
                     winner_name,winner_nat,winner_flag,height_profile_img,route_img)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', [
                    sid, race_id, n, stage.get('label', ''), stage.get('type', stage.get('stage_type', '')),
                    stage.get('date', stage.get('date_str', '')), stage.get('from', stage.get('start_town', '')),
                    stage.get('to', stage.get('finish_town', '')), stage.get('km', stage.get('distance_km')),
                    stage.get('elev', stage.get('elevation_m')), stage.get('winner', ''),
                    stage.get('winnerNat', stage.get('winner_nat', '')),
                    stage.get('winnerFlag', stage.get('winner_flag', '')),
                    stage.get('profileImg', stage.get('height_profile_img', '')),
                    stage.get('routeImg', stage.get('route_img', ''))
                ])
                sc += 1
                # 'results' is the current field name; 'top10' is legacy
                for row in stage.get('results', stage.get('top10', [])):
                    # current format: slug direct; legacy: rider_url
                    rslug = row.get('slug') or slug_from_url(row.get('rider_url', ''))
                    conn.execute('''INSERT OR REPLACE INTO stage_results
                        (id,stage_id,race_id,rank,rider_slug,rider_name,team,nat_code,flag,time_gap)
                        VALUES(?,?,?,?,?,?,?,?,?,?)''', [
                        f'{sid}-r{row["rank"]}', sid, race_id, row['rank'],
                        rslug, row.get('name', ''), row.get('team') or slug_to_team.get(rslug, ''),
                        row.get('nat', row.get('nat_code', '')), row.get('flag', ''),
                        row.get('time', row.get('time_gap', ''))
                    ])
                    results += 1
                    if rslug:
                        conn.execute('INSERT OR IGNORE INTO riders(slug,name) VALUES(?,?)',
                                     [rslug, row.get('name', '')])

            # Classifications
            for ctype, dbtype in [('gc_top10', 'gc'), ('points_top10', 'points'),
                                   ('kom_top10', 'kom'), ('youth_top10', 'youth')]:
                for row in race.get(ctype, []):
                    rslug = slug_from_url(row.get('rider_url', ''))
                    conn.execute('''INSERT OR REPLACE INTO classifications
                        (id,race_id,type,rank,rider_slug,rider_name,team,nat_code,flag,value)
                        VALUES(?,?,?,?,?,?,?,?,?,?)''', [
                        f'{race_id}-{dbtype}-r{row["rank"]}', race_id, dbtype, row['rank'],
                        rslug, row.get('name', ''), row.get('team') or slug_to_team.get(rslug, ''),
                        row.get('nat_code', ''), row.get('flag', ''), row.get('time_gap', '')
                    ])
                    cl += 1
                    if rslug:
                        conn.execute('INSERT OR IGNORE INTO riders(slug,name) VALUES(?,?)',
                                     [rslug, row.get('name', '')])

    # Rider photos from data.json rider_profiles
    photos = 0
    for slug, rp in d.get('rider_profiles', {}).items():
        conn.execute('''INSERT INTO riders(slug,name,nat,dob,photo_url,fetched_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(slug) DO UPDATE SET
              dob=COALESCE(excluded.dob,dob),
              nat=COALESCE(NULLIF(excluded.nat,''),nat),
              photo_url=COALESCE(excluded.photo_url,photo_url),
              fetched_at=excluded.fetched_at''',
            [slug, rp.get('name', slug), rp.get('nat', ''), rp.get('dob', ''),
             rp.get('photo', ''), rp.get('fetched_at', NOW)])
        if rp.get('photo'):
            photos += 1
        for w in rp.get('wins', []):
            wid = f'{slug}-cf-{w.get("date","")}-{str(w.get("race",""))[:30]}'
            conn.execute('INSERT OR IGNORE INTO rider_wins(id,rider_slug,year,date,race,cat) VALUES(?,?,?,?,?,?)',
                         [wid, slug, w.get('year', ''), w.get('date', ''), w.get('race', ''), w.get('cat', '')])

    conn.commit()
    print(f'  data.json → races:{rc}  stages:{sc}  results:{results}  classes:{cl}  photos:{photos}')


# ── Import rider_profiles.json ─────────────────────────────────────────────────

def import_rider_profiles(conn):
    path = os.path.join(BASE, 'rider_profiles.json')
    if not os.path.exists(path):
        print('  ✗ rider_profiles.json not found — skipping')
        return
    with open(path, encoding='utf-8') as f:
        rp = json.load(f)
    riders = rp.get('riders', rp)
    n = wins = 0
    for slug, r in riders.items():
        sp = r.get('specialties', {})
        conn.execute('''INSERT INTO riders
            (slug,name,nat,nat_name,height,weight,sp_oneday,sp_gc,sp_tt,sp_sprint,sp_climber,sp_hills)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(slug) DO UPDATE SET
              name=COALESCE(NULLIF(excluded.name,''),name),
              nat=COALESCE(NULLIF(excluded.nat,''),nat),
              nat_name=excluded.nat_name, height=excluded.height, weight=excluded.weight,
              sp_oneday=excluded.sp_oneday, sp_gc=excluded.sp_gc, sp_tt=excluded.sp_tt,
              sp_sprint=excluded.sp_sprint, sp_climber=excluded.sp_climber,
              sp_hills=excluded.sp_hills''',
            [slug, r.get('name', slug), r.get('nat', ''), r.get('nat_name', ''),
             r.get('height'), r.get('weight'),
             sp.get('oneday'), sp.get('gc'), sp.get('tt'),
             sp.get('sprint'), sp.get('climber'), sp.get('hills')])
        n += 1
        for w in r.get('wins', []):
            wid = f'{slug}-pcs-{w.get("date","")}-{str(w.get("race",""))[:30]}'
            conn.execute('INSERT OR IGNORE INTO rider_wins(id,rider_slug,year,date,race,cat) VALUES(?,?,?,?,?,?)',
                         [wid, slug, w.get('year', ''), w.get('date', ''), w.get('race', ''), w.get('cat', '')])
            wins += 1
        n += 0
    conn.commit()
    print(f'  rider_profiles.json → {n} riders, {wins} win records')


# ── Export data.js ──────────────────────────────────────────────────────────────

def export_data_js(conn):
    """Generate data.js for the HTML viewer (loads via <script src='data.js'>)."""
    races_out = []
    for race in conn.execute('SELECT * FROM races ORDER BY end_date DESC, start_date DESC'):
        rid   = race['id']
        rtype = race['race_type']

        cl_data = {}
        for cl in conn.execute(
            'SELECT type,rank,rider_slug,rider_name,team,nat_code,flag,value '
            'FROM classifications WHERE race_id=? ORDER BY type,rank', [rid]
        ):
            cl_data.setdefault(cl['type'], []).append({
                'rank': cl['rank'], 'slug': cl['rider_slug'], 'name': cl['rider_name'],
                'team': cl['team'], 'nat': (cl['nat_code'] or '').lower(),
                'flag': cl['flag'], 'value': cl['value']
            })

        stages_out = []
        for stage in conn.execute('SELECT * FROM stages WHERE race_id=? ORDER BY stage_num', [rid]):
            sid     = stage['id']
            results = []
            for r in conn.execute(
                'SELECT rank,rider_slug,rider_name,team,nat_code,flag,time_gap '
                'FROM stage_results WHERE stage_id=? ORDER BY rank', [sid]
            ):
                ph = conn.execute('SELECT photo_url FROM riders WHERE slug=?',
                                  [r['rider_slug']]).fetchone()
                results.append({
                    'rank': r['rank'], 'slug': r['rider_slug'], 'name': r['rider_name'],
                    'team': r['team'], 'nat': (r['nat_code'] or '').lower(),
                    'flag': r['flag'], 'time': r['time_gap'],
                    'photo': ph['photo_url'] if ph else None
                })
            stages_out.append({
                'num': stage['stage_num'], 'label': stage['label'],
                'type': stage['stage_type'], 'date': stage['date_str'],
                'from': stage['start_town'], 'to': stage['finish_town'],
                'km': stage['distance_km'], 'elev': stage['elevation_m'],
                'winner': stage['winner_name'],
                'winnerNat': (stage['winner_nat'] or '').lower(),
                'winnerFlag': stage['winner_flag'],
                'profileImg': stage['height_profile_img'],
                'routeImg': stage['route_img'],
                'results': results
            })

        oneday = []
        for r in conn.execute(
            'SELECT rank,rider_slug,rider_name,team,nat_code,flag,time_gap '
            'FROM race_results WHERE race_id=? ORDER BY rank', [rid]
        ):
            ph = conn.execute('SELECT photo_url FROM riders WHERE slug=?',
                              [r['rider_slug']]).fetchone()
            oneday.append({
                'rank': r['rank'], 'slug': r['rider_slug'], 'name': r['rider_name'],
                'team': r['team'], 'nat': (r['nat_code'] or '').lower(),
                'flag': r['flag'], 'time': r['time_gap'],
                'photo': ph['photo_url'] if ph else None
            })

        races_out.append({
            'id': rid, 'slug': race['slug'], 'name': race['name'],
            'year': race['year'], 'category': race['category'],
            'startDate': race['start_date'], 'endDate': race['end_date'],
            'status': race['status'], 'raceType': rtype,
            'totalStages': race['total_stages'], 'stagesCompleted': race['stages_completed'],
            'winnerName': race['winner_name'], 'winnerFlag': race['winner_flag'],
            'winnerNat': (race['winner_nat'] or '').lower(),
            'gcLeader': race['gc_leader'], 'officialUrl': race['official_url'],
            'classifications': cl_data,
            'stages': stages_out,
            'results': oneday
        })

    riders_map = {}
    for r in conn.execute('SELECT * FROM riders WHERE photo_url IS NOT NULL AND photo_url != ""'):
        riders_map[r['slug']] = {
            'name': r['name'], 'nat': (r['nat'] or '').lower(), 'natName': r['nat_name'],
            'photo': r['photo_url'], 'dob': r['dob'],
            'height': r['height'], 'weight': r['weight'],
            'specialties': {
                'gc': r['sp_gc'], 'sprint': r['sp_sprint'], 'climber': r['sp_climber'],
                'tt': r['sp_tt'], 'oneday': r['sp_oneday'], 'hills': r['sp_hills']
            }
        }

    payload = {
        'exportedAt': NOW + 'Z',
        'races': races_out,
        'riders': riders_map
    }

    out_path = os.path.join(BASE, 'data.js')
    content  = 'window.UCI_DATA = ' + json.dumps(payload, ensure_ascii=False) + ';\n'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'  data.js → {len(content):,} chars, {len(races_out)} races, {len(riders_map)} rider photos')


# ── Summary ─────────────────────────────────────────────────────────────────────

def print_summary(conn):
    print('\n══ cycling.db ══')
    for t in ['races', 'stages', 'stage_results', 'race_results',
              'classifications', 'riders', 'rider_wins', 'teams']:
        n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        print(f'  {t:<22} {n:>7,}')
    sr_with_team = conn.execute(
        "SELECT COUNT(*) FROM stage_results WHERE team!='' AND team IS NOT NULL"
    ).fetchone()[0]
    sr_total = conn.execute("SELECT COUNT(*) FROM stage_results").fetchone()[0]
    print(f'  team coverage (stages)   {sr_with_team:>7,} / {sr_total}')


# ── Main ──────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    print('=== UCI Cycling DB Import ===')
    print(f'Source: {BASE}')
    print(f'Target: {DEST_DB}\n')

    conn = open_db()

    print('[1/3] Importing data.json ...')
    import_data_json(conn)

    print('[2/3] Importing rider_profiles.json ...')
    import_rider_profiles(conn)

    print('[3/3] Exporting data.js ...')
    export_data_js(conn)

    print_summary(conn)
    conn.close()

    # Atomic copy: tmp -> dest
    shutil.copy2(TMP_DB, DEST_DB)
    sz = os.path.getsize(DEST_DB) / 1024 / 1024
    print(f'\n✓ cycling.db saved ({sz:.1f} MB)')
    print('✓ data.js updated')
    print('\nRun again after each scraper.py run to keep the DB current.')
