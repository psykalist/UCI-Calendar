#!/usr/bin/env python3
"""
build_rider_photos.py — Build a slim slug→photo_url index from rider_profiles.json.

Output: rider_photos.json  (~50KB vs 24MB for the full profiles file)

Run after any scrape_rider_profiles.py run:
  python build_rider_photos.py
  git add rider_photos.json && git commit -m "data: rebuild rider photos index" && git push
"""
import json, subprocess
from pathlib import Path

BASE = Path(__file__).parent
PROFILES = BASE / 'rider_profiles.json'
OUT = BASE / 'rider_photos.json'

riders = json.loads(PROFILES.read_text('utf-8')).get('riders', {})
photos = {slug: r['photo'] for slug, r in riders.items() if r.get('photo')}
print(f'Riders with photos: {len(photos)} / {len(riders)}')

OUT.write_text(json.dumps(photos, ensure_ascii=False, separators=(',', ':')), 'utf-8')
size = OUT.stat().st_size // 1024
print(f'Written rider_photos.json ({size} KB)')

subprocess.run(['git', 'add', 'rider_photos.json'], cwd=BASE)
result = subprocess.run(['git', 'diff', '--staged', '--quiet'], cwd=BASE)
if result.returncode != 0:
    subprocess.run(['git', 'commit', '-m', f'data: rider photos index ({len(photos)} photos)'], cwd=BASE)
    subprocess.run(['git', 'push'], cwd=BASE)
    print('Committed and pushed.')
else:
    print('No changes.')
