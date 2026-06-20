"""
fetch_one_rider.py — fetch one rider's PCS specialty stats and save to data.json.

Run via Windows Task Scheduler every minute to politely backfill specialty data
without hammering procyclingstats.com.

Exit codes:
  0 — fetched one rider successfully (or nothing left to do)
  1 — fetch failed (will retry next minute)
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

DATA_FILE     = os.path.join(os.path.dirname(__file__), "data.json")
LOCK_FILE     = os.path.join(os.path.dirname(__file__), ".specialty_last_run")
WRITE_LOCK    = os.path.join(os.path.dirname(__file__), ".data_write.lock")
MIN_INTERVAL  = 50   # seconds — skip run if called sooner than this
PCS_BASE      = "https://www.procyclingstats.com"
REQUEST_TIMEOUT = 20

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
        except URLError:
            time.sleep(2 ** attempt)
    return None


def scrape_specialties(slug):
    """Fetch PCS rider page and return specialty dict."""
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


def load_data():
    with open(DATA_FILE, encoding='utf-8') as f:
        return json.load(f)


def acquire_write_lock(timeout=10):
    """Spin-wait for exclusive write access (max timeout seconds)."""
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
    # Throttle: skip if called too soon after the last run
    now_ts = time.time()
    try:
        last_run = float(open(LOCK_FILE).read().strip())
        if now_ts - last_run < MIN_INTERVAL:
            sys.exit(0)  # silent exit — too soon
    except Exception:
        pass
    with open(LOCK_FILE, 'w') as f:
        f.write(str(now_ts))

    data = load_data()
    profiles = data.get('rider_profiles', {})

    # Find next rider missing specialty data
    # Note: specialties={} means "checked, none found" — exclude those too
    missing = [slug for slug, p in profiles.items() if 'specialties' not in p]

    if not missing:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] All {len(profiles)} riders have specialty data. Nothing to do.")
        sys.exit(0)

    slug = missing[0]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching specialties for {slug} ({len(missing)} remaining)...", flush=True)

    specialties = scrape_specialties(slug)

    if specialties is None:
        print(f"  Failed to fetch {slug} — will retry next run.", flush=True)
        sys.exit(1)

    if specialties:
        profiles[slug]['specialties'] = specialties
        profiles[slug]['specialties_fetched_at'] = datetime.now(timezone.utc).isoformat()
        save_data(data)
        cats = ", ".join(f"{k}:{v['score']}" for k, v in specialties.items())
        print(f"  OK: {cats}", flush=True)
        print(f"  {len(missing)-1} riders still missing specialties.", flush=True)
    else:
        # PCS page loaded but no specialty block — mark as attempted so we skip it
        profiles[slug]['specialties'] = {}
        profiles[slug]['specialties_fetched_at'] = datetime.now(timezone.utc).isoformat()
        save_data(data)
        print(f"  No specialty data on PCS for {slug} (marked as checked).", flush=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
