"""
patch_v21.py — upgrades UCI Calendar to v21.

Changes:
  - Teams are now per-race: pick a race, build your 9, stored under that race
  - Race selector strip at top of Fantasy tab
  - No swaps / transfers
  - APP_VERSION v21, sw.js cache uci-calendar-v21

Run on Windows: python patch_v21.py
"""
import os, sys, subprocess, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))

def safe_write(dest, content):
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(dest)[1], dir=os.path.dirname(dest))
    os.close(fd)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    os.replace(tmp, dest)
    print(f'  OK  {os.path.basename(dest)}  ({len(content):,} chars)', flush=True)

def require(condition, msg):
    if not condition:
        print(f'  ERR {msg}', flush=True)
        sys.exit(1)

def patch(html, old, new, label):
    if old not in html:
        print(f'  !!  {label}: target string not found — skipping', flush=True)
        return html
    result = html.replace(old, new, 1)
    print(f'  OK  {label}', flush=True)
    return result

# ── Get clean base from git HEAD ───────────────────────────────────────────
r = subprocess.run(['git', 'show', 'HEAD:index.html'], capture_output=True, cwd=BASE)
require(r.returncode == 0, f'git show index.html failed: {r.stderr.decode()[:100]}')
html = r.stdout.decode('utf-8', errors='replace')
print(f'\nBase: index.html from git HEAD ({len(html):,} chars)\n')

# ══════════════════════════════════════════════════════════════════════════════
# 1. APP_VERSION
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    "const APP_VERSION = 'v20'",
    "const APP_VERSION = 'v21'",
    'APP_VERSION v21')

# ══════════════════════════════════════════════════════════════════════════════
# 2. Fix "12" squad-size in rules card (lingering stale value)
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    '\'<div style="font-size:1.4rem;font-weight:800;color:var(--text)">12</div>\'',
    '\'<div style="font-size:1.4rem;font-weight:800;color:var(--text)">9</div>\'',
    'Fix squad size 12→9 in rules card')

# ══════════════════════════════════════════════════════════════════════════════
# 3. Rules card transfers cell → "TEAMS" ∞
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    '\'<div style="background:var(--surface2);border-radius:8px;padding:10px;text-align:center">\'\n'
    '          +\'<div style="font-size:1.4rem;font-weight:800;color:#2dd36f">5</div>\'\n'
    '          +\'<div style="font-size:.72rem;color:var(--muted);margin-top:2px">TRANSFERS</div>\'\n'
    '        +\'</div>\'',
    '\'<div style="background:var(--surface2);border-radius:8px;padding:10px;text-align:center">\'\n'
    '          +\'<div style="font-size:1.4rem;font-weight:800;color:#2dd36f">∞</div>\'\n'
    '          +\'<div style="font-size:.72rem;color:var(--muted);margin-top:2px">TEAMS</div>\'\n'
    '        +\'</div>\'',
    'Rules card: transfers→teams')

# ══════════════════════════════════════════════════════════════════════════════
# 4. Replace storage constants + functions with race-keyed multi-team system
# ══════════════════════════════════════════════════════════════════════════════
OLD_STORAGE = (
    "function fantasyLoad(){try{return JSON.parse(localStorage.getItem(FANTASY_TEAM_KEY)||'null');}catch(e){return null;}}\n"
    "function fantasySave(t){localStorage.setItem(FANTASY_TEAM_KEY,JSON.stringify(t));}"
)
NEW_STORAGE = """\
const FANTASY_TEAMS_KEY  = 'fantasy_race_teams';   // {raceKey: team}
const FANTASY_ACTIVE_KEY = 'fantasy_active_race';  // currently viewed race key

function _raceKey(r){return r?(r.slug||r.name||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,''):'';}
function _autoRace(){
  const races=[...(appData.live||[]),...(appData.upcoming||[])];
  for(const r of races){const k=_raceKey(r);if(k)return k;}
  return '';
}
function fantasyLoadAll(){try{const s=localStorage.getItem(FANTASY_TEAMS_KEY);if(s)return JSON.parse(s);}catch(e){}return {};}
function fantasySaveAll(d){localStorage.setItem(FANTASY_TEAMS_KEY,JSON.stringify(d));}
function fantasyGetRace(){const k=localStorage.getItem(FANTASY_ACTIVE_KEY)||'';return k||_autoRace();}
function fantasySetRace(k){localStorage.setItem(FANTASY_ACTIVE_KEY,k);}
function fantasyLoad(){const d=fantasyLoadAll(),k=fantasyGetRace();return k?d[k]||null:null;}
function fantasySave(t){const d=fantasyLoadAll(),k=fantasyGetRace();if(k){d[k]=t;fantasySaveAll(d);}}
function fantasyDelete(){const d=fantasyLoadAll(),k=fantasyGetRace();if(k){delete d[k];fantasySaveAll(d);}}"""
html = patch(html, OLD_STORAGE, NEW_STORAGE, 'Storage: race-keyed multi-team')

