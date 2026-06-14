"""Probe a CyclingFlash team page for riders, jersey, stats. Run: py probe_teams.py"""
import re, sys
from urllib.request import Request, urlopen

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

def fetch(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")

def strip(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    s = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1),16)), s)
    return re.sub(r'\s+', ' ', s).strip()

# Probe a UWT team
TEAM = "uae-emirates-xrg-2026"
url = f"https://cyclingflash.com/team/{TEAM}"
print(f"Fetching {url}...")
html = fetch(url)

with open("debug_team_page.txt", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Saved {len(html)//1024}KB to debug_team_page.txt\n")

# Rider links
riders = list(dict.fromkeys(re.findall(r'/profile/([a-z0-9-]+)', html)))
print(f"Rider profile slugs: {len(riders)}")
for r in riders[:10]:
    print(f"  {r}")

# Image/jersey links
imgs = re.findall(r'src=["\']([^"\']*(?:jersey|kit|logo|badge)[^"\']*)["\']', html, re.IGNORECASE)
print(f"\nJersey/kit images: {imgs[:5]}")

# All img tags
all_imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', html)
print(f"\nAll images ({len(all_imgs)} total), first 10:")
for i in all_imgs[:10]:
    print(f"  {i}")

# Stats/wins section text
stats_m = re.search(r'(?:wins|victories|palmares|results).{0,2000}', html, re.IGNORECASE | re.DOTALL)
if stats_m:
    print(f"\nStats section (first 500 chars):\n{strip(stats_m.group(0))[:500]}")

# Also probe one rider profile
print("\n" + "="*60)
if riders:
    rider_url = f"https://cyclingflash.com/profile/{riders[0]}"
    print(f"Fetching rider: {rider_url}")
    rider_html = fetch(rider_url)
    with open("debug_rider_page.txt", "w", encoding="utf-8") as f:
        f.write(rider_html)
    print(f"Saved {len(rider_html)//1024}KB to debug_rider_page.txt")

    # Rider images
    rider_imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', rider_html)
    print(f"Rider page images ({len(rider_imgs)}):")
    for i in rider_imgs[:8]:
        print(f"  {i}")

    # Key text
    print(f"\nRider page text (first 800 chars):")
    print(strip(rider_html[:4000])[:800])
