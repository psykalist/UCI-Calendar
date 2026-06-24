@echo off
cd /d "C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results"
echo === Rebuilding cycling.db + data.js from latest scrapes === > rebuild_datajs_log.txt 2>&1
echo %date% %time% >> rebuild_datajs_log.txt 2>&1
python import_to_db.py >> rebuild_datajs_log.txt 2>&1
echo. >> rebuild_datajs_log.txt 2>&1
echo === Git commit + push === >> rebuild_datajs_log.txt 2>&1
git add data.js cycling.db data.json rider_profiles.json >> rebuild_datajs_log.txt 2>&1
git commit -m "data: rebuild data.js + cycling.db from latest scrapes 2026-06-24" >> rebuild_datajs_log.txt 2>&1
git pull --rebase origin main >> rebuild_datajs_log.txt 2>&1
git push origin main >> rebuild_datajs_log.txt 2>&1
echo === Done === >> rebuild_datajs_log.txt 2>&1
echo %date% %time% >> rebuild_datajs_log.txt 2>&1
echo Done. Check rebuild_datajs_log.txt for details.
pause
