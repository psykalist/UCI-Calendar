"""
detect_changes.py — diff old vs new data.json, append to changelog.json

Usage:
    python3 detect_changes.py data_old.json data.json changelog.json
"""

import json
import sys
import hashlib
import os
from datetime import datetime, timezone, timedelta

CHANGELOG_MAX_DAYS = 14


def load(path, default=None):
    if default is None:
        default = {}
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return default
        return json.loads(content)
    except Exception as e:
        print(f"  warning: could not load {path}: {e}", flush=True)
        return default


def validate_data(d, label):
    warnings = []
    if not isinstance(d, dict):
        warnings.append(f"{label}: expected dict, got {type(d).__name__}")
        return warnings
    for key in ("live", "upcoming", "recent"):
        if key not in d:
            warnings.append(f"{label}: missing '{key}' key")
        elif not isinstance(d[key], list):
            warnings.append(f"{label}: '{key}' is not a list")
    total = sum(len(d.get(s, [])) for s in ("live", "upcoming", "recent"))
    if total == 0:
        warnings.append(f"{label}: zero races -- possibly empty/corrupt file")
    return warnings


def entry_id(*parts):
    key = "|".join(str(p) for p in parts)
    return hashlib.md5(key.encode()).hexdigest()[:12]


def race_index(data, sections=("live", "recent", "upcoming")):
    idx = {}
    if not isinstance(data, dict):
        return idx
    for sec in sections:
        for r in data.get(sec, []):
            if not isinstance(r, dict):
                continue
            name = r.get("name") or r.get("slug", "")
            if name:
                idx[name] = r
    return idx


def stage_index(race):
    if not isinstance(race, dict):
        return {}
    return {
        s["num"]: s
        for s in race.get("stages", [])
        if isinstance(s, dict) and s.get("num")
    }


def detect(old, new):
    now = datetime.now(timezone.utc).isoformat()
    entries = []

    old_races = race_index(old)
    new_races = race_index(new)

    for race_name, new_race in new_races.items():
        if not isinstance(new_race, dict):
            continue
        old_race = old_races.get(race_name, {})

        # Stage winners
        try:
            old_stages = stage_index(old_race)
            new_stages = stage_index(new_race)
            for num, new_stage in new_stages.items():
                if not isinstance(new_stage, dict):
                    continue
                winner = new_stage.get("winner")
                if not winner:
                    continue
                old_winner = old_stages.get(num, {}).get("winner")
                if winner != old_winner:
                    flag = new_stage.get("winner_flag", "")
                    entries.append({
                        "id":        entry_id(race_name, "stage", num, winner),
                        "timestamp": now,
                        "type":      "stage_result",
                        "icon":      "trophy",
                        "text":      f"Stage {num} {race_name}: {flag} {winner} wins",
                    })
        except Exception as e:
            print(f"  warning: stage detection error for {race_name}: {e}", flush=True)

        # Single-day race winner
        try:
            if new_race.get("total_stages", 1) == 1:
                winner = new_race.get("winner")
                old_winner = old_race.get("winner")
                if winner and winner != old_winner:
                    flag = new_race.get("winner_flag", "")
                    entries.append({
                        "id":        entry_id(race_name, "oneday", winner),
                        "timestamp": now,
                        "type":      "race_result",
                        "icon":      "medal",
                        "text":      f"{race_name}: {flag} {winner} wins",
                    })
        except Exception as e:
            print(f"  warning: one-day detection error for {race_name}: {e}", flush=True)

        # Classification leaders
        try:
            cls_map = {
                "gc_leader":     ("GC",     "yellow"),
                "points_leader": ("Points", "green"),
                "kom_leader":    ("KOM",    "red"),
                "youth_leader":  ("Youth",  "white"),
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
        except Exception as e:
            print(f"  warning: classification detection error for {race_name}: {e}", flush=True)

        # Startlist additions
        try:
            old_sl = {r.get("name","") for r in old_race.get("startlist", [])
                      if isinstance(r, dict) and r.get("name")}
            new_sl = {r.get("name","") for r in new_race.get("startlist", [])
                      if isinstance(r, dict) and r.get("name")}
            added = new_sl - old_sl
            if added and old_sl:
                sample = ", ".join(sorted(added)[:3])
                more = f" (+{len(added)-3} more)" if len(added) > 3 else ""
                entries.append({
                    "id":        entry_id(race_name, "startlist", len(new_sl)),
                    "timestamp": now,
                    "type":      "startlist",
                    "icon":      "group",
                    "text":      f"{race_name} startlist: {sample}{more} added",
                })
            elif new_sl and not old_sl:
                entries.append({
                    "id":        entry_id(race_name, "startlist_new", len(new_sl)),
                    "timestamp": now,
                    "type":      "startlist",
                    "icon":      "group",
                    "text":      f"{race_name} startlist published ({len(new_sl)} riders)",
                })
        except Exception as e:
            print(f"  warning: startlist detection error for {race_name}: {e}", flush=True)

    return entries


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 detect_changes.py old.json new.json changelog.json")
        sys.exit(1)

    old_path, new_path, cl_path = sys.argv[1], sys.argv[2], sys.argv[3]

    old = load(old_path, {"live": [], "upcoming": [], "recent": []})
    new = load(new_path, {"live": [], "upcoming": [], "recent": []})

    for d, label in ((old, "old data"), (new, "new data")):
        for w in validate_data(d, label):
            print(f"  warning: {w}", flush=True)

    new_total = sum(len(new.get(s, [])) for s in ("live", "upcoming", "recent"))
    if new_total == 0:
        print("  warning: new data has no races -- skipping change detection", flush=True)
        sys.exit(0)

    try:
        new_entries = detect(old, new)
    except Exception as e:
        print(f"  error: detect() crashed: {e}", flush=True)
        sys.exit(0)

    print(f"  Changes detected: {len(new_entries)}", flush=True)
    for e in new_entries:
        print(f"    {e.get('text','')}", flush=True)

    changelog = load(cl_path, {"entries": []})
    if not isinstance(changelog, dict):
        changelog = {"entries": []}

    existing_entries = changelog.get("entries", [])
    if not isinstance(existing_entries, list):
        existing_entries = []

    existing_ids = {
        e["id"] for e in existing_entries
        if isinstance(e, dict) and "id" in e
    }

    cutoff = (datetime.now(timezone.utc) - timedelta(days=CHANGELOG_MAX_DAYS)).isoformat()
    kept = [
        e for e in existing_entries
        if isinstance(e, dict) and "id" in e and e.get("timestamp", "") >= cutoff
    ]

    for e in new_entries:
        if e.get("id") not in existing_ids:
            kept.append(e)

    kept.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries":      kept,
    }

    try:
        tmp = cl_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, cl_path)
        print(f"  changelog.json: {len(kept)} total entries", flush=True)
    except Exception as e:
        print(f"  error: could not write changelog.json: {e}", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
