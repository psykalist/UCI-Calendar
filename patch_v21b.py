"""
patch_v21b.py — fixes daysUntil() rounding bug, bumps version to v21b.
Run on Windows: python patch_v21b.py
"""
import os, sys, subprocess, tempfile, re

BASE = os.path.dirname(os.path.abspath(__file__))

def safe_write(dest, content_bytes):
    suffix = os.path.splitext(dest)[1]
    fd, tmp = tempfile.mkstemp(suffix=suffix, dir=os.path.dirname(dest))
    os.close(fd)
    with open(tmp, "wb") as f:
        f.write(content_bytes)
    os.replace(tmp, dest)
    print(f"  ✓ Wrote {os.path.basename(dest)} ({len(content_bytes):,} bytes)", flush=True)

def git_show(fname):
    r = subprocess.run(["git", "show", f"HEAD:{fname}"], capture_output=True, cwd=BASE)
    if r.returncode != 0:
        print(f"  ✗ git show {fname} failed: {r.stderr.decode()[:200]}", flush=True)
        sys.exit(1)
    return r.stdout.decode("utf-8")

# ── Patch index.html ──────────────────────────────────────────────────────────
print("Reading index.html from git HEAD...", flush=True)
html = git_show("index.html")
orig_len = len(html)

STEPS = []

# 1. Fix daysUntil — compare against midnight today, not current time
OLD_DAYS = (
    "function daysUntil(iso) {\n"
    "  if (!iso) return 999;\n"
    "  return Math.round((new Date(iso+'T00:00:00') - new Date()) / 86400000);\n"
    "}"
)
NEW_DAYS = (
    "function daysUntil(iso) {\n"
    "  if (!iso) return 999;\n"
    "  const today = new Date(); today.setHours(0,0,0,0);\n"
    "  return Math.round((new Date(iso+'T00:00:00') - today) / 86400000);\n"
    "}"
)
STEPS.append(("Fix daysUntil()", OLD_DAYS, NEW_DAYS))

# 2. Bump APP_VERSION
STEPS.append(("Bump APP_VERSION to v21b",
    "const APP_VERSION = 'v21'",
    "const APP_VERSION = 'v21b'"))

errors = 0
for label, old, new in STEPS:
    count = html.count(old)
    if count == 0:
        print(f"  ✗ NOT FOUND: {label}", flush=True)
        errors += 1
    elif count > 1:
        print(f"  ✗ AMBIGUOUS ({count} matches): {label}", flush=True)
        errors += 1
    else:
        html = html.replace(old, new)
        print(f"  ✓ {label}", flush=True)

if errors:
    print(f"\n✗ {errors} step(s) failed — aborting.", flush=True)
    sys.exit(1)

dest_html = os.path.join(BASE, "index.html")
safe_write(dest_html, html.encode("utf-8"))

# ── Patch sw.js ───────────────────────────────────────────────────────────────
print("\nPatching sw.js...", flush=True)
sw_path = os.path.join(BASE, "sw.js")
with open(sw_path, "r", encoding="utf-8") as f:
    sw = f.read()

sw_old = "const CACHE_NAME = 'uci-calendar-v21'"
sw_new = "const CACHE_NAME = 'uci-calendar-v21b'"
if sw_old in sw:
    sw = sw.replace(sw_old, sw_new)
    print("  ✓ Bumped CACHE_NAME to uci-calendar-v21b", flush=True)
    safe_write(sw_path, sw.encode("utf-8"))
else:
    print("  ✗ CACHE_NAME v21 not found in sw.js — check manually", flush=True)

print("\n✓ Done. Run pre_push_check.py to verify, then commit and push.", flush=True)
