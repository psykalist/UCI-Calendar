"""
Debug script: fetch a stage result page and test parse_stage_results.
Run: py debug_scraper.py
"""
import sys, re
sys.path.insert(0, '.')
from scraper import fetch, parse_stage_results

url = '/race/tour-de-beauce/2026/stage-1/result'
print(f"Fetching {url}...")
html = fetch(url)
if not html:
    print("ERROR: fetch returned None")
    sys.exit(1)

print(f"Got {len(html)} bytes")
print(f"Has 'href=\"rider/': {'href=\"rider/' in html}")
print(f"Has '<span class=\"flag': {'<span class=\"flag' in html}")
print(f"Has 'class=\"time ar': {'class=\"time ar' in html}")
print()

# Test the parser
results = parse_stage_results(html)
print(f"parse_stage_results returned {len(results)} riders:")
for r in results:
    print(f"  #{r['rank']:2d} {r['flag']} {r['name']:<30s} {r['team']:<35s} {r['time_gap']}")

# Save full HTML for manual inspection
with open('debug_html.txt', 'w', encoding='utf-8') as f:
    f.write(html)
print(f"\nFull HTML saved to debug_html.txt")

# Show first <tr> with rider link
tr_match = re.search(r'<tr[^>]*>.*?href="rider/.*?</tr>', html, re.DOTALL | re.IGNORECASE)
if tr_match:
    print(f"\nFirst <tr> with rider link:\n{tr_match.group(0)[:1200]}")
else:
    print("\nNo <tr> with rider link found")
