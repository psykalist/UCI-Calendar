@echo off
cd /d "C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results"
echo === Step 1: Rebuild cycling.db === >> fix_palmares_log.txt 2>&1
echo %date% %time% >> fix_palmares_log.txt 2>&1
python rebuild_cycling_db.py >> fix_palmares_log.txt 2>&1
echo. >> fix_palmares_log.txt 2>&1
echo === Step 2: Inject palmares into data.json === >> fix_palmares_log.txt 2>&1
python inject_palmares.py >> fix_palmares_log.txt 2>&1
echo. >> fix_palmares_log.txt 2>&1
echo === Step 3: Git commit + push === >> fix_palmares_log.txt 2>&1
git add cycling.db data.json import_to_db.py inject_palmares.py rebuild_cycling_db.py >> fix_palmares_log.txt 2>&1
git commit -m "data: init race_palmares table + palmares injection 2026-06-24" >> fix_palmares_log.txt 2>&1
git pull --rebase >> fix_palmares_log.txt 2>&1
git push >> fix_palmares_log.txt 2>&1
echo === Done === >> fix_palmares_log.txt 2>&1
echo %date% %time% >> fix_palmares_log.txt 2>&1
echo Done. Check fix_palmares_log.txt for details.
pause
