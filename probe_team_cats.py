"""Probe teams list page for UWT/Pro category labels. Run: py probe_team_cats.py"""
import re, sys
from urllib.request import Request, urlopen

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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
    s = re.sub(r'&amp;', '&', s)
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    return re.sub(r'\s+', ' ', s).strip()

html = fetch("https://cyclingflash.com/teams/2026/road/men")
with open("debug_teams_list.txt", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Saved {len(html)//1024}KB\n")

# Check if UWT/Pro appear anywhere
for cat in ["UWT", "WorldTour", "ProTeam", "Pro Team", "1.Pro", "2.Pro", "Continental"]:
    count = html.count(cat)
    if count:
        print(f"  '{cat}' appears {count} times")

# Find team rows
tr_blocks = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
team_rows = [t for t in tr_blocks if '/team/' in t]
print(f"\nTeam rows: {len(team_rows)}")

print("\nFirst 8 rows stripped:")
for row in team_rows[:8]:
    print(f"  {strip(row)[:180]}")

print("\nRaw HTML of first row (first 600 chars):")
print(team_rows[0][:600])
