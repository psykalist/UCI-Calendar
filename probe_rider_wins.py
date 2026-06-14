"""Probe for rider wins/palmares endpoint. Run: py probe_rider_wins.py"""
import re, sys, json
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/json,*/*;q=0.8",
}

def fetch(url):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=10) as r:
            ct = r.headers.get('Content-Type','')
            body = r.read().decode('utf-8', errors='replace')
            return r.status, ct, body
    except HTTPError as e:
        return e.code, '', ''
    except Exception as e:
        return 0, '', str(e)

SLUG = "joao-almeida"
BASE = "https://cyclingflash.com"

urls_to_try = [
    f"{BASE}/profile/{SLUG}/victories",
    f"{BASE}/profile/{SLUG}/results",
    f"{BASE}/profile/{SLUG}/wins",
    f"{BASE}/profile/{SLUG}/palmares",
    f"{BASE}/api/profile/{SLUG}/victories",
    f"{BASE}/api/profile/{SLUG}",
    f"{BASE}/api/riders/{SLUG}/wins",
    f"{BASE}/api/riders/{SLUG}",
]

for url in urls_to_try:
    code, ct, body = fetch(url)
    print(f"  {code}  {url}")
    if code == 200:
        print(f"       Content-Type: {ct}")
        print(f"       Body (first 300): {body[:300]}")
        with open(f"debug_wins_{SLUG}.txt", "w", encoding="utf-8") as f:
            f.write(body)
        print(f"       Saved to debug_wins_{SLUG}.txt")
