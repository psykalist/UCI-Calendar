"""
patch_v21c.py — race selector as dropdown, moved below instructions, no race limit.
Run on Windows: python patch_v21c.py
"""
import os, sys, subprocess, tempfile

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

print("Reading index.html from git HEAD...", flush=True)
html = git_show("index.html")

STEPS = []

# ── 1. Replace renderRaceSelector with dropdown version (no slice limit) ───────
STEPS.append(("renderRaceSelector → dropdown, no race limit",
"""function renderRaceSelector(){
  const teams=fantasyLoadAll();
  const activeKey=fantasyGetRace();
  const races=[...(appData.live||[]),...(appData.upcoming||[]),...(appData.recent||[])];
  const seen=new Set();
  const unique=races.filter(r=>{const k=_raceKey(r);if(!k||seen.has(k))return false;seen.add(k);return true;}).slice(0,8);
  if(!unique.length)return '';
  return '<div style="margin-bottom:14px">'
    +'<div style="font-size:.72rem;font-weight:700;color:var(--muted);letter-spacing:.7px;text-transform:uppercase;margin-bottom:8px">🏁 Pick a Race</div>'
    +'<div style="display:flex;gap:6px;overflow-x:auto;padding-bottom:2px;scrollbar-width:none">'
      +unique.map(r=>{
        const k=_raceKey(r);
        const has=!!teams[k];
        const active=k===activeKey;
        const label=r.name.length>20?r.name.slice(0,20)+'…':r.name;
        return '<button onclick="fSwitchRace(this.dataset.race)" data-race="'+k+'" style="flex:0 0 auto;padding:7px 12px;border-radius:8px;font-size:.75rem;font-weight:700;cursor:pointer;border:2px solid '+(active?'var(--upcoming)':'var(--border)')+';background:'+(active?'var(--upcoming)':'var(--surface)')+';color:'+(active?'#fff':'var(--text)')+';white-space:nowrap">'
          +esc(label)+(has?' ✓':'')
        +'</button>';
      }).join('')
    +'</div>'
  +'</div>';
}""",
"""function renderRaceSelector(){
  const teams=fantasyLoadAll();
  const activeKey=fantasyGetRace();
  const races=[...(appData.live||[]),...(appData.upcoming||[]),...(appData.recent||[])];
  const seen=new Set();
  const unique=races.filter(r=>{const k=_raceKey(r);if(!k||seen.has(k))return false;seen.add(k);return true;});
  if(!unique.length)return '';
  const opts=unique.map(r=>{
    const k=_raceKey(r);
    const has=!!teams[k];
    const label=esc(r.name)+(has?' ✓':'');
    return '<option value="'+k+'"'+(k===activeKey?' selected':'')+'>'+label+'</option>';
  }).join('');
  return '<div style="margin-bottom:14px">'
    +'<label style="display:block;font-size:.72rem;font-weight:700;color:var(--muted);letter-spacing:.7px;text-transform:uppercase;margin-bottom:6px">🏁 Pick a Race</label>'
    +'<select onchange="fSwitchRace(this.value)" style="width:100%;padding:10px 12px;border-radius:8px;border:2px solid var(--upcoming);background:var(--surface);color:var(--text);font-size:.88rem;font-weight:600;cursor:pointer;appearance:auto">'
      +'<option value="" disabled'+(activeKey?'':' selected')+'>— choose a race —</option>'
      +opts
    +'</select>'
  +'</div>';
}"""))

# ── 3. renderFantasy: move selector below instructions ─────────────────────────
# Current: selector → banner → howToPlay → rules
# New:     howToPlay → rules → selector (banner removed — selector shows active race)
STEPS.append(("renderFantasy: selector below instructions",
    "+renderRaceSelector()\n    +_raceBanner\n    +renderHowToPlay()\n    +renderRulesCard()",
    "+renderHowToPlay()\n    +renderRulesCard()\n    +renderRaceSelector()"))

# ── 4. renderFantasySetup: move selector below instructions ────────────────────
# Current: selector → srLabel header → howToPlay → rules → squad card
# New:     howToPlay → rules → selector → squad card (srLabel merged into selector label)
STEPS.append(("renderFantasySetup: selector below instructions",
    "+renderRaceSelector()\n    +'<div class=\"group-header\" style=\"padding-top:4px\">\U0001f3c1 '+esc(_srLabel)+'</div>'\n    +renderHowToPlay()\n    +renderRulesCard()",
    "+renderHowToPlay()\n    +renderRulesCard()\n    +renderRaceSelector()"))

# ── 5. Bump APP_VERSION ────────────────────────────────────────────────────────
STEPS.append(("Bump APP_VERSION to v21c",
    "const APP_VERSION = 'v21b'",
    "const APP_VERSION = 'v21c'"))

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

# Handle whichever version is currently in sw.js
for old_ver, new_ver in [("uci-calendar-v21b", "uci-calendar-v21c"),
                          ("uci-calendar-v21",  "uci-calendar-v21c")]:
    if old_ver in sw:
        sw = sw.replace(old_ver, new_ver)
        print(f"  ✓ Bumped CACHE_NAME to uci-calendar-v21c", flush=True)
        safe_write(sw_path, sw.encode("utf-8"))
        break
else:
    print("  ✗ CACHE_NAME not found in sw.js — check manually", flush=True)

print("\n✓ Done. Run pre_push_check.py to verify, then commit and push.", flush=True)
