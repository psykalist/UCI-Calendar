"""
Probe CyclingFlash structured calendar pages for full 2026 race list.
Run: py probe_calendar.py
"""
import re
from urllib.request import Request, urlopen
from urllib.parse import quote

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

def fetch(url):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace"), r.geturl()
    except Exception as e:
        return None, str(e)

def get_slugs(html, men_only=True):
    slugs = list(dict.fromkeys(
        re.findall(r'/race/([a-z0-9-]+-20\d\d)(?:/|["\' <])', html)
    ))
    if men_only:
        slugs = [s for s in slugs if not re.search(
            r'-(we|wj|wu|mu|mj|ju)-|(-we|-wj|-wu|-mu|-mj|-ju)$', s
        )]
    return slugs

URLS = [
    "https://cyclingflash.com/calendar/road/2026/Men%20Elite",
    "https://cyclingflash.com/calendar/road/2026/UCI%20World%20Tour",
    "https://cyclingflash.com/calendar/road/2026/UCI%20ProSeries",
    "https://cyclingflash.com/calendar/road/2026/1.1",
    "https://cyclingflash.com/calendar/road/2026/2.1",
]

for url in URLS:
    html, info = fetch(url)
    if not html:
        print(f"✗ {url}\n  [{info}]\n")
        continue

    slugs = get_slugs(html)
    print(f"✓ {url}")
    print(f"  Men's slugs: {len(slugs)}")
    for s in slugs:
        print(f"    {s}")
    print()
