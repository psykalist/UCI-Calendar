"""
heal.py — UCI Calendar self-healing monitor.

Checks data integrity, clears stale locks, repairs what it can,
and writes heal.log + status.json so both you and GitHub Actions
can see the current health at a glance.

Usage:
    py heal.py              # check + repair (default)
    py heal.py --push       # also commit + push status.json to GitHub
    py heal.py --status     # print current status.json and exit
    py heal.py --fix-all    # force-apply specialty cache + restore if needed

Schedule via Windows Task Scheduler: every 5 minutes.
Log:    heal.log  (last 1000 lines kept)
State:  status.json  (machine-readable, pushed to GitHub)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta

# Force UTF-8 output so emoji don't crash on Windows cp1252 consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Config ────────────────────────────────────────────────────────────────────
BASE            = os.path.dirname(os.path.abspath(__file__))
LOG_FILE        = os.path.join(BASE, "heal.log")
STATUS_FILE     = os.path.join(BASE, "status.json")
DATA_FILE       = os.path.join(BASE, "data.json")
CACHE_FILE      = os.path.join(BASE, "specialty_cache.json")
CHANGELOG_FILE  = os.path.join(BASE, "changelog.json")
INDEX_FILE      = os.path.join(BASE, "index.html")
SW_FILE         = os.path.join(BASE, "sw.js")
WRITE_LOCK      = os.path.join(BASE, ".data_write.lock")
SPECIALTY_LOCK  = os.path.join(BASE, ".specialty_last_run")
GIT_INDEX_LOCK  = os.path.join(BASE, ".git", "index.lock")
GIT_HEAD_LOCK   = os.path.join(BASE, ".git", "HEAD.lock")

LOG_MAX_LINES   = 1000
LOCK_STALE_SECS = 300       # lock files older than 5 min are stale
DATA_WARN_HOURS = 26        # warn if data older than this
DATA_ERROR_HOURS = 72       # error if data older than this
SPECIALTY_WARN_PCT = 80     # warn if fewer than this % of riders have specialties

# ── Logging ───────────────────────────────────────────────────────────────────
_log_lines = []

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    _log_lines.append(line)

def flush_log():
    """Append new lines to heal.log, keeping only the last LOG_MAX_LINES."""
    try:
        existing = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, encoding="utf-8") as f:
                existing = f.readlines()
        combined = existing + [l + "\n" for l in _log_lines]
        trimmed  = combined[-LOG_MAX_LINES:]
        fd, tmp  = tempfile.mkstemp(dir=BASE, suffix=".log")
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(trimmed)
        os.replace(tmp, LOG_FILE)
    except Exception as e:
        print(f"  [WARN] Could not write heal.log: {e}", flush=True)

# ── Status tracking ───────────────────────────────────────────────────────────
_errors   = []
_warnings = []
_repairs  = []
_info     = {}

def record_error(msg):
    _errors.append(msg)
    log(msg, "ERROR")

def record_warning(msg):
    _warnings.append(msg)
    log(msg, "WARN")

def record_repair(msg):
    _repairs.append(msg)
    log(msg, "REPAIR")

def record_ok(msg):
    log(msg, "OK")

# ── Helpers ───────────────────────────────────────────────────────────────────
def safe_write_json(path, obj):
    fd, tmp = tempfile.mkstemp(dir=BASE, suffix=".json")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def file_age_secs(path):
    return time.time() - os.path.getmtime(path)

def run(cmd, cwd=BASE):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)

# ── Checks ────────────────────────────────────────────────────────────────────

def check_lock_files():
    """Clear stale lock files that would block writes or specialty fetches."""
    for lf, label in [
        (WRITE_LOCK,     ".data_write.lock"),
        (SPECIALTY_LOCK, ".specialty_last_run"),
        (GIT_INDEX_LOCK, ".git/index.lock"),
        (GIT_HEAD_LOCK,  ".git/HEAD.lock"),
    ]:
        if not os.path.exists(lf):
            continue
        age = file_age_secs(lf)
        if age > LOCK_STALE_SECS:
            try:
                os.remove(lf)
                record_repair(f"Deleted stale {label} (age {int(age)}s)")
            except Exception as e:
                record_warning(f"Could not delete stale {label}: {e}")
        else:
            log(f"{label} exists but is fresh ({int(age)}s old) — leaving it")


def check_data_json():
    """Validate data.json: JSON integrity, size, freshness, structure."""
    if not os.path.exists(DATA_FILE):
        record_error("data.json missing")
        return None

    size_kb = os.path.getsize(DATA_FILE) // 1024
    _info["data_size_kb"] = size_kb

    if size_kb < 200:
        record_error(f"data.json too small ({size_kb} KB) — likely truncated")
        _attempt_restore_data()
        return None

    try:
        data = load_json(DATA_FILE)
    except json.JSONDecodeError as e:
        record_error(f"data.json invalid JSON: {e}")
        _attempt_restore_data()
        return None

    record_ok(f"data.json valid JSON ({size_kb} KB)")

    # Structure
    for key in ("upcoming", "recent", "teams"):
        n = len(data.get(key, []))
        _info[f"data_{key}"] = n
        if n == 0:
            record_warning(f"data.json has no {key}")
        else:
            record_ok(f"data.{key}: {n} items")

    # Rider profiles
    profiles = data.get("rider_profiles", {})
    _info["rider_profiles"] = len(profiles)
    record_ok(f"rider_profiles: {len(profiles)} riders")

    # Freshness
    scraped = data.get("scraped_at", "")
    _info["scraped_at"] = scraped
    if scraped:
        try:
            dt  = datetime.fromisoformat(scraped.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - dt
            age_h = age.total_seconds() / 3600
            _info["data_age_hours"] = round(age_h, 1)
            if age_h > DATA_ERROR_HOURS:
                record_error(f"data.json is {age.days}d old — scraper may have stopped")
            elif age_h > DATA_WARN_HOURS:
                record_warning(f"data.json is {age_h:.0f}h old — CI should update soon")
            else:
                record_ok(f"data.json freshness: {age_h:.1f}h old")
        except Exception:
            record_warning(f"Could not parse scraped_at: {scraped}")
    else:
        record_warning("data.json has no scraped_at timestamp")

    return data


def check_specialty_coverage(data):
    """Count riders missing specialty data. Apply cache if available."""
    if data is None:
        return

    profiles = data.get("rider_profiles", {})
    if not profiles:
        return

    missing   = [s for s, p in profiles.items() if "specialties" not in p]
    has_data  = sum(1 for p in profiles.values()
                    if p.get("specialties") and len(p["specialties"]) > 0)
    empty     = sum(1 for p in profiles.values()
                    if "specialties" in p and not p["specialties"])
    total     = len(profiles)
    covered   = total - len(missing)
    pct       = round(100 * covered / total, 1) if total else 0

    _info["specialties_missing"]  = len(missing)
    _info["specialties_with_data"]= has_data
    _info["specialties_empty"]    = empty
    _info["specialties_covered"]  = covered
    _info["specialty_pct"]        = pct

    log(f"Specialty coverage: {covered}/{total} checked ({pct}%), "
        f"{has_data} with real data, {len(missing)} missing, {empty} confirmed-empty")

    if len(missing) > 0 and os.path.exists(CACHE_FILE):
        _maybe_apply_specialty_cache(data, missing)

    if pct < SPECIALTY_WARN_PCT:
        record_warning(
            f"Only {pct}% of riders have specialty checked "
            f"— run: py backfill_specialties.py"
        )


def _maybe_apply_specialty_cache(data, missing_slugs):
    """If specialty_cache.json has entries for missing riders, apply them now."""
    try:
        cache = load_json(CACHE_FILE)
    except Exception as e:
        record_warning(f"Could not load specialty_cache.json: {e}")
        return

    applicable = [s for s in missing_slugs if s in cache]
    if not applicable:
        return

    profiles = data["rider_profiles"]
    for slug in applicable:
        entry = cache[slug]
        profiles[slug]["specialties"]            = entry["specialties"]
        profiles[slug]["specialties_fetched_at"] = entry.get("fetched_at", "")

    try:
        safe_write_json(DATA_FILE, data)
        record_repair(
            f"Applied {len(applicable)} specialty entries from cache "
            f"({len(missing_slugs) - len(applicable)} still missing)"
        )
        _info["specialties_missing"] -= len(applicable)
        _info["specialties_covered"] += len(applicable)
    except Exception as e:
        record_error(f"Failed to write data.json after applying cache: {e}")


def _attempt_restore_data():
    """Try to restore data.json from last git commit."""
    log("Attempting git restore of data.json...", "REPAIR")
    r = run(["git", "checkout", "HEAD", "--", "data.json"])
    if r.returncode == 0:
        record_repair("Restored data.json from git HEAD")
    else:
        record_error(f"git restore failed: {r.stderr.strip()[:120]}")


def check_changelog():
    if not os.path.exists(CHANGELOG_FILE):
        record_warning("changelog.json missing")
        return
    try:
        cl = load_json(CHANGELOG_FILE)
        n  = len(cl.get("entries", []))
        _info["changelog_entries"] = n
        record_ok(f"changelog.json valid ({n} entries)")
    except Exception as e:
        record_error(f"changelog.json invalid: {e}")


def check_index_html():
    if not os.path.exists(INDEX_FILE):
        record_error("index.html missing")
        return
    size = os.path.getsize(INDEX_FILE)
    _info["index_html_bytes"] = size
    if size < 80_000:
        record_error(f"index.html too small ({size:,} bytes) — likely truncated")
        return
    record_ok(f"index.html size OK ({size:,} bytes)")

    with open(INDEX_FILE, encoding="utf-8", errors="replace") as f:
        html = f.read()

    if "</html>" not in html:
        record_error("index.html missing </html> — file truncated")
    if "</script>" not in html:
        record_error("index.html missing </script> — JS block incomplete")

    # JS syntax check (requires node)
    m = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    if m:
        import shutil
        if shutil.which("node"):
            fd, tmp = tempfile.mkstemp(suffix=".js", dir=BASE)
            os.close(fd)
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(m.group(1))
                r = run(["node", "--check", tmp])
                if r.returncode == 0:
                    record_ok("index.html JavaScript syntax OK")
                    _info["js_syntax_ok"] = True
                else:
                    first = (r.stderr or "").strip().split("\n")[0]
                    record_error(f"index.html JavaScript syntax error: {first}")
                    _info["js_syntax_ok"] = False
            finally:
                try: os.remove(tmp)
                except: pass
        else:
            log("node not found — skipping JS syntax check", "WARN")


def check_git_sync():
    """Warn if local branch is behind origin/main."""
    r = run(["git", "fetch", "--dry-run", "origin", "main"])
    # A real check: compare HEAD vs origin/main
    r2 = run(["git", "rev-list", "--count", "HEAD..origin/main"])
    if r2.returncode == 0:
        behind = int(r2.stdout.strip() or "0")
        _info["git_behind"] = behind
        if behind > 0:
            record_warning(f"Local branch is {behind} commit(s) behind origin/main — run git pull")
        else:
            record_ok("Git in sync with origin/main")


# ── Status JSON ───────────────────────────────────────────────────────────────

def write_status():
    overall = "ok"
    if _errors:
        overall = "error"
    elif _warnings:
        overall = "warning"

    status = {
        "updated_at":  datetime.now(timezone.utc).isoformat(),
        "source":      "local",
        "overall":     overall,
        "errors":      _errors,
        "warnings":    _warnings,
        "repairs":     _repairs,
        "data":        _info,
    }
    safe_write_json(STATUS_FILE, status)
    return overall


def print_summary(overall):
    icons = {"ok": "✅", "warning": "⚠️ ", "error": "❌"}
    print(f"\n{'='*52}", flush=True)
    print(f"  {icons.get(overall, '?')}  STATUS: {overall.upper()}", flush=True)
    if _repairs:
        print(f"\n  Repairs made ({len(_repairs)}):", flush=True)
        for r in _repairs: print(f"    ↻  {r}", flush=True)
    if _warnings:
        print(f"\n  Warnings ({len(_warnings)}):", flush=True)
        for w in _warnings: print(f"    ⚠  {w}", flush=True)
    if _errors:
        print(f"\n  Errors ({len(_errors)}):", flush=True)
        for e in _errors: print(f"    ✗  {e}", flush=True)
    if not _repairs and not _warnings and not _errors:
        print("  Everything looks healthy.", flush=True)
    print(f"{'='*52}\n", flush=True)


# ── Git push ──────────────────────────────────────────────────────────────────

def git_push_status():
    """Commit and push status.json (and data.json if it changed)."""
    r = run(["git", "status", "--porcelain", "status.json", "data.json"])
    changed = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    if not changed:
        log("No changes to push")
        return

    files = ["status.json"]
    if any("data.json" in l for l in changed):
        files.append("data.json")

    run(["git", "add"] + files)
    ts  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = f"heal: status update {ts}"
    r2  = run(["git", "commit", "-m", msg])
    if r2.returncode != 0:
        record_warning(f"git commit failed: {r2.stderr.strip()[:80]}")
        return

    r3 = run(["git", "push"])
    if r3.returncode == 0:
        record_repair(f"Pushed {', '.join(files)} to GitHub")
    else:
        record_warning(f"git push failed: {r3.stderr.strip()[:80]}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = set(sys.argv[1:])

    # --status: just print existing status.json
    if "--status" in args:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, encoding="utf-8") as f:
                s = json.load(f)
            print(json.dumps(s, indent=2))
        else:
            print("No status.json found. Run: py heal.py")
        return

    log("=" * 52)
    log("heal.py starting")

    # 1. Stale lock files
    log("--- Checking lock files ---")
    check_lock_files()

    # 2. data.json
    log("--- Checking data.json ---")
    data = check_data_json()

    # 3. Specialty coverage (+ auto-apply cache)
    log("--- Checking specialty coverage ---")
    check_specialty_coverage(data)

    # 4. changelog.json
    log("--- Checking changelog.json ---")
    check_changelog()

    # 5. index.html
    log("--- Checking index.html ---")
    check_index_html()

    # 6. Git sync
    log("--- Checking git sync ---")
    check_git_sync()

    # Write outputs
    overall = write_status()
    flush_log()
    print_summary(overall)

    if "--push" in args:
        git_push_status()
        flush_log()


if __name__ == "__main__":
    main()
