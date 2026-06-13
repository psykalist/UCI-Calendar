@echo off
echo [%date% %time%] Starting UCI Calendar update...

cd /d "C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results"

REM Run scraper (uses your home IP - not blocked by PCS)
py scraper.py 2>nul || python3 scraper.py 2>nul || python scraper.py
if %errorlevel% neq 0 (
    echo [WARNING] Scraper had errors - pushing whatever data was generated
)

REM Clean up stale git lock files if they exist
if exist .git\index.lock del /f .git\index.lock
if exist .git\HEAD.lock del /f .git\HEAD.lock

REM Push all app files to GitHub (GitHub Pages auto-deploys from there)
git add data.json index.html scraper.py sw.js manifest.json update.bat
git diff --staged --quiet && (
    echo No new data to push.
) || (
    git commit -m "chore: update race data %date% %time%"
    git push origin main
    echo [%date% %time%] Data pushed - GitHub Pages will update shortly.
)

echo [%date% %time%] Done!
