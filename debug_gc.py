"""Run: py debug_gc.py - show how cont divs get populated"""
import sys, re
sys.path.insert(0, '.')
from scraper import fetch

js = fetch('/v3_scripts_v47.js')
print(f"Script: {len(js)} bytes")

# Show everything around 'cont'
for m in re.finditer(r'.{0,200}["\']cont["\'].{0,200}', js, re.DOTALL):
    print(repr(m.group())); print()
