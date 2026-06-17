"""
pre_push_check.py — validates all project files before a git push.
Run manually: python pre_push_check.py
Or install as a git hook: python pre_push_check.py --install

Exits with code 0 (OK to push) or 1 (blocked — fix issues first).
"""
import os, sys, re, json, subprocess, tempfile, shutil
from datetime import datetime, timezone, timedelta

BASE  = os.path.dirname(os.path.abspath(__file__))
PASS  = "\033[32m  ✓\033[0m"
FAIL  = "\033[31m  ✗\033[0m"
WARN  = "\033[33m  ⚠\033[0m"
BLOCK = "\033[31m\n  ╔══════════════════════════════════════╗\n  ║  PUSH BLOCKED — fix issues above    ║\n  ╚══════════════════════════════════════╝\033[0m"
OK    = "\033[32m\n  ✓ All checks passed — safe to push!\033[0m"

errors   = []
warnings = []

def ok(msg, detail=""):
    print(f"{PASS} {msg}" + (f"  ({detail})" if detail else ""))

def err(msg, detail=""):
    print(f"{FAIL} {msg}" + (f"  ({detail})" if detail else ""))
    errors.append(msg)

def warn(msg, detail=""):
    print(f"{WARN} {msg}" + (f"  ({detail})" if detail else ""))
    warnings.append(msg)

def path(f):
    return os.path.join(BASE, f)

def read(f, mode="r", enc="utf-8"):
    try:
        with open(path(f), mode, encoding=enc, errors="replace") as fh:
            return fh.read()
    except Exception as e:
        return None

# ─────────────────────────────────────────────────────────────────────────────
print("\n━━━ Pre-push check: UCI Calendar ━━━\n")

# ── 1. REQUIRED FILES ────────────────────────────────────────────────────────
print("[ Files ]")
for f in ["index.html", "sw.js", "data.json", "scraper.py",
          "detect_changes.py", "changelog.json", "manifest.json",
          ".github/workflows/scrape.yml"]:
    if os.path.exists(path(f)):
        ok(f)
    else:
        err(f, "MISSING")

# ── 2. INDEX.HTML ────────────────────────────────────────────────────────────
print("\n[ index.html ]")
html = read("index.html")
if html is None:
    err("index.html readable")
else:
    size = len(html)
    if size < 80_000:
        err("index.html size", f"{size:,} bytes — too small, likely truncated (expect >100KB)")
    else:
        ok("index.html size", f"{size:,} bytes")

    if "<script>" not in html:
        err("Has <script> tag")
    elif "</script>" not in html:
        err("Has </script> closing tag", "file truncated mid-script")
    else:
        ok("Script block complete")

    if "</html>" not in html:
        err("Has </html>")
    else:
        ok("HTML closes cleanly")

    app_v = re.search(r"APP_VERSION\s*=\s*'([^']+)'", html)
    ok("APP_VERSION", app_v.group(1)) if app_v else err("APP_VERSION defined")

    sq = re.search(r"MAX_SQUAD\s*=\s*(\d+)", html)
    (ok if sq and sq.group(1)=="9" else err)("MAX_SQUAD = 9", sq.group(1) if sq else "not found")

    bud = re.search(r"FANTASY_BUDGET\s*=\s*(\d+)", html)
    (ok if bud and bud.group(1)=="100" else err)("FANTASY_BUDGET = 100", bud.group(1) if bud else "not found")

    if "cyclingflash.com/svg/flags" in html:
        err("No cyclingflash SVG flags", "still present — breaks cross-origin")
    else:
        ok("No cyclingflash SVG flags")

    if "flagcdn.com" not in html:
        err("flagcdn.com used for flags")
    else:
        ok("flagcdn.com used")

    if "function fDoImport" not in html:
        err("fDoImport defined")
    else:
        ok("fDoImport defined")

    for bad in ["'12 riders'", "12 Riders to Continue", "Pick 12 riders",
                "exactly 12 riders", "/ 12 riders"]:
        if bad in html:
            err(f"No stale '12 riders' text", f"found: {bad!r}")
            break
    else:
        ok("No stale '12 riders' text")

    # JS syntax check
    m = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    if m and shutil.which("node"):
        fd, tmp = tempfile.mkstemp(suffix=".js")
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(m.group(1))
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        os.unlink(tmp)
        if r.returncode == 0:
            ok("JavaScript syntax")
        else:
            first_line = (r.stderr or "").strip().split("\n")[0]
            err("JavaScript syntax", first_line)
    elif not shutil.which("node"):
        warn("JavaScript syntax", "node not found — skipping")

