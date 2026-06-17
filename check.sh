#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# check.sh  –  Health-check for UCI Calendar repo → writes error.log
# Usage:  bash check.sh
# ─────────────────────────────────────────────────────────────────────────────
REPO="$(cd "$(dirname "$0")" && pwd)"
LOG="$REPO/error.log"
ERRORS=0
WARNINGS=0

> "$LOG"   # clear previous log

ts() { date '+%H:%M:%S'; }

pass()  { echo "  ✅  $*" | tee -a "$LOG"; }
warn()  { echo "  ⚠️   $*" | tee -a "$LOG"; (( WARNINGS++ )) || true; }
fail()  { echo "  ❌  $*" | tee -a "$LOG"; (( ERRORS++ ))   || true; }
section(){ echo "" | tee -a "$LOG"; echo "── $* ──" | tee -a "$LOG"; }

echo "UCI Calendar Health Check  $(date '+%Y-%m-%d %H:%M:%S')" | tee "$LOG"
echo "Repo: $REPO" | tee -a "$LOG"
cd "$REPO"

# ── Git lock files ────────────────────────────────────────────────────────────
section "Git lock files"
LOCKS=(".git/index.lock" ".git/HEAD.lock" ".git/refs/heads/main.lock")
FOUND_LOCKS=0
for f in "${LOCKS[@]}"; do
  if [ -f "$f" ]; then
    fail "Stale lock file: $f  →  run: rm -f $f"
    FOUND_LOCKS=1
  fi
done
[ "$FOUND_LOCKS" -eq 0 ] && pass "No stale lock files"

# ── Git index integrity ───────────────────────────────────────────────────────
section "Git index"
if git status --short &>/dev/null; then
  pass "Git index is healthy"
else
  fail "Git index is corrupt — run: GIT_INDEX_FILE=/tmp/tmp_idx git read-tree HEAD && cp /tmp/tmp_idx .git/index"
fi

# ── Local vs remote ───────────────────────────────────────────────────────────
section "Local vs remote"
git fetch origin --quiet 2>>"$LOG" || warn "Could not fetch from remote (no network?)"
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "unknown")
AHEAD=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo "?")
BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null || echo "?")
echo "  Local HEAD:   $LOCAL" | tee -a "$LOG"
echo "  Remote HEAD:  $REMOTE" | tee -a "$LOG"
if [ "$LOCAL" = "$REMOTE" ]; then
  pass "In sync with origin/main"
elif [ "$AHEAD" != "0" ] && [ "$AHEAD" != "?" ]; then
  warn "$AHEAD commit(s) ahead of remote — run git-push.sh"
fi
if [ "$BEHIND" != "0" ] && [ "$BEHIND" != "?" ]; then
  warn "$BEHIND commit(s) behind remote — pull needed"
fi

# ── Uncommitted changes ───────────────────────────────────────────────────────
section "Working tree"
DIRTY=$(git status --porcelain 2>/dev/null | grep -v '^?' || true)
if [ -z "$DIRTY" ]; then
  pass "Working tree clean"
else
  warn "Uncommitted changes detected:"
  echo "$DIRTY" | while read -r line; do echo "    $line" | tee -a "$LOG"; done
fi

# ── index.html JS syntax ──────────────────────────────────────────────────────
section "index.html JS syntax"
if [ ! -f "index.html" ]; then
  fail "index.html not found"
elif command -v node &>/dev/null; then
  JS_ERR=$(node --check index.html 2>&1 || true)
  if echo "$JS_ERR" | grep -qi "SyntaxError\|error"; then
    fail "JS syntax error in index.html:"
    echo "$JS_ERR" | head -5 | tee -a "$LOG"
  else
    pass "index.html JS syntax OK"
  fi
  # Check file isn't truncated (must end with </html>)
  TAIL=$(tail -1 index.html | tr -d '\r\n ')
  if [ "$TAIL" = "</html>" ]; then
    pass "index.html ends correctly (</html>)"
  else
    fail "index.html appears truncated! Last line: '$TAIL'"
  fi
else
  warn "node not found — skipping JS syntax check"
fi

# ── data.json validity ────────────────────────────────────────────────────────
section "data.json"
if [ ! -f "data.json" ]; then
  fail "data.json not found"
else
  SIZE=$(wc -c < data.json)
  echo "  Size: $SIZE bytes" | tee -a "$LOG"
  if python3 -c "import json,sys; json.load(open('data.json'))" 2>>"$LOG"; then
    pass "data.json is valid JSON"
    # Quick stats
    python3 -c "
import json
d=json.load(open('data.json'))
live=len(d.get('live',[]))
up=len(d.get('upcoming',[]))
rec=len(d.get('recent',[]))
teams=len(d.get('teams',[]))
scraped=d.get('scraped_at_human','unknown')
print(f'  Live:{live}  Upcoming:{up}  Recent:{rec}  Teams:{teams}  Scraped:{scraped}')
" | tee -a "$LOG"
  else
    fail "data.json is invalid JSON (see above)"
  fi
fi

# ── Required files ────────────────────────────────────────────────────────────
section "Required files"
REQUIRED=("index.html" "data.json" "sw.js" "manifest.json" "scraper.py"
          ".github/workflows/update-data.yml")
for f in "${REQUIRED[@]}"; do
  if [ -f "$f" ]; then pass "$f"; else fail "Missing: $f"; fi
done

# ── App version ───────────────────────────────────────────────────────────────
section "App version"
if [ -f "index.html" ]; then
  VER=$(grep -o "APP_VERSION = '[^']*'" index.html | head -1)
  SW_VER=$(grep -o "CACHE_NAME = '[^']*'" sw.js 2>/dev/null | head -1)
  pass "index.html: $VER"
  pass "sw.js:      $SW_VER"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo "" | tee -a "$LOG"
echo "════════════════════════════════" | tee -a "$LOG"
if [ "$ERRORS" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
  echo "✅  All checks passed" | tee -a "$LOG"
elif [ "$ERRORS" -eq 0 ]; then
  echo "⚠️   $WARNINGS warning(s), 0 errors — repo is pushable" | tee -a "$LOG"
else
  echo "❌  $ERRORS error(s), $WARNINGS warning(s) — fix errors before pushing" | tee -a "$LOG"
fi
echo "Full log saved to: $LOG" | tee -a "$LOG"
