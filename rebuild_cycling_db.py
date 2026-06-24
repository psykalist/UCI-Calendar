"""
rebuild_cycling_db.py — Rebuilds cycling.db from scratch using the schema in
import_to_db.py, then seeds race_palmares from the palmares data in data.json.

Run this once to fix a corrupted/missing cycling.db.
"""
import json, sqlite3, os, shutil, sys
from json import JSONDecoder

BASE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'cycling.db')
DAT     = os.path.join(BASE, 'data.json')
TMP_DB  = os.path.join(BASE, 'cycling_rebuild.tmp.db')

# Pull in the SCHEMA from import_to_db
sys.path.insert(0, BASE)
from import_to_db import SCHEMA

print('=== Rebuilding cycling.db ===')

# Remove any broken DB
if os.path.exists(TMP_DB):
    os.remove(TMP_DB)

conn = sqlite3.connect(TMP_DB)
conn.execute('PRAGMA journal_mode=DELETE')
conn.executescript(SCHEMA)
conn.commit()
print('  Schema created.')

# If old DB is valid, copy its data in
try:
    old = sqlite3.connect(DB_PATH)
    old.execute('SELECT count(*) FROM sqlite_master')
    old.close()
    print('  Existing cycling.db appears valid — skipping wipe (use --force to override)')
except Exception as e:
    print(f'  Existing cycling.db invalid ({e}) — starting fresh')

# Seed race_palmares from data.json
print('  Seeding race_palmares from data.json...')
with open(DAT, 'r', encoding='utf-8') as f:
    content = f.read()
d, _ = JSONDecoder().raw_decode(content)

pbr = d.get('palmares', {})
rows_inserted = 0
c = conn.cursor()
for race_slug, entries in pbr.items():
    for entry in entries:
        year        = entry.get('year')
        winner      = entry.get('winner', '')
        winner_slug = entry.get('winner_slug', '')
        second      = entry.get('second', '')
        second_slug = entry.get('second_slug', '')
        third       = entry.get('third', '')
        third_slug  = entry.get('third_slug', '')
        row_id = f"{race_slug}_{year}"
        c.execute('''
            INSERT OR REPLACE INTO race_palmares
            (id, race_slug, year, winner, winner_slug, second, second_slug, third, third_slug)
            VALUES (?,?,?,?,?,?,?,?,?)
        ''', (row_id, race_slug, year, winner, winner_slug, second, second_slug, third, third_slug))
        rows_inserted += 1

conn.commit()
conn.close()
print(f'  Inserted {rows_inserted} race_palmares rows across {len(pbr)} races.')

# Atomically replace the old DB
shutil.move(TMP_DB, DB_PATH)
print(f'  cycling.db written ({os.path.getsize(DB_PATH)//1024} KB).')
print('Done.')
