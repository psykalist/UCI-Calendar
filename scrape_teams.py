#!/usr/bin/env python3
"""
scrape_teams.py — fetch all WorldTeam + ProTeam rosters and merge into data.json
Run from Git Bash: python3 scrape_teams.py
Takes ~2 minutes (34 teams × ~3s each)
"""
import sys, json, time, os
sys.path.insert(0, '.')
from scraper import scrape_team, WORLD_TEAMS, PRO_TEAMS
from db_safe import safe_json_write

DATA = "data.json"
PHOTOS = "rider_photos.json"

d = json.load(open(DATA, encoding='utf-8'))

# Load photo map for injecting into rider records
photos = {}
if os.path.exists(PHOTOS):
    photos = json.load(open(PHOTOS, encoding='utf-8'))
    print(f"Loaded {len(photos)} rider photos")

teams = []
pairs = [(s, 'UWT') for s in WORLD_TEAMS] + [(s, 'Pro') for s in PRO_TEAMS]
total = len(pairs)

for i, (slug, cat) in enumerate(pairs, 1):
    print(f"[{i}/{total}] {slug} ... ", end='', flush=True)
    team = scrape_team(slug, cat)
    if team:
        # Inject photos from rider_photos.json
        for r in team.get('riders', []):
            r.setdefault('photo', photos.get(r.get('slug', ''), ''))
        print(f"{len(team.get('riders',[]))} riders")
        teams.append(team)
    else:
        print("FAILED")
    time.sleep(1.0)

d['teams'] = teams
total_riders = sum(len(t.get('riders',[])) for t in teams)
photos_filled = sum(1 for t in teams for r in t.get('riders',[]) if r.get('photo'))
print(f"\n✅  {len(teams)} teams, {total_riders} riders ({photos_filled} with photos) — writing {DATA}")
safe_json_write(DATA, d, required_keys=['live','upcoming','recent','scraped_at'], min_ratio=0.90, label='data.json (teams)')
print("Done. Commit and push with: bash git-push.sh \"data: scrape team rosters\"")
