#!/usr/bin/env python3
"""
scrape_cyclingoracle.py — Fetch CyclingOracle rider stats and merge into rider_profiles.json.

CyclingOracle scores riders on 13 attributes (0–100 scale), updated from race results
over the past 3 seasons. Scores are stored as `co_stats` on each rider entry.

Usage:
  py scrape_cyclingoracle.py          # fetch all CO riders, merge into rider_profiles.json
  py scrape_cyclingoracle.py --dry-run # print match stats without writing

After running:
  git add rider_profiles.json && git commit -m "data: cyclingoracle stats" && git push
"""

import json, os, sys, time, unicodedata, re
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

BASE          = Path(__file__).parent
PROFILES_FILE = BASE / 'rider_profiles.json'
DRY_RUN       = '--dry-run' in sys.argv

API_URL = 'https://api.cyclingoracle.com/v1'
API_KEY = 'c81823a3-ea7e-4a48-97ab-aa3372fd1a0b'

PAGE_SIZE = 100   # max per request
DELAY     = 0.4   # seconds between pages

GQL_QUERY = """
query FetchRiders(
  $take: Int!,
  $page: Int!,
  $gender: Gender!,
  $search: String!,
  $orderBy: [OrderByDto!],
  $teamIds: [String!],
  $nations: [String!]
) {
  fetchRiders(
    take: $take,
    page: $page,
    gender: $gender,
    search: $search,
    orderBy: $orderBy,
    teamIds: $teamIds,
    nations: $nations
  ) {
    count
    riders {
      id
      fullName
      slug
      nation
      currentTeam {
        name
      }
      currentStats {
        flat
        cobble
        hill
        mountain
        sprint
        timetrial
        gc
        onedaypoints
        ttlong
        ttshort
        prologue
        leadout
        average
      }
    }
  }
}
"""


def normalise(name: str) -> str:
    """Normalise a rider name to a slug-comparable form.

    'Tadej Pogačar' → 'tadej-pogacar'
    Handles accents, hyphens-in-names, apostrophes, etc.
    """
    # Strip accents via NFD decomposition
    nfd = unicodedata.normalize('NFD', name)
    ascii_name = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    # Lowercase, replace spaces and hyphens with single dash, strip other chars
    slug = re.sub(r'[^a-z0-9\-]', '', ascii_name.lower().replace(' ', '-').replace("'", ''))
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


def fetch_page(page: int) -> dict:
    payload = json.dumps({
        'query': GQL_QUERY,
        'variables': {
            'take': PAGE_SIZE,
            'page': page,
            'gender': 'MEN',
            'search': '',
            'orderBy': [{'field': 'average', 'orderBy': 'DESC', 'nestedField': ['currentStats']}],
            'teamIds': None,
            'nations': None,
        }
    }).encode('utf-8')

    req = Request(
        API_URL,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': API_KEY,
            'User-Agent': 'Mozilla/5.0 (compatible; UCI-Calendar-Scraper/1.0)',
        },
        method='POST',
    )
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))


def build_co_name_index(riders_json: dict) -> tuple:
    """Build two lookup dicts from rider_profiles.json:

    exact_index  — normalised-full-name → pcs_slug
    prefix_index — normalised-first-two-words → [pcs_slug, ...]
      (handles cases where CyclingOracle uses 'Jonas Vingegaard' but
       PCS has 'Jonas Vingegaard Rasmussen' → slug 'jonas-vingegaard-rasmussen')
    """
    exact_index  = {}
    prefix_index = {}  # shortened key → list of full pcs slugs

    for pcs_slug, profile in riders_json.items():
        name = profile.get('name', '')
        if not name:
            continue
        key = normalise(name)
        exact_index[key] = pcs_slug

        # Build prefix entries: for 'jonas-vingegaard-rasmussen' also add
        # 'jonas-vingegaard' as a prefix key pointing here.
        parts = key.split('-')
        for end in range(2, len(parts)):          # skip full key (in exact_index)
            prefix = '-'.join(parts[:end])
            prefix_index.setdefault(prefix, []).append(pcs_slug)

    return exact_index, prefix_index


def lookup_rider(co_name: str, exact_index: dict, prefix_index: dict) -> str | None:
    """Return PCS slug for a CyclingOracle name, or None if no confident match."""
    key = normalise(co_name)

    # 1. Exact match
    if key in exact_index:
        return exact_index[key]

    # 2. Prefix match — CO name is a prefix of the PCS full name
    candidates = prefix_index.get(key, [])
    if len(candidates) == 1:
        return candidates[0]          # unambiguous
    if len(candidates) > 1:
        # Disambiguate: prefer the candidate whose slug starts with key-
        starts = [s for s in candidates if s.startswith(key + '-')]
        if len(starts) == 1:
            return starts[0]
        # Still ambiguous — skip to avoid wrong match
        return None

    return None


def main():
    # Load existing profiles
    if not PROFILES_FILE.exists():
        print('❌  rider_profiles.json not found — run scrape_rider_profiles.py first')
        sys.exit(1)

    with open(PROFILES_FILE, encoding='utf-8') as f:
        db = json.load(f)

    riders_json = db.get('riders', db)
    if not isinstance(riders_json, dict):
        print('❌  Unexpected rider_profiles.json structure')
        sys.exit(1)

    exact_index, prefix_index = build_co_name_index(riders_json)
    print(f'📂  Loaded {len(riders_json):,} riders from rider_profiles.json')

    # Fetch all pages
    all_co_riders = []
    page = 1
    total = None

    while True:
        print(f'  → Fetching page {page}…', end=' ', flush=True)
        try:
            resp = fetch_page(page)
        except (HTTPError, URLError) as e:
            print(f'\n❌  Request failed: {e}')
            sys.exit(1)

        if 'errors' in resp:
            print(f'\n❌  GraphQL error: {resp["errors"]}')
            sys.exit(1)

        batch = resp.get('data', {}).get('fetchRiders', {})
        riders = batch.get('riders', [])
        if total is None:
            total = batch.get('count', 0)
            pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            print(f'total={total}, pages={pages}')

        all_co_riders.extend(riders)
        print(f'    got {len(riders)} riders (total so far: {len(all_co_riders)})')

        if len(all_co_riders) >= total or 