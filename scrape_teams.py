#!/usr/bin/env python3
"""
scrape_teams.py — fetch all WorldTeam + ProTeam rosters and merge into data.json
Run from Git Bash: python3 scrape_teams.py
Takes ~2 minutes (35 teams × ~3s each)
"""
import sys, json, time
sys.path.insert(0, '.')
from scraper import scrape_team, WORLD_TEAMS, PRO_TEAMS

DATA = "data.json"

d = json.load(open(DATA, encoding='utf-8'))
teams = []
pairs = [(s, 'UWT') for s in WORLD_TEAMS] + [(s, 'Pro') for s in PRO_TEAMS]
total = len(pairs)

for i, (slug, cat) in enumerate(pairs, 1):
    print(f"[{i}/{total}] {slug} ... ", end='', flush=True)
    team = scrape_team(slug, cat)
    if team:
        print(f"{len(team.get('riders',[]))} riders")
        teams.append(team)
    else:
        print("FAILED")
    time.sleep(1.0)

d['teams'] = teams
total_riders = sum(len(t.get('riders',[])) for t in teams)
print(f"\n✅  {len(teams)} teams, {total_riders} riders — writing {DATA}")
json.dump(d, open(DATA, 'w', encoding='utf-8'), separators=(',', ':'))
print("Done. Commit and push with: bash git-push.sh \"data: scrape team rosters\"")
