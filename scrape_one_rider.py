#!/usr/bin/env python3
"""
scrape_one_rider.py — Force re-fetch a single rider's full profile.

Usage:
  py scrape_one_rider.py wout-van-aert
  py scrape_one_rider.py tadej-pogacar

Fetches photo, bio, team history, full palmares, and season results from PCS,
then saves to rider_profiles.json.

Run from your local machine — PCS blocks CI/server IPs.
After running:
  git add rider_profiles.json && git commit -m "data: refresh <slug>" && git push
"""

import sys
from pathlib import Path

# Reuse everything from the main scraper
sys.path.insert(0, str(Path(__file__).parent))
from scrape_rider_profiles import (
    fetch_html, parse_rider_page, parse_team_history,
    parse_wins_page, parse_season_results, save, PROFILES_FILE, DELAY
)
import json, time, datetime

def main():
    if len(sys.argv) < 2:
        print("Usage: py scrape_one_rider.py <rider-slug>")
        print("Example: py scrape_one_rider.py wout-van-aert")
        sys.exit(1)

    slug = sys.argv[1].strip()

    # Load existing profiles
    existing = {}
    if PROFILES_FILE.exists():
        try:
            existing = json.loads(PROFILES_FILE.read_text('utf-8')).get('riders', {})
            print(f"Loaded {len(existing)} existing profiles")
        except Exception as e:
            print(f"Warning: could not load existing profiles: {e}")

    print(f"Fetching {slug} from PCS...")

    html_main = fetch_html(f'https://www.procyclingstats.com/rider/{slug}')
    if html_main is None:
        print(f"ERROR: Could not fetch rider page for '{slug}' — check the slug is correct.")
        sys.exit(1)
    time.sleep(DELAY)

    profile = parse_rider_page(html_main, slug)
    profile['team_history'] = parse_team_history(html_main)
    print(f"  Photo: {'✓' if profile.get('photo') else '✗ not found'}")
    print(f"  Team history: {len(profile['team_history'])} entries")

    html_wins = fetch_html(f'https://www.procyclingstats.com/rider/{slug}/statistics/wins')
    time.sleep(DELAY)
    profile['wins'] = parse_wins_page(html_wins) if html_wins else []
    print(f"  Wins: {len(profile['wins'])}")

    html_results = fetch_html(f'https://www.procyclingstats.com/rider/{slug}/results')
    time.sleep(DELAY)
    profile['season_results'] = parse_season_results(html_results) if html_results else []
    print(f"  Season results: {len(profile['season_results'])} entries")

    profile['fetched_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    existing[slug] = profile
    save(existing)
    print(f"\nSaved. Now run:")
    print(f'  git add rider_profiles.json && git commit -m "data: refresh {slug}" && git push')

if __name__ == '__main__':
    main()
