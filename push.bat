@echo off
cd /d "%~dp0"
echo === UCI Calendar - Git Push ===
echo.

:: Fix corrupted index if present
if exist ".git\index" (
    del /f ".git\index" 2>nul
)

:: Reset, add all changes, commit and push
git reset HEAD
git add -A
git status

echo.
set /p MSG="Commit message (or press Enter for 'chore: update'): "
if "%MSG%"=="" set MSG=chore: update

git commit -m "%MSG%"

:: Pull rebase in case remote is ahead, then push
git pull --rebase
git push

echo.
echo === Done! ===
pause
