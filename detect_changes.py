"""
detect_changes.py — diff old vs new data.json, append to changelog.json

Usage:
    python3 detect_changes.py data_old.json data.json changelog.json

Detects:
  - New stage winners
  - GC / points / KOM / youth leader changes
  - Startlist additions (new riders added to an upcoming race)
  - New races appearing in results
"""

import json
import sys
import hashlib
from datetime import datetime, timezone, timedelta

CHANGELOG_MAX_DAYS = 14   # Keep entries for this many days


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default or {}


def entry_id(*parts):
    """Stable unique ID for a changelog entry."""
    key = "|".join(str(p) for p in parts)
    return hashlib.md5(key.encode()).hexdigest()[:12]


def race_index(data, sections=("live", "recent", "upcoming")):
    """Build {race_name: race_obj} index."""
    idx = {}
    for sec in sections:
        for r in data.get(sec, []):
            name = r.get("name") or r.get("slug", "")
            if name:
                idx[name] = r
    return idx


def stage_index(race):
    """Build {stage_num: stage_obj} for a race."""
    return {s["num"]: s for s in race.get("stages", []) if s.get("num")}


def detect(old, new):
    now = datetime.now(timezone.utc).isoformat()
    entries = []

    old_races = race_index(old)
    new_races = race_index(new)

    for race_name, new_race in new_races.items():
        old_race = old_races.get(race_name, {})

        # ── Stage winners ────────────────────────────────────────────────────
        old_stages = stage_index(old_race)
        new_stages = stage_index(new_race)

        for num, new_stage in new_stages.items():
            winner = new_stage.get("winner")
            if not winner:
                continue
            old_winner = old_stages.get(num, {}).get("winner")
            if winner and winner != old_winner:
                flag = new_stage.get("winner_flag", "")
                entries.append({
                    "id":        entry_id(race_name, "stage", num, winner),
                    "timestamp": now,
                    "type":      "stage_result",
                    "icon":      "🏆",
                    "text":      f"Stage {num} {race_name}: {flag} {winner} wins",
                })

        # ── Single-day race winner ────────────────────────────────────────────
        if new_race.get("total_stages", 1) == 1:
            winner = new_race.get("winner")
            old_winner = old_race.get("winner")
            if winner and winner != old_winner:
                flag = new_race.get("winner_flag", "")
                entries.append({
                    "id":        entry_id(race_name, "oneday", winner),
                    "timestamp": now,
                    "type":      "race_result",
                    "icon":      "🏅",
                    "text":      f"{race_name}: {flag} {winner} wins",
                })

        # ── Classification leaders ────────────────────────────────────────────
        cls_map = {
            "gc_leader":     ("GC",     "🟡"),
            "points_leader": ("Points", "🟢"),
            "kom_leader":    ("KOM",    "🔴"),
            "youth_leader":  ("Youth",  "⬜"),
        }
        for key, (label, icon) in cls_map.items():
            new_leader = new_race.get(key, "")
            old_leader = old_race.get(key, "")
            if new_leader and new_leader != old_leader:
                entries.append({
                    "id":        entry_id(race_name, key, new_leader),
                    "timestamp": now,
                    "type":      "leader_change",
                    "icon":      icon,
                    "text":      f"{race_name} {label}: {new_leader} leads",
                })

        # ── Startlist additions ───────────────────────────────────────────────
        old_sl = {r["name"] for r in old_race.get("startlist", []) if r.get("name")}
        new_sl = {r["name"] for r in new_race.get("startlist", []) if r.get("name")}
        added = new_sl - old_sl
        if added and old_sl:  # only report if there was already a partial list
            sample = ", ".join(sorted(added)[:3])
            more = f" (+{len(added)-3} more)" if len(added) > 3 else ""
            entries.append({
                "id":        entry_id(race_name, "startlist", len(new_sl)),
                "timestamp": now,
                "type":      "startlist",
                "icon":      "👥",
                "text":      f"{race_name} startlist: {sample}{more} added",
            })
        elif new_sl and not old_sl:
            entries.append({
                "id":        entry_id(race_name, "startlist_new", len(new_sl)),
                "timestamp": now,
                "type":      "startlist",
                "icon":      "👥",
                "text":      f"{race_name} startlist published ({len(new_sl)} riders)",
            })

    return entries


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 detect_changes.py old.json new.json changelog.json")
        sys.exit(1)

    old_path, new_path, cl_path = sys.argv[1], sys.argv[2], sys.argv[3]

    old = load(old_path)
    new = load(new_path)

    new_entries = detect(old, new)
    print(f"  Changes detected: {len(new_entries)}", flush=True)
    for e in new_entries:
        print(f"    {e['icon']} {e['text']}", flush=True)

    # Load existing changelog
    changelog = load(cl_path, {"entries": []})
    existing_ids = {e["id"] for e in changelog.get("entries", []) if "id" in e}

    # Prune old entries
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CHANGELOG_MAX_DAYS)).isoformat()
    kept = [e for e in changelog.get("entries", []) if e.get("timestamp", "") >= cutoff]

    # Append new (deduped)
    for e in new_entries:
        if e["id"] not in existing_ids:
            kept.append(e)

    # Most recent first
    kept.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": kept,
    }

    with open(cl_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"  changelog.json: {len(kept)} total entries", flush=True)


if __name__ == "__main__":
    main()
