@echo off
cd /d "C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results"

echo Pushing display fixes to GitHub...

if exist .git\index.lock del /f .git\index.lock
if exist .git\HEAD.lock del /f .git\HEAD.lock

git add sw.js index.html scraper.py update.bat setup_playwright.bat check.bat
git diff --staged --quiet
if %errorlevel% equ 0 (
    echo No changes to push - already up to date.
    goto :done
)
git commit -m "fix: bigger text, jersey cards always clickable, team jerseys, SW cache v3"
git push origin main
if %errorlevel% equ 0 (
    echo.
    echo [OK] Pushed! App will update in ~1 minute.
    echo      Open the app and wait - it will auto-refresh with bigger text,
    echo      clickable jersey cards, and team jersey images.
) else (
    echo.
    echo [!!] Push failed. Try: git pull --rebase origin main then re-run this.
)

:done
pause
