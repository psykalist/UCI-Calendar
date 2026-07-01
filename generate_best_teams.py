"""
generate_best_teams.py
======================
Generates one auto-team opponent ("Team Claudius") per race for the Fantasy
tab. Reads data.json + rider_profiles.json, builds best_teams.json.

Rider suitability is scored from CyclingOracle stats (`co_stats` on each rider
profile — 13 attributes on a 0-100 scale, scraped by scrape_cyclingoracle.py).
Riders with no CyclingOracle entry get a flat low baseline value instead
(procyclingstats.com "specialties" scores are NOT normalised to 0-100 and are
not comparable — see predict_value() below).

The squad itself is chosen by an exact 0/1 knapsack maximising total
predicted value under the budget cap, not a greedy value/cost-ratio pick —
see _optimal_team() for why that distinction matters.

Run automatically by CI after every scrape. Can also be run locally:
    py generate_best_teams.py

Output: best_teams.json  (committed to GitHub Pages alongside data.json)

Scoring constants must stay in sync with index.html:
    STAGE_PTS  = {1:25,2:12,3:8,4..10:3}
    GC_PTS     = {1:50,2:30,3:20,4..10:8}
    JERSEY_PTS = 15
    BUDGET=100  MAX_SQUAD=9  COST_FLOOR=4  COST_CEIL=22
"""

import json, math, re, unicodedata
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
    """Replicate index.html buildRiderCosts() exactly — cost reflects actual
    results scored this season (market price), independent of the CyclingOracle
    suitability score used to pick the squad."""
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


# ── Race-type specialty weights (keyed to CyclingOracle `co_stats` fields) ────
# co_stats fields: flat, cobble, hill, mountain, sprint, timetrial, gc,
#                  onedaypoints, ttlong, ttshort, prologue, leadout, average

MONUMENT_NAMES = {'sanremo', 'vlaanderen', 'roubaix', 'liège', 'liege', 'lombardia'}

def race_weights(race):
    """Return a dict of {co_stats field: weight} for this race."""
    name_lc  = (race.get('name') or '').lower()
    n_stages = race.get('total_stages') or 1
    is_gt    = n_stages >= 21
    is_mon   = any(m in name_lc for m in MONUMENT_NAMES)

    if is_gt:
        return {'gc': 0.40, 'mountain': 0.30, 'timetrial': 0.15, 'hill': 0.10, 'onedaypoints': 0.05}
    if is_mon:
        if 'sanremo' in name_lc or 'vlaanderen' in name_lc:
            return {'onedaypoints': 0.30, 'flat': 0.20, 'cobble': 0.20, 'hill': 0.20, 'sprint': 0.10}
        if 'roubaix' in name_lc:
            return {'onedaypoints': 0.35, 'cobble': 0.45, 'flat': 0.20}
        # Liège, Lombardia — climbers' classics
        return {'onedaypoints': 0.30, 'hill': 0.35, 'mountain': 0.25, 'gc': 0.10}
    if n_stages <= 1:
        return {'onedaypoints': 0.40, 'flat': 0.25, 'sprint': 0.20, 'hill': 0.15}
    if n_stages <= 5:
        return {'gc': 0.25, 'onedaypoints': 0.25, 'hill': 0.20, 'timetrial': 0.15, 'mountain': 0.15}
    # Multi-stage (7-20 stages)
    return {'gc': 0.35, 'mountain': 0.25, 'hill': 0.15, 'timetrial': 0.15, 'onedaypoints': 0.10}


# NOTE: procyclingstats "specialties" scores are NOT on a 0-100 scale — they're
# raw cumulative career points that can range from 0 to 10,000+ depending on a
# rider's career length and calibre (e.g. Pogačar's climber specialty is
# 10122; a modest domestique's might be 50). CyclingOracle's co_stats, in
# contrast, are properly normalised to 0-100. Blending the two directly (as an
# earlier version of this script did) let a handful of specialties-only
# riders score higher than genuine elite CyclingOracle-rated riders just from
# scale mismatch. So: use co_stats only, and fall back to a flat low baseline
# (not specialties) for the small number of starters with no CyclingOracle
# entry yet.

