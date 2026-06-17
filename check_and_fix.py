"""
check_and_fix.py — validates and fixes all UCI Calendar project files.
Run from project folder: python check_and_fix.py
"""
import os, sys, json, re, subprocess, tempfile, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))

PASS = "  ✓"
FAIL = "  ✗"
FIX  = "  ↻"

issues = []
fixes  = []

def check(label, ok, detail=""):
    if ok:
        print(f"{PASS} {label}" + (f" — {detail}" if detail else ""), flush=True)
    else:
        print(f"{FAIL} {label}" + (f" — {detail}" if detail else ""), flush=True)
        issues.append(label)
    return ok

def safe_write(path, content):
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(path)[1], dir=os.path.dirname(path))
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)

# ── 1. FILE EXISTENCE ─────────────────────────────────────────────────────────
print("\n[1/6] Checking required files exist...")
required = ["index.html", "sw.js", "data.json", "scraper.py",
            "detect_changes.py", "changelog.json", "manifest.json",
            ".github/workflows/scrape.yml"]
for fname in required:
    path = os.path.join(BASE, fname)
    check(fname, os.path.exists(path))

# ── 2. DATA.JSON ──────────────────────────────────────────────────────────────
print("\n[2/6] Checking data.json...")
data_path = os.path.join(BASE, "data.json")
try:
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)
    size_kb = os.path.getsize(data_path) // 1024
    check("data.json valid JSON", True, f"{size_kb} KB")
    check("data.json has upcoming", bool(data.get("upcoming")), f"{len(data.get('upcoming',[]))} races")
    check("data.json has recent",   bool(data.get("recent")),   f"{len(data.get('recent',[]))} races")
    check("data.json has teams",    bool(data.get("teams")),    f"{len(data.get('teams',[]))} teams")
    tds = next((r for r in data.get("upcoming",[]) if "suisse" in r.get("name","").lower()), None)
    tdf = next((r for r in data.get("upcoming",[]) if "france" in r.get("name","").lower()), None)
    check("Tour de Suisse startlist", tds and len(tds.get("startlist",[])) > 0,
          f"{len(tds.get('startlist',[]))} riders" if tds else "not found")
    check("Tour de France startlist", tdf and len(tdf.get("startlist",[])) > 0,
          f"{len(tdf.get('startlist',[]))} riders" if tdf else "not found")
except Exception as e:
    check("data.json valid JSON", False, str(e))

# ── 3. CHANGELOG.JSON ─────────────────────────────────────────────────────────
print("\n[3/6] Checking changelog.json...")
cl_path = os.path.join(BASE, "changelog.json")
try:
    with open(cl_path, encoding="utf-8") as f:
        cl = json.load(f)
    check("changelog.json valid", True, f"{len(cl.get('entries',[]))} entries")
except Exception as e:
    check("changelog.json valid", False, str(e))

# ── 4. INDEX.HTML ─────────────────────────────────────────────────────────────
print("\n[4/6] Checking index.html...")
html_path = os.path.join(BASE, "index.html")
with open(html_path, encoding="utf-8", errors="replace") as f:
    html = f.read()

size_kb = len(html) // 1024
check("index.html exists", True, f"{size_kb} KB / {len(html):,} bytes")
check("index.html has <script>",    "<script>" in html)
check("index.html has </script>",   "</script>" in html)
check("index.html has </html>",     "</html>" in html)

app_v = re.search(r"APP_VERSION\s*=\s*'([^']+)'", html)
check("APP_VERSION defined", bool(app_v), app_v.group(1) if app_v else "not found")

max_sq = re.search(r"MAX_SQUAD\s*=\s*(\d+)", html)
check("MAX_SQUAD = 9", max_sq and max_sq.group(1) == "9",
      max_sq.group(1) if max_sq else "not found")

budget = re.search(r"FANTASY_BUDGET\s*=\s*(\d+)", html)
check("FANTASY_BUDGET = 100", budget and budget.group(1) == "100",
      budget.group(1) if budget else "not found")

