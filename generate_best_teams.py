"""
generate_best_teams.py
======================
Generates three auto-team opponents per race (Easy / Pro / Elite) for the
Fantasy tab.  Reads data.json + rider_profiles.json, builds best_teams.json.

Run automatically by CI after every scrape.  Can also be run locally:
    py generate_best_teams.py

Output: best_teams.json  (committed to GitHub Pages alongside data.json)

Scoring constants must stay in sync with index.html:
    STAGE_PTS  = {1:25,2:12,3:8,4..10:3}
    GC_PTS     = {1:50,2:30,3:20,4..10:8}
    JERSEY_PTS = 15
    BUDGET=100  MAX_SQUAD=9  COST_FLOOR=4  COST_CEIL=22
"""

import json, math, re, unicodedata, random
from pathlib import Path

BASE = Path(__file__).parent

# ── Fantasy constants (mirror index.html exactly) ─────────────────────────────
BUDGET      = 100
MAX_SQUAD_GT = 8   # Grand Tours (total_stages >= 21)
MAX_SQUAD    = 7   # All other races
COST_FLOOR  = 4
COST_CEIL   = 22
STAGE_PTS   = {1:25, 2:12, 3:8, 4:3, 5:3, 6:3, 7:3, 8:3, 9:3, 10:3}
GC_PTS      = {1:50, 2:30, 3:20, 4:8, 5:8, 6:8, 7:8, 8:8, 9:8, 10:8}
JERSEY_PTS  = 15


# ── Helpers ───────────────────────────────────────────────────────────────────

def norm(n):
    """Normalise name to lowercase ASCII letters and spaces (mirrors JS normName)."""
    n = unicodedata.normalize('NFD', n or '').encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z]', ' ', n.lower())).strip()


def build_costs(data):
    """Replicate index.html buildRiderCosts() exactly."""
    scores = {}

    def add(name, pts):
        if not name or pts <= 0:
            return
        k = norm(name)
        scores[k] = scores.get(k, 0) + pts

    for section in ('recent', 'live', 'upcoming'):
        for race in data.get(section, []):
            for stage in race.get('stages', []):
                for r in stage.get('top10', []):
                    add(r.get('name'), STAGE_PTS.get(r.get('rank'), 0))
            cl = race.get('classifications', {})
            for r in cl.get('gc', []):
                add(r.get('name'), GC_PTS.get(r.get('rank'), 0))
            for key in ('points', 'mountain', 'youth'):
                lst = cl.get(key, [])
                if lst:
                    add(lst[0].get('name'), JERSEY_PTS)

    max_pts = max(scores.values(), default=1)
    costs = {}
    for k, pts in scores.items():
        cost = max(COST_FLOOR,
                   round(COST_FLOOR + (COST_CEIL - COST_FLOOR) * math.sqrt(pts / max_pts)))
        costs[k] = cost
        rev = ' '.join(k.split()[::-1])
        if rev != k:
            costs[rev] = cost
    return costs


def rider_cost(name, costs):
    return costs.get(norm(name), COST_FLOOR)


# ── Race-type specialty weights ───────────────────────────────────────────────

MONUMENT_NAMES = {'sanremo', 'vlaanderen', 'roubaix', 'liège', 'liege', 'lombardia'}

def race_weights(race):
    """
    Return a dict of {specialty: weight} for this race.
    Specialties: gc, oneday, climber, sprint, tt, hills
    """
    name_lc  = (race.get('name') or '').lower()
    n_stages = race.get('total_stages') or 1
    is_gt    = n_stages >= 21
    is_mon   = any(m in name_lc for m in MONUMENT_NAMES)

    if is_gt:
        return {'gc': 0.45, 'climber': 0.30, 'tt': 0.15, 'hills': 0.05, 'oneday': 0.05}
    if is_mon:
        if 'sanremo' in name_lc or 'vlaanderen' in name_lc:
            return {'oneday': 0.35, 'sprint': 0.30, 'hills': 0.25, 'gc': 0.10}
        if 'roubaix' in name_lc:
            return {'oneday': 0.50, 'hills': 0.30, 'sprint': 0.20}
        # Liège, Lombardia — climbers' classics
        return {'oneday': 0.35, 'climber': 0.45, 'hills': 0.20}
    if n_stages <= 1:
        return {'oneday': 0.40, 'sprint': 0.30, 'hills': 0.15, 'gc': 0.15}
    if n_stages <= 5:
        return {'gc': 0.25, 'oneday': 0.35, 'climber': 0.20, 'tt': 0.10, 'hills': 0.10}
    # Multi-stage (7–20 stages)
    return {'gc': 0.35, 'climber': 0.30, 'tt': 0.15, 'hills': 0.10, 'oneday': 0.10}


def predict_value(slug, profiles, weights):
    """Predicted race suitability (0–100) from PCS specialty scores."""
    spec = (profiles.get(slug) or {}).get('specialties') or {}
    if not spec:
        return 15.0  # unknown rider base value
    return sum(spec.get(k, 0) * w for k, w in weights.items())


# ── Team picker ───────────────────────────────────────────────────────────────

def _greedy_pick(candidates, budget, n, rng=None):
    """
    Greedy knapsack by value/cost ratio.
    If rng is provided, the top-half is shuffled first (introduces randomness
    for lower difficulty tiers).
    """
    pool = sorted(candidates, key=lambda x: x['value'] / max(x['cost'], 1), reverse=True)
    if rng is not None:
        mid = max(1, len(pool) // 2)
        top = pool[:mid]
        rng.shuffle(top)
        pool = top + pool[mid:]

    picked, spent = [], 0
    for r in pool:
        if len(picked) >= n:
            break
        if spent + r['cost'] <= budget:
            picked.append(r)
            spent += r['cost']
    return picked


def build_auto_teams(race, costs, profiles):
    startlist = race.get('startlist') or []
    if not startlist:
        return None

    n_picks = MAX_SQUAD_GT if (race.get('total_stages') or 1) >= 21 else MAX_SQUAD
    weights = race_weights(race)

    # Score every starter
    scored = []
    for entry in startlist:
        raw_url = entry.get('rider_url') or ''
        slug = entry.get('slug') or raw_url.replace('/profile/', '').strip('/')
        name = entry.get('name') or slug.replace('-', ' ').title()
        nat  = entry.get('nat') or ''
        cost  = rider_cost(name, costs)
        value = predict_value(slug, profiles, weights)
        scored.append({'slug': slug, 'name': name, 'nat': nat,
                       'cost': cost, 'value': value})

    if not scored:
        return None

    # Elite — pure greedy optimum (best possible team)
    elite = _greedy_pick(scored, BUDGET, n_picks)

    # Pro — randomised selection from top 50% by value/cost
    rng_pro = random.Random(hash(race.get('slug') or race.get('name') or '') ^ 0xCAFE)
    pro = _greedy_pick(scored, BUDGET, n_picks, rng=rng_pro)

    # Easy — cheapest n_picks riders (riders with little/no results history)
    cheap = sorted(scored, key=lambda x: (x['cost'], -x['value']))
    easy  = cheap[:n_picks]

    def fmt(team):
        return {
            'riders':    [{'name': r['name'], 'nat': r['nat'],
                           'slug': r['slug'], 'cost': r['cost'],
                           'predicted': round(r['value'])} for r in team],
            'total_cost': sum(r['cost'] for r in team),
        }

    return {'elite': fmt(elite), 'pro': fmt(pro), 'easy': fmt(easy)}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    data_path     = BASE / 'data.json'
    profiles_path = BASE / 'rider_profiles.json'
    out_path      = BASE / 'best_teams.json'

    print('Loading data.json …')
    with open(data_path, encoding='utf-8') as f:
        data = json.load(f)

    print('Loading rider_profiles.json …')
    profiles: dict = {}
    if profiles_path.exists():
        with open(profiles_path, encoding='utf-8') as f:
            raw = json.load(f)
        profiles = raw.get('riders') or raw  # handle both formats

    print('Building rider cost table …')
    costs = build_costs(data)

    result = {'generated_at': data.get('scraped_at', ''), 'races': {}}
    total = 0

    for section in ('live', 'upcoming', 'recent'):
        for race in data.get(section, []):
            slug = race.get('slug') or race.get('name', '').lower().replace(' ', '-')
            if not slug:
                continue
            teams = build_auto_teams(race, costs, profiles)
            if teams:
                result['races'][slug] = {
                    'name':     race.get('name', ''),
                    'section':  section,
                    'teams':    teams,
                }
                total += 1

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))

    print(f'✓ best_teams.json written — {total} races covered')


if __name__ == '__main__':
    main()
