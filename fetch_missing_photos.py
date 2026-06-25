#!/usr/bin/env python3
"""
fetch_missing_photos.py — Scrape cyclingflash profile pages to fill missing rider photos.

Fetches photos for every team rider not already in rider_photos.json,
then updates both rider_photos.json and injects photos into data.json.

Run: python3 fetch_missing_photos.py
Takes ~15-20 min for ~500 riders (1.2s delay between requests).
"""
import json, re, time, sys
sys.path.insert(0, '.')
from scraper import fetch, BASE_URL
from db_safe import safe_json_write

DATA       = 'data.json'
PHOTOS_OUT = 'rider_photos.json'

# Load current state
data    = json.load(open(DATA, encoding='utf-8'))
photos  = json.load(open(PHOTOS_OUT, encoding='utf-8'))

# Collect slugs that need photos
need = []
for team in data['teams']:
    for r in team['riders']:
        slug = r.get('slug', '')
        if slug and not r.get('photo') and slug not in photos:
            need.append(slug)
need = list(dict.fromkeys(need))  # deduplicate
print(f"Riders needing photos: {len(need)}")

new_photos = {}
failed = []

for i, slug in enumerate(need, 1):
    print(f"[{i}/{len(need)}] {slug}", end=' ... ', flush=True)
    html = fetch(f"{BASE_URL}/profile/{slug}")
    if not html:
        print("FAILED")
        failed.append(slug)
        continue

    # Extract first CDN photo (not responsive-images variant)
    m = re.search(
        r'https://cyclingflash\.ams3\.cdn\.digitaloceanspaces\.com/\d+/[^"\'<\s/]+\.(jpg|jpeg|png|webp)',
        html, re.IGNORECASE
    )
    if m:
        url = m.group(0)
        new_photos[slug] = url
        print(f"✓ {url[-40:]}")
    else:
        print("no photo found")
        failed.append(slug)

    time.sleep(1.0)

print(f"\n{'='*60}")
print(f"Found {len(new_photos)} new photos, {len(failed)} failed/missing")

if new_photos:
    # Merge into rider_photos.json
    photos.update(new_photos)
    with open(PHOTOS_OUT, 'w', encoding='utf-8') as f:
        json.dump(photos, f, ensure_ascii=False, separators=(',', ':'))
    print(f"Updated rider_photos.json ({len(photos)} total entries)")

    # Inject into data.json team rider records
    injected = 0
    for team in data['teams']:
        for r in team['riders']:
            if not r.get('photo') and r.get('slug') in new_photos:
                r['photo'] = new_photos[r['slug']]
                injected += 1

    safe_json_write(DATA, data,
                    required_keys=['live', 'upcoming', 'recent', 'scraped_at'],
                    min_ratio=0.90, label='data.json (photos)')
    print(f"Injected {injected} photos into data.json")
    print("\nCommit with:")
    print('  bash git-push.sh "data: fill missing rider photos"')
else:
    print("No new photos found — nothing to write.")