# ══════════════════════════════════════════════════════════════════════════════
# 5. Fix the stale removeItem(FANTASY_TEAM_KEY) in renderFantasy body
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    'localStorage.removeItem(FANTASY_TEAM_KEY);',
    'fantasyDelete();',
    'renderFantasy: removeItem→fantasyDelete')

# ══════════════════════════════════════════════════════════════════════════════
# 6. Add renderRaceSelector + fSwitchRace just before renderFantasy()
# ══════════════════════════════════════════════════════════════════════════════
RACE_SELECTOR_FNS = """\
function renderRaceSelector(){
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
}

function fSwitchRace(key){
  fantasySetRace(key);
  draftClear();_fPicked=[];
  renderFantasy();
}

"""
html = patch(html,
    'function renderFantasy(){',
    RACE_SELECTOR_FNS + 'function renderFantasy(){',
    'Add renderRaceSelector + fSwitchRace')

# ══════════════════════════════════════════════════════════════════════════════
# 7. renderFantasy: add race selector + race label to the "has team" view
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    "  el.innerHTML='<div style=\"max-width:480px;margin:0 auto;padding:16px\">'\n"
    "    +renderHowToPlay()\n"
    "    +renderRulesCard()\n"
    "    +'</div>'\n"
    "    +renderLeagueTable(allTeams)+renderMySquad(myTeam,total,breakdown)+renderWatchlist(watchLoad());",

    "  const _ark=fantasyGetRace();\n"
    "  const _arl=[...(appData.live||[]),...(appData.upcoming||[]),...(appData.recent||[])].find(r=>_raceKey(r)===_ark);\n"
    "  const _raceBanner=_arl?'<div style=\"font-size:.82rem;font-weight:700;color:var(--accent);margin-bottom:12px\">🏁 '+esc(_arl.name)+'</div>':'';\n"
    "  el.innerHTML='<div style=\"max-width:480px;margin:0 auto;padding:16px\">'\n"
    "    +renderRaceSelector()\n"
    "    +_raceBanner\n"
    "    +renderHowToPlay()\n"
    "    +renderRulesCard()\n"
    "    +'</div>'\n"
    "    +renderLeagueTable(allTeams)+renderMySquad(myTeam,total,breakdown)+renderWatchlist(watchLoad());",
    'renderFantasy: race selector + banner in team view')

# ══════════════════════════════════════════════════════════════════════════════
# 8. renderFantasySetup: add race selector + race label as title
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    "  const html = '<div style=\"max-width:480px;margin:0 auto;padding:16px\">'\n"
    "    +'<div class=\"group-header\" style=\"padding-top:4px\">&#127942; Create Your Fantasy Team</div>'\n"
    "    +renderHowToPlay()",

    "  const _srk=fantasyGetRace();\n"
    "  const _srl=[...(appData.live||[]),...(appData.upcoming||[]),...(appData.recent||[])].find(r=>_raceKey(r)===_srk);\n"
    "  const _srLabel=_srl?_srl.name:'Select a race above';\n"
    "  const html = '<div style=\"max-width:480px;margin:0 auto;padding:16px\">'\n"
    "    +renderRaceSelector()\n"
    "    +'<div class=\"group-header\" style=\"padding-top:4px\">🏁 '+esc(_srLabel)+'</div>'\n"
    "    +renderHowToPlay()",
    'renderFantasySetup: race selector + dynamic title')

# ══════════════════════════════════════════════════════════════════════════════
# 9. renderMySquad: strip transfers/swap UI
# ══════════════════════════════════════════════════════════════════════════════
# Remove "left" + "tCol" vars
html = patch(html,
    'function renderMySquad(team,total,breakdown){\n'
    '  const left=team.transfers_total-(team.transfers_used||0);\n'
    '  const tCol=left===0?\'var(--live)\':left<=2?\'var(--accent)\":\'#2dd36f\';\n\n'
    '  const totalCost=squadCost(team.riders);',
    'function renderMySquad(team,total,breakdown){\n'
    '  const totalCost=squadCost(team.riders);',
    'renderMySquad: remove transfers vars')

# Remove per-rider Swap button
html = patch(html,
    "      +(left>0?'<button data-swap=\"'+esc(r.name)+'\" style=\"background:var(--surface2);border:1px solid var(--border);border-radius:4px;color:var(--muted);font-size:.72rem;padding:3px 7px;cursor:pointer\">Swap</button>':'')",
    '',
    'renderMySquad: remove swap button from rider row')

# Remove TRANSFERS LEFT stat block
html = patch(html,
    "        +'<div style=\"text-align:right\"><div style=\"font-size:1.2rem;font-weight:800;color:'+tCol+'\">'+left+'</div><div style=\"font-size:.7rem;color:var(--muted)\">TRANSFERS LEFT</div></div>'",
    '',
    'renderMySquad: remove transfers left stat')

