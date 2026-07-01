#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# git-push.sh  –  Safe push for UCI Calendar repo
# Usage:  bash git-push.sh [optional commit message]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
LOG="$REPO/push.log"
MSG="${1:-"chore: update $(date '+%Y-%m-%d %H:%M')"}"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

echo "" >> "$LOG"
log "━━━━ git-push.sh started ━━━━"
cd "$REPO"

# ── 1. Kill stale lock files ──────────────────────────────────────────────────
log "Checking for stale lock files…"
LOCKS=(
  ".git/index.lock"
  ".git/HEAD.lock"
  ".git/refs/heads/main.lock"
  ".git/refs/heads/master.lock"
  ".git/MERGE_HEAD"
  ".git/CHERRY_PICK_HEAD"
  ".git/REBASE_HEAD"
)
for f in "${LOCKS[@]}"; do
  if [ -f "$REPO/$f" ]; then
    rm -f "$REPO/$f" && log "  Removed $f" || log "  WARNING: could not remove $f — delete it manually"
  fi
done
if [ -d "$REPO/.git/rebase-merge" ] || [ -d "$REPO/.git/rebase-apply" ]; then
  log "  Removing stale rebase-merge/rebase-apply state…"
  rm -rf "$REPO/.git/rebase-merge" "$REPO/.git/rebase-apply" || log "  WARNING: could not remove stale rebase dir — delete it manually"
fi

# ── 2. Rebuild index if corrupt or stale relative to HEAD ─────────────────────
# (out-of-band commits — e.g. Claude's plumbing-commit workaround for locked
#  index/HEAD — move HEAD without touching the index, which leaves git status
#  showing confusing staged D/M entries that a plain `git add -u` would then
#  commit as real deletions. Detect that mismatch and resync the index first.)
INDEX_STALE=0
if ! git status --short &>/dev/null; then
  INDEX_STALE=1
elif ! git diff --quiet --cached HEAD -- 2>/dev/null; then
  INDEX_STALE=1
fi
if [ "$INDEX_STALE" -eq 1 ]; then
  log "Index appears corrupt or out of sync with HEAD — rebuilding…"
  GIT_INDEX_FILE=/tmp/uci_git_idx git read-tree HEAD
  cp /tmp/uci_git_idx .git/index
  log "  Index rebuilt from HEAD"
fi

# ── 3. Stash any uncommitted changes ─────────────────────────────────────────
DIRTY=$(git status --porcelain 2>/dev/null | grep -v '^?' || true)
if [ -n "$DIRTY" ]; then
  log "Stashing local changes…"
  git stash push -m "auto-stash $(date '+%Y-%m-%d %H:%M')" >> "$LOG" 2>&1
  STASHED=1
else
  log "Working tree clean — no stash needed"
  STASHED=0
fi

# ── 4. Pull latest from remote with rebase ───────────────────────────────────
log "Pulling origin/main (rebase)…"
if ! git pull origin main --rebase >> "$LOG" 2>&1; then
  log "  Rebase conflict detected — trying auto-resolve on data.json…"
  git checkout --theirs data.json 2>/dev/null && git add data.json || true
  # GIT_EDITOR=true: `rebase --continue` still wants to confirm the replayed
  # commit's message, which pops an interactive editor. Since stdout here is
  # redirected to $LOG, the editor's screen draws into the log file instead
  # of the terminal, so it just looks hung. `true` accepts the pre-filled
  # message with no prompt at all.
  if GIT_EDITOR=true git rebase --continue >> "$LOG" 2>&1; then
    log "  Rebase completed after auto-resolve"
  else
    log "  ERROR: Rebase still failing. Run 'git rebase --abort' and resolve manually."
    [ "$STASHED" -eq 1 ] && git stash pop || true
    exit 1
  fi
fi

# ── 5. Restore stash ─────────────────────────────────────────────────────────
if [ "$STASHED" -eq 1 ]; then
  log "Restoring stashed changes…"
  if ! git stash pop >> "$LOG" 2>&1; then
    log "  WARNING: stash pop had conflicts — check git status"
  fi
fi

# ── 6. Stage and commit ───────────────────────────────────────────────────────
CHANGED=$(git status --porcelain 2>/dev/null | grep