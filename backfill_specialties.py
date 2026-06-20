"""
backfill_specialties.py — one-shot bulk fetch of all missing PCS specialty data.

Run once from the command line:
    py backfill_specialties.py

Fetches all riders missing specialties with a 5-second delay between each.
Saves progress after every rider so it's safe to Ctrl+C and resume.
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

DATA_FILE       = os.path.join(os.path.dirname(__file__), "data.json")
WRITE_LOCK      = os.path.join(os.path.dirname(__file__), ".data_write.lock")
PCS_BASE        = "https://www.procyclingstats.com"
REQUEST_TIMEOUT = 20
DELAY_SECONDS   = 5   # polite delay between requests

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
        except (URLError, TimeoutError, OSError):
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


def acquire_write_lock(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(WRITE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.1)
    return False

def release_write_lock():
    try:
        os.remove(WRITE_LOCK)
    except Exception:
        pass

def save_data(data):
    if not acquire_write_lock():
        print("  Could not acquire write lock — skipping save.", flush=True)
        return
    try:
        tmp = DATA_FILE + f".tmp{os.getpid()}"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        for _ in range(10):
            try:
                os.replace(tmp, DATA_FILE)
                break
            except PermissionError:
                time.sleep(0.3)
        else:
            print("  Warning: could not replace data.json after retries.", flush=True)
            try: os.remove(tmp)
            except: pass
    finally:
        release_write_lock()


def main():
    with open(DATA_FILE, encoding='utf-8') as f:
        data = json.load(f)
    profiles = data.get('rider_profiles', {})

    missing = [slug for slug, p in profiles.items() if 'specialties' not in p]
    total = len(missing)

    if not total:
        print("All riders already have specialty data. Nothing to do.")
        return

    print(f"Backfilling specialties for {total} riders (~{total * DELAY_SECONDS // 60} min)...")
    print("Safe to Ctrl+C — progress is saved after each rider.\n")

    ok = skipped = failed = 0

    for i, slug in enumerate(missing, 1):
        print(f"[{i}/{total}] {slug}...", end=" ", flush=True)
        specialties = scrape_specialties(slug)

        if specialties is None:
            print("FAILED (fetch error — will retry next run)")
            failed += 1
        elif specialties:
            profiles[slug]['specialties'] = specialties
            profiles[slug]['specialties_fetched_at'] = datetime.now(timezone.utc).isoformat()
            save_data(data)
            cats = ", ".join(f"{k}:{v['score']}" for k, v in specialties.items())
            print(f"OK — {cats}")
            ok += 1
        else:
            profiles[slug]['specialties'] = {}
            profiles[slug]['specialties_fetched_at'] = datetime.now(timezone.utc).isoformat()
            save_data(data)
            print("no PCS data (marked)")
            skipped += 1

        if i < total:
            time.sleep(DELAY_SECONDS)

    print(f"\nDone. {ok} fetched, {skipped} no PCS data, {failed} failed.")
    print("Run again to retry any failures, then git add data.json && git push.")


if __name__ == "__main__":
    main()
