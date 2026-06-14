@echo off
set LOG=C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results\update.log

if not exist "%LOG%" (
    echo No log file found. Run update.bat first.
    pause
    goto :eof
)

echo ============================================
echo  UCI Calendar - Last Update Log (last 60 lines)
echo ============================================
py -c "l=open(r'%LOG%',encoding='utf-8').readlines(); [print(x,end='') for x in l[-60:]]"
echo ============================================
pause
