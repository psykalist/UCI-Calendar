@echo off
echo [%date% %time%] Starting UCI Calendar update...

cd /d "C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results"

REM Run scraper (uses your home IP - not blocked by PCS)
python scraper.py
if %errorlevel% neq 0 (
    echo [WARNING] Scraper had errors - pushing whatever data was generated
)

REM Push data.json to GitHub (Netlify auto-deploys from there)
git add data.json
git diff --staged --quiet && (
    echo No new data to push.
) || (
    git commit -m "chore: update race data %date% %time%"
    git push origin main
    echo [%date% %time%] Data pushed - Netlify will redeploy automatically.
)

echo [%date% %time%] Done!
