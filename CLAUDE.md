# CLAUDE.md — Project Instructions

> Read this file at the start of every session. Follow all rules here before making any changes.

---

## Project

UCI Calendar & Results — a single-file PWA (`index.html`) deployed on GitHub Pages.
- **Live URL:** https://psykalist.github.io/UCI-Calendar/
- **Project folder:** D:\Claude\Projects\UCI Calendar & Results
- **Bash mount path:** /sessions/gifted-keen-rubin/mnt/UCI Calendar & Results/
- See `ARCHITECTURE.md` for full system overview.

---

## Workflow Rules (MANDATORY)

### 1. Use Bash for git — do not ask the user to run git add/commit

After every change to `index.html` (or any project file), run from the sandbox:

```bash
cd "/sessions/gifted-keen-rubin/mnt/UCI Calendar & Results"
git add index.html          # add other changed files too if needed
git commit -m "vNN: description"
```

Then tell the user to run **one of these** — both handle HEAD.lock automatically:

```bash
# Option A — Git Bash (simple)
bash git-push.sh "vNN: description"

# Option B — manual
rm -f .git/HEAD.lock .git/index.lock
git push
```

Claude cannot run `git push` (no credentials in sandbox), but must run add + commit.

**HEAD.lock collisions:** heal.py runs every 5 min and can leave lock files.
The fix is already in heal.py (clears locks before git ops, 30s stale threshold).
If a commit still fails with HEAD.lock, tell the user to run `bash git-push.sh`.

### 2. Bump APP_VERSION on every change

Every bug fix, feature, or tweak must increment `APP_VERSION` in `index.html` before committing.

```js
const APP_VERSION = 'vNN';   // increment NN by 1 each time
```

Check current version first:
```bash
grep "APP_VERSION" "/sessions/gifted-keen-rubin/mnt/UCI Calendar & Results/index.html"
```

### 3. Read and respond to bash output

Always read the output of every bash command and react to errors or unexpected results before continuing.

### 4. Update these instructions when asked

If the user asks to update the workflow, rules, or project instructions, edit this CLAUDE.md file directly and commit it as part of the same version bump.

---

## Coding Rules

- `index.html` is a single-file PWA — all HTML, CSS, and JS lives in one file (~3400+ lines).
- The fantasy league uses `localStorage` only — no backend.
- Squad size: `maxSquad()` returns **8** for Grand Tours (≥21 stages), **7** for all other races.
- Budget: **100 credits** per team. `COST_FLOOR = 4`, `COST_CEIL = 22`.
- Points scoring: Stage wins (25pts), GC top-10, jersey holders (15pts each — not if also Yellow).
- `APP_VERSION` is displayed in the app header so the user can confirm which version is live.
- After editing `index.html`, verify JS brace balance:
  ```bash
  python3 -c "
  h=open(\"/sessions/gifted-keen-rubin/mnt/UCI Calendar & Results/index.html\").read()
  js=h[h.index('<script>'):h.rindex('</script>')]
  print('Brace diff:', js.count('{') - js.count('}'))
  "
  ```

---

## Key Constants (keep in sync between index.html and generate_best_teams.py)

| Constant | Value |
|----------|-------|
| `FANTASY_BUDGET` | 100 |
| `COST_FLOOR` | 4 |
| `COST_CEIL` | 22 |
| `STAGE_PTS` | 1st=25, 2nd=12, 3rd=8, 4th-10th=3 |
| `GC_PTS` | 1st=50, 2nd=30, 3rd=20, 4th-10th=8 |
| `JERSEY_PTS` | 15 (Points, KOM, Youth — not if rider also leads GC/Yellow) |
| `MAX_SQUAD_GT` | 8 (Grand Tours) |
| `MAX_SQUAD` | 7 (all other races) |

---

## I Claudius (AI Opponent)

- Stored per race in `localStorage` under key `iclaudius_teams`
- Generated from `best_teams.json` (built by `generate_best_teams.py`)
- Three tiers: Easy 🟢 / Pro 🟡 / Elite 🔴
- Appears in the league table with 🏛️ icon and purple AI badge
- Yellow exclusion applies: jersey bonuses don't stack with GC points

---

## Current Version

Check with:
```bash
grep "APP_VERSION" "/sessions/gifted-keen-rubin/mnt/UCI Calendar & Results/index.html"
```