def predict_value(slug, profiles, weights):
    """Predicted race suitability from CyclingOracle stats (co_stats). Riders
    with no CyclingOracle entry get a flat low baseline rather than an
    unnormalised procyclingstats specialty score."""
    prof = profiles.get(slug) or {}
    co = prof.get('co_stats')
    if co:
        return sum(co.get(k, 0) * w for k, w in weights.items())
    return 15.0  # no CyclingOracle data — unknown rider base value


# ── Team picker ───────────────────────────────────────────────────────────────

def _optimal_team(candidates, budget, n):
    """Exact 0/1 knapsack: pick exactly `n` riders maximising total predicted
    value subject to the budget cap.

    A greedy pick-by-value/cost-ratio was tried first, but it systematically
    passes over the sport's actual best riders: someone like Pogačar or
    Vingegaard costs 20-22cr (their `cost` reflects real results already
    scored this season), so even a huge predicted value gets a mediocre
    ratio next to a 4cr unknown who is merely decent — the greedy pick ends
    up as a bench of unknowns with zero recognisable GC riders. An exact
    knapsack instead finds the combination with the highest total value,
    which naturally spends on the stars worth their price and fills the
    rest of the squad with the best cheap options.
    """
    n = min(n, len(candidates))
    if n == 0:
        return []
    NEG = float('-inf')
    # dp[c][b] = best total value using exactly c riders and total cost <= b
    dp = [[NEG] * (budget + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    history = [[row[:] for row in dp]]  # snapshot after considering 0 riders
    for r in candidates:
        cost, val = r['cost'], r['value']
        new_dp = [row[:] for row in dp]
        for c in range(1, n + 1):
            prev_row = dp[c - 1]
            for b in range(cost, budget + 1):
                cand = prev_row[b - cost]
                if cand != NEG and cand + val > new_dp[c][b]:
                    new_dp[c][b] = cand + val
        dp = new_dp
        history.append([row[:] for row in dp])

    best_val, best_b = NEG, 0
    for b in range(budget + 1):
        if dp[n][b] > best_val:
            best_val, best_b = dp[n][b], b
    if best_val == NEG:
        return []  # can't afford a full squad even at floor cost

    # Backtrack through history to recover which riders were chosen.
    chosen = []
    c, b = n, best_b
    for idx in range(len(candidates), 0, -1):
        if c == 0:
            break
        r = candidates[idx - 1]
        cost, val = r['cost'], r['value']
        if b >= cost and history[idx - 1][c - 1][b - cost] + val == history[idx][c][b]:
            chosen.append(r)
            c -= 1
            b -= cost
    return chosen


def build_auto_team(race, costs, profiles):
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

    best = _optimal_team(scored, BUDGET, n_picks)
    if not best:
        return None

    return {
        'riders':    [{'name': r['name'], 'nat': r['nat'],
                       'slug': r['slug'], 'cost': r['cost'],
                       'predicted': round(r['value'])} for r in best],
        'total_cost': sum(r['cost'] for r in best),
    }


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

    co_count = sum(1 for p in profiles.values() if p.get('co_stats'))
    print(f'  {len(profiles)} rider profiles loaded ({co_count} with CyclingOracle stats)')

    print('Building rider cost table …')
    costs = build_costs(data)

    result = {'generated_at': data.get('scraped_at', ''), 'races': {}}
    total = 0

    for section in ('live', 'upcoming', 'recent'):
        for race in data.get(section, []):
            slug = race.get('slug') or race.get('name', '').lower().replace(' ', '-')
            if not slug:
                continue
            team = build_auto_team(race, costs, profiles)
            if team:
                result['races'][slug] = {
                    'name':     race.get('name', ''),
                    'section':  section,
                    'team':     team,
                }
                total += 1

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))

    print(f'✓ best_teams.json written — {total} races covered')


if __name__ == '__main__':
    main()