# Remove swapPanel definition
html = patch(html,
    "  const swapPanel='<div id=\"fSwapPanel\" style=\"display:none;padding:14px;border-top:1px solid var(--border);background:var(--surface2)\">'\n"
    "    +'<div id=\"fSwapLabel\" style=\"font-size:.82rem;color:var(--muted);margin-bottom:8px\"></div>'\n"
    "    +'<input id=\"fSwapSearch\" type=\"search\" placeholder=\"Type name to search riders…\" autocomplete=\"off\" style=\"width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:9px 12px;color:var(--text);font-size:.88rem;outline:none;margin-bottom:6px\" oninput=\"fSearchSwap(this.value)\" onfocus=\"fSearchSwap(this.value)\">'\n"
    "    +'<div id=\"fSwapResults\" style=\"max-height:200px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;display:none;background:var(--surface)\"></div>'\n"
    "    +'<button onclick=\"fCloseSwap()\" style=\"margin-top:8px;padding:7px 14px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--muted);font-size:.82rem;cursor:pointer\">Cancel</button>'\n"
    "  +'</div>';",
    '  const swapPanel=\'\';',
    'renderMySquad: remove swapPanel')

# Remove swap event listener in renderFantasy
html = patch(html,
    "  el.querySelectorAll('[data-swap]').forEach(el=>el.addEventListener('click',()=>fOpenSwap(el.dataset.swap)));",
    '',
    'renderFantasy: remove data-swap listener')

# ══════════════════════════════════════════════════════════════════════════════
# 10. fCreateTeam: no transfers in saved object
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    'fantasySave({name,owner,riders:[..._fPicked],transfers_used:0,transfers_total:MAX_TRANSFERS,created_at:new Date().toISOString(),pin_hash:_pinHash(pin)});',
    'fantasySave({name,owner,riders:[..._fPicked],created_at:new Date().toISOString(),pin_hash:_pinHash(pin)});',
    'fCreateTeam: no transfers in saved object')

# ══════════════════════════════════════════════════════════════════════════════
# 11. fDoImport: no transfers in imported object
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    '    const t={name:raw.name||\'Imported Team\',owner:raw.owner||\'\',riders:raw.riders,\n'
    '      transfers_used:raw.transfers_used||0,transfers_total:raw.transfers_total||5,\n'
    '      created_at:raw.created_at||new Date().toISOString()};',
    '    const t={name:raw.name||\'Imported Team\',owner:raw.owner||\'\',riders:raw.riders,\n'
    '      created_at:raw.created_at||new Date().toISOString()};',
    'fDoImport: no transfers in imported object')

# ══════════════════════════════════════════════════════════════════════════════
# 12. "My Squad" header → show race name
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    "  +'<div class=\"group-header\">👕 My Squad — '+esc(team.name)+'</div>'",
    "  +'<div class=\"group-header\">👕 '+esc(team.name)+(team._race?' — '+esc(team._race):\'\')+'</div>'",
    'renderMySquad: show race in header')

# ══════════════════════════════════════════════════════════════════════════════
# 13. fCreateTeam: embed race name in saved team object
# ══════════════════════════════════════════════════════════════════════════════
html = patch(html,
    'fantasySave({name,owner,riders:[..._fPicked],created_at:new Date().toISOString(),pin_hash:_pinHash(pin)});',
    '  const _crk=fantasyGetRace();\n'
    '  const _craces=[...(appData.live||[]),...(appData.upcoming||[]),...(appData.recent||[])].find(r=>_raceKey(r)===_crk);\n'
    '  fantasySave({name,owner,riders:[..._fPicked],_race:_craces?_craces.name:\'\',created_at:new Date().toISOString(),pin_hash:_pinHash(pin)});',
    'fCreateTeam: embed race name in team')

# ══════════════════════════════════════════════════════════════════════════════
# Verify critical strings present
# ══════════════════════════════════════════════════════════════════════════════
print('\nVerifying...')
checks = [
    ("APP_VERSION = 'v21'",       'APP_VERSION'),
    ('fantasyLoadAll',            'fantasyLoadAll'),
    ('fantasyGetRace',            'fantasyGetRace'),
    ('renderRaceSelector',        'renderRaceSelector'),
    ('fSwitchRace',               'fSwitchRace'),
    ('fantasyDelete',             'fantasyDelete'),
    ('</script>',                 'closing </script>'),
    ('</html>',                   'closing </html>'),
]
ok = True
for needle, label in checks:
    found = needle in html
    print(f'  {"OK" if found else "!!"} {label}')
    if not found: ok = False

if not ok:
    print('\nERROR: some checks failed — not writing file')
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
# Write index.html
# ══════════════════════════════════════════════════════════════════════════════
print()
safe_write(os.path.join(BASE, 'index.html'), html)

# ══════════════════════════════════════════════════════════════════════════════
# Patch sw.js
# ══════════════════════════════════════════════════════════════════════════════
r2 = subprocess.run(['git', 'show', 'HEAD:sw.js'], capture_output=True, cwd=BASE)
if r2.returncode == 0:
    sw = r2.stdout.decode('utf-8', errors='replace')
    sw = sw.replace("'uci-calendar-v20'", "'uci-calendar-v21'")
    safe_write(os.path.join(BASE, 'sw.js'), sw)
else:
    print('  !!  Could not read sw.js from git')

print('\nDone. Run: python pre_push_check.py')