check("No cyclingflash SVG flags", "cyclingflash.com/svg/flags" not in html)
check("flagcdn.com used",          "flagcdn.com" in html)
check("fDoImport defined",         "function fDoImport" in html)
check("No '12 riders' strings",    "'12 riders'" not in html and "12 Riders" not in html)

# Syntax-check the JS
m = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
if m:
    js = m.group(1)
    fd, tmp = tempfile.mkstemp(suffix=".js")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(js)
    r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    os.unlink(tmp)
    check("JavaScript syntax OK", r.returncode == 0,
          "OK" if r.returncode == 0 else r.stderr.strip().split("\n")[0])
else:
    check("JavaScript syntax OK", False, "no <script> block found")

# ── 4b. AUTO-FIX INDEX.HTML ───────────────────────────────────────────────────
html_needs_fix = False

# Fix: broken fModal string (+'<butto\n     n id= should be +'<button id=)
BROKEN = "+'<butto\n     n id="
if BROKEN in html:
    print(f"\n{FIX} Fixing broken fModal string concatenation...", flush=True)
    html = html.replace(BROKEN, "+'<button id=", 1)
    html_needs_fix = True
    fixes.append("fModal string concatenation fixed")

# Fix: missing closing tags
if "</script>" not in html:
    print(f"{FIX} Appending missing </script></body></html>...", flush=True)
    # Find end of JS (after last closing brace)
    html = html.rstrip() + "\n}\n</script>\n</body>\n</html>\n"
    html_needs_fix = True
    fixes.append("Appended missing closing tags")

if html_needs_fix:
    safe_write(html_path, html)
    print(f"  Saved index.html ({len(html):,} bytes)", flush=True)

    # Re-validate JS after fix
    m2 = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    if m2:
        fd, tmp = tempfile.mkstemp(suffix=".js")
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f: f.write(m2.group(1))
        r2 = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        os.unlink(tmp)
        check("JavaScript syntax OK (after fix)", r2.returncode == 0,
              "OK" if r2.returncode == 0 else r2.stderr.strip().split("\n")[0])

# ── 5. SW.JS ──────────────────────────────────────────────────────────────────
print("\n[5/6] Checking sw.js...")
sw_path = os.path.join(BASE, "sw.js")
with open(sw_path, encoding="utf-8") as f:
    sw = f.read()
cache = re.search(r"CACHE_NAME\s*=\s*'([^']+)'", sw)
check("sw.js CACHE_NAME matches APP_VERSION",
      bool(cache) and bool(app_v) and app_v.group(1) in cache.group(0),
      cache.group(1) if cache else "not found")

# ── 6. GITHUB ACTIONS WORKFLOW ────────────────────────────────────────────────
print("\n[6/6] Checking .github/workflows/scrape.yml...")
wf_path = os.path.join(BASE, ".github", "workflows", "scrape.yml")
with open(wf_path, encoding="utf-8") as f:
    wf = f.read()
check("Workflow has permissions: write", "contents: write" in wf)
check("Workflow has schedule",           "cron:" in wf)
check("Workflow has workflow_dispatch",  "workflow_dispatch" in wf)
check("Workflow runs scraper.py",        "scraper.py" in wf)
check("Workflow runs detect_changes.py","detect_changes.py" in wf)

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print("\n" + "="*50, flush=True)
print(f"Issues found:  {len(issues)}", flush=True)
print(f"Auto-fixed:    {len(fixes)}", flush=True)
if issues:
    print("Remaining issues:", flush=True)
    for i in issues: print(f"  • {i}", flush=True)
if fixes:
    print("Fixed:", flush=True)
    for f in fixes: print(f"  • {f}", flush=True)
    print("\nNow run:", flush=True)
    print('  bash git-push.sh "fix: check_and_fix auto-repairs (v20)"', flush=True)
else:
    print("All checks passed — nothing to fix.", flush=True)