# ── 3. SW.JS ─────────────────────────────────────────────────────────────────
print("\n[ sw.js ]")
sw = read("sw.js")
if sw and html:
    cache = re.search(r"CACHE_NAME\s*=\s*'([^']+)'", sw)
    app_v = re.search(r"APP_VERSION\s*=\s*'([^']+)'", html or "")
    if cache and app_v and app_v.group(1) in cache.group(1):
        ok("CACHE_NAME matches APP_VERSION", cache.group(1))
    else:
        err("CACHE_NAME matches APP_VERSION",
            f"sw={cache.group(1) if cache else '?'} vs app={app_v.group(1) if app_v else '?'}")

# ── 4. DATA.JSON ─────────────────────────────────────────────────────────────
print("\n[ data.json ]")
raw = read("data.json")
if raw is None:
    err("data.json readable")
else:
    try:
        data = json.loads(raw)
        size_kb = len(raw) // 1024
        if size_kb < 500:
            err("data.json size", f"{size_kb} KB — too small, likely truncated")
        else:
            ok("data.json size", f"{size_kb} KB")

        for key in ["upcoming","recent","teams"]:
            n = len(data.get(key, []))
            (ok if n > 0 else err)(f"Has {key}", f"{n} items")

        scraped = data.get("scraped_at","")
        if scraped:
            try:
                dt = datetime.fromisoformat(scraped.replace("Z","+00:00"))
                age = datetime.now(timezone.utc) - dt
                if age > timedelta(days=3):
                    warn("Data freshness", f"scraped {age.days}d ago — consider re-running scraper")
                else:
                    ok("Data freshness", f"scraped {age.days}d ago")
            except Exception:
                warn("Data freshness", f"can't parse date: {scraped}")

        tdf = next((r for r in data.get("upcoming",[]) if "france" in r.get("name","").lower()), None)
        if tdf:
            sl = len(tdf.get("startlist", []))
            (ok if sl > 0 else warn)("Tour de France startlist", f"{sl} riders")

    except json.JSONDecodeError as e:
        err("data.json valid JSON", str(e)[:80])

# ── 5. PYTHON SYNTAX ─────────────────────────────────────────────────────────
print("\n[ Python files ]")
for pyfile in ["scraper.py", "detect_changes.py"]:
    r = subprocess.run([sys.executable, "-m", "py_compile", path(pyfile)],
                       capture_output=True, text=True)
    if r.returncode == 0:
        ok(f"{pyfile} syntax")
    else:
        err(f"{pyfile} syntax", r.stderr.strip().split("\n")[-1])

# ── 6. CHANGELOG.JSON ────────────────────────────────────────────────────────
print("\n[ changelog.json ]")
cl = read("changelog.json")
try:
    json.loads(cl)
    ok("changelog.json valid JSON")
except Exception as e:
    err("changelog.json valid JSON", str(e)[:60])

# ── 7. GITHUB WORKFLOW ───────────────────────────────────────────────────────
print("\n[ GitHub Actions ]")
wf = read(".github/workflows/scrape.yml")
if wf:
    for check_str, label in [
        ("contents: write", "Workflow has write permissions"),
        ("cron:",           "Workflow has schedule"),
        ("scraper.py",      "Workflow runs scraper.py"),
        ("detect_changes",  "Workflow runs detect_changes.py"),
    ]:
        (ok if check_str in wf else err)(label)

# ── SUMMARY ──────────────────────────────────────────────────────────────────
print("\n" + "━"*42)
print(f"  Errors:   {len(errors)}")
print(f"  Warnings: {len(warnings)}")

if errors:
    for e in errors:
        print(f"    ✗ {e}")
    print(BLOCK)
    sys.exit(1)
else:
    if warnings:
        for w in warnings:
            print(f"    ⚠ {w}")
    print(OK)
    sys.exit(0)

