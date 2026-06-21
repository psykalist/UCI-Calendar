"""
apply_specialties.py — merge specialty_cache.json into data.json.

Run this once after backfill_specialties.py finishes.
"""

import json
import os
import time

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_FILE  = os.path.join(BASE_DIR, "data.json")
CACHE_FILE = os.path.join(BASE_DIR, "specialty_cache.json")


def main():
    # Load cache
    if not os.path.exists(CACHE_FILE):
        print("specialty_cache.json not found. Run backfill_specialties.py first.")
        return

    with open(CACHE_FILE, encoding='utf-8') as f:
        cache = json.load(f)

    # Load data.json
    with open(DATA_FILE, encoding='utf-8') as f:
        data = json.load(f)

    profiles = data.get('rider_profiles', {})
    applied = 0
    for slug, entry in cache.items():
        if slug in profiles:
            profiles[slug]['specialties'] = entry['specialties']
            profiles[slug]['specialties_fetched_at'] = entry.get('fetched_at', '')
            applied += 1

    # Write data.json (single write, no concurrency issue)
    tmp = DATA_FILE + f".tmp{os.getpid()}"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    for _ in range(10):
        try:
            os.replace(tmp, DATA_FILE)
            break
        except PermissionError:
            time.sleep(0.3)

    has = sum(1 for p in profiles.values() if p.get('specialties') and len(p['specialties']) > 0)
    print(f"Applied specialties to {applied} riders.")
    print(f"Riders with real specialty data: {has}/{len(profiles)}")
    print("Now run: git add data.json specialty_cache.json && git commit -m 'data: specialty backfill' && git push")


if __name__ == "__main__":
    main()
