@echo off
echo ============================================
echo  UCI Calendar - Playwright Setup
echo  (one-time install for classification data)
echo ============================================
echo.
echo Installing Playwright Python package...
py -m pip install playwright
if %errorlevel% neq 0 (
    echo ERROR: pip install failed. Make sure Python is installed.
    pause
    goto :eof
)
echo.
echo Downloading Chromium browser (~300 MB, one-time only)...
py -m playwright install chromium
if %errorlevel% neq 0 (
    echo ERROR: Playwright browser install failed.
    pause
    goto :eof
)
echo.
echo ============================================
echo  Setup complete!
echo  Classification data (GC/Points/KOM/Youth)
echo  will now be scraped on next update.bat run.
echo ============================================
pause
