"""
backfill_specialties.py — fetch PCS specialty data for all riders.

Writes to specialty_cache.json (never touches data.json during the run).
Run apply_specialties.py afterwards to merge into data.json.

Usage:
    py backfill_specialties.py          # fetch missing
    py backfill_specialties.py --all    # re-fetch everything
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DATA_FILE      = os.path.join(BASE_DIR, "data.json")
CACHE_FILE     = os.path.join(BASE_DIR, "specialty_cache.json")
PCS_BASE       = "https://www.procyclingstats.com"
REQUEST_TIMEOUT = 20
DELAY_SECONDS  = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def fetch(url):
    for attempt in range(3):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                return r.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** attempt)
        except (URLError, TimeoutError, OSError, Exception):
            time.sleep(2 ** attempt)
    return None


def scrape_specialties(slug):
    html = fetch(f"{PCS_BASE}/rider/{slug}")
    if not html:
        return None
    specialties = {}
    pps_m = re.search(r'<ul[^>]+class="pps[^"]*"[^>]*>(.*?)</ul>', html, re.DOTALL)
    if pps_m:
        pps_block = pps_m.group(1)
        for li_m in re.finditer(r'<li[^>]*>(.*?)</li>', pps_block, re.DOTALL):
            li = li_m.group(1)
            score_m = re.search(r'class="xvalue[^"]*"\s*>(\d+)<', li)
            cat_m   = re.search(r'(?:career-points-|/results/)(one-day-races|gc|time-trial|sprint|climbers?|hills)', li)
            bar_m   = re.search(r'class="w(\d+)\s', li)
            if score_m and cat_m:
                key = cat_m.group(1)
                specialties[key] = {
                    'score': int(score_m.group(1)),
                    'bar':   int(bar_m.group(1)) if bar_m else 0,
                }
    return specialties


def load_cache():
    try:
        with open(CACHE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    """Save specialty_cache.json — small file, fast write, safe."""
    tmp = CACHE_FILE + f".tmp{os.getpid()}"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    for _ in range(10):
        try:
            os.replace(tmp, CACHE_FILE)
            return
        except PermissionError:
            time.sleep(0.2)
    os.remove(tmp)


def get_all_slugs():
    """Read slugs from data.json (read-only)."""
    with open(DATA_FILE, encoding='utf-8') as f:
        d = json.load(f)
    return list(d.get('rider_profiles', {}).keys())


def main():
    refetch_all = '--all' in sys.argv

    slugs = get_all_slugs()
    cache = load_cache()

    if refetch_all:
        missing = slugs
    else:
        # Skip riders already in cache (even empty {} = confirmed no PCS data)
        missing = [s for s in slugs if s not in cache]

    total = len(missing)
    if not total:
        print(f"All {len(slugs)} riders already in specialty cache. Nothing to do.")
        print(f"Run: py apply_specialties.py  to merge into data.json")
        return

    print(f"Fetching specialties for {total} riders (~{total * DELAY_SECONDS // 60} min)...")
    print(f"Writes go to specialty_cache.json — data.json is never touched.\n")

    ok = skipped = failed = 0

    for i, slug in enumerate(missing, 1):
        print(f"[{i}/{total}] {slug}...", end=" ", flush=True)
        try:
            specialties = scrape_specialties(slug)
        except Exception as e:
            print(f"ERROR ({e}) — skipping")
            failed += 1
            if i < total:
                time.sleep(DELAY_SECONDS)
            continue

        if specialties is None:
            print("FAILED (fetch error)")
            failed += 1
        elif specialties:
            cache[slug] = {'specialties': specialties, 'fetched_at': datetime.now(timezone.utc).isoformat()}
            save_cache(cache)
            cats = ", ".join(f"{k}:{v['score']}" for k, v in specialties.items())
            print(f"OK — {cats}")
            ok += 1
        else:
            cache[slug] = {'specialties': {}, 'fetched_at': datetime.now(timezone.utc).isoformat()}
            save_cache(cache)
            print("no PCS data")
            skipped += 1

        if i < total:
            time.sleep(DELAY_SECONDS)

    print(f"\nDone. {ok} fetched, {skipped} no PCS data, {failed} failed.")
    if failed:
        print("Re-run to retry failures.")
    print("Then run: py apply_specialties.py")


if __name__ == "__main__":
    main()
