@echo off
setlocal

set LOG=C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results\update.log
set STATUS=OK
set ERRORS=0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results"

call :log "========================================"
call :log "UPDATE STARTED"

REM Run scraper (results-only: skips static calendar/team data, only fetches new stage results)
call :log "Running scraper (results-only)..."
py scraper.py --results-only >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    python3 scraper.py --results-only >> "%LOG%" 2>&1
    if %errorlevel% neq 0 (
        python scraper.py --results-only >> "%LOG%" 2>&1
        if %errorlevel% neq 0 (
            call :log "ERROR: Scraper failed to run"
            set STATUS=SCRAPER_FAILED
            set /a ERRORS+=1
        )
    )
)

REM Validate data.json
if exist data.json (
    py -c "import json; json.load(open('data.json',encoding='utf-8')); print('data.json OK')" >> "%LOG%" 2>&1
    if %errorlevel% neq 0 (
        call :log "ERROR: data.json is invalid JSON - not pushing"
        set STATUS=INVALID_JSON
        set /a ERRORS+=1
        goto :done
    )
) else (
    call :log "ERROR: data.json not found"
    set STATUS=NO_DATA_FILE
    set /a ERRORS+=1
    goto :done
)

REM Clean git locks
if exist .git\index.lock del /f .git\index.lock
if exist .git\HEAD.lock del /f .git\HEAD.lock

REM Push to GitHub
call :log "Pushing to GitHub..."
git add data.json index.html scraper.py sw.js manifest.json update.bat setup_playwright.bat >> "%LOG%" 2>&1
git diff --staged --quiet
if %errorlevel% equ 0 (
    call :log "No new data to push (nothing changed)"
    goto :done
)
git commit -m "chore: update race data %date% %time%" >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    call :log "ERROR: git commit failed"
    set STATUS=GIT_COMMIT_FAILED
    set /a ERRORS+=1
    goto :done
)
git push origin main >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    call :log "ERROR: git push failed"
    set STATUS=GIT_PUSH_FAILED
    set /a ERRORS+=1
    goto :done
)
call :log "Pushed OK - GitHub Pages updating"

:done
if %ERRORS% equ 0 (
    call :log "UPDATE COMPLETE - Status: %STATUS%"
) else (
    call :log "UPDATE FINISHED WITH ERRORS - Status: %STATUS%"
)
call :log "========================================"

REM Trim log to last 500 lines (no > character in Python expression)
py -c "f='update.log'; l=open(f,encoding='utf-8').readlines(); open(f,'w',encoding='utf-8').writelines(l[max(0,len(l)-500):])" 2>nul

REM Print summary
echo.
if %ERRORS% equ 0 (
    echo [OK] Update complete. No errors.
) else (
    echo [!!] Update finished with errors. Check update.log
)
echo Last log lines:
py -c "l=open('update.log',encoding='utf-8').readlines(); [print(x,end='') for x in l[-8:]]" 2>nul
endlocal
goto :eof

:log
echo [%date% %time%] %~1
echo [%date% %time%] %~1 >> "%LOG%"
goto :eof
