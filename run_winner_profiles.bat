@echo off
cd /d "C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results"
echo === Step 1: Scraping winner profiles === >> run_log.txt 2>&1
echo %date% %time% >> run_log.txt 2>&1
python scrape_rider_profiles.py --update-winners >> run_log.txt 2>&1
echo. >> run_log.txt 2>&1
echo === Step 2: Injecting palmares === >> run_log.txt 2>&1
python inject_palmares.py >> run_log.txt 2>&1
echo. >> run_log.txt 2>&1
echo === Step 3: Git add/commit/push === >> run_log.txt 2>&1
git add rider_profiles.json data.json >> run_log.txt 2>&1
git commit -m "data: winner profiles + palmares 2026-06-24" >> run_log.txt 2>&1
git pull --rebase >> run_log.txt 2>&1
git push >> run_log.txt 2>&1
echo === Done === >> run_log.txt 2>&1
echo %date% %time% >> run_log.txt 2>&1
echo Done. Check run_log.txt for details.
pause
