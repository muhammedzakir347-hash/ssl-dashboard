@echo off
REM run_refresh.bat
REM Used by Windows Task Scheduler: runs the SSL pipeline at 8 AM and 8 PM.
REM Waits up to 15 minutes for the G: drive (Google Drive) to mount.

REM Local log — always writable even when G: isn't mounted yet
set LOCALLOG=C:\Users\mzaki\AppData\Local\Temp\ssl_dash_sched.log
echo %DATE% %TIME% Task started >> %LOCALLOG%

REM Set UTF-8 output so Unicode chars in Python logs don't crash the redirect
set PYTHONIOENCODING=utf-8

REM Wait up to 900 seconds (15 min) for G: drive to mount
set /a TRIES=0
:WAIT_DRIVE
if exist "G:\Shared drives\Demand Planning\ssl_dashboard\main.py" goto RUN
set /a TRIES=%TRIES%+1
echo %DATE% %TIME% Waiting for G: drive (attempt %TRIES%/180) >> %LOCALLOG%
if %TRIES% GEQ 180 (
    echo %DATE% %TIME% ERROR: G: drive not available after 900s. Aborting. >> %LOCALLOG%
    exit /b 1
)
timeout /t 5 /nobreak >nul
goto WAIT_DRIVE

:RUN
echo %DATE% %TIME% G: drive ready - starting main.py >> %LOCALLOG%
cd /d "G:\Shared drives\Demand Planning\ssl_dashboard"

"C:\Users\mzaki\AppData\Local\Programs\Python\Python313\python.exe" main.py >> logs\scheduler.log 2>&1
echo %DATE% %TIME% main.py finished (exit %ERRORLEVEL%) >> %LOCALLOG%

REM Get current month as YYYY-MM using Python (avoids locale date parsing issues)
for /f %%i in ('"C:\Users\mzaki\AppData\Local\Programs\Python\Python313\python.exe" -c "import datetime; print(datetime.date.today().strftime(\"%%Y-%%m\"))"') do set CURR_MONTH=%%i

REM Fetch current month GP data from Salesforce
echo %DATE% %TIME% Starting GP fetch for %CURR_MONTH% >> %LOCALLOG%
"C:\Users\mzaki\AppData\Local\Programs\Python\Python313\python.exe" fetch_gp_report.py --from %CURR_MONTH% --months 1 >> logs\scheduler.log 2>&1
echo %DATE% %TIME% GP fetch finished (exit %ERRORLEVEL%) >> %LOCALLOG%

REM Push updated GP month to BigQuery
echo %DATE% %TIME% Pushing GP to BQ >> %LOCALLOG%
"C:\Users\mzaki\AppData\Local\Programs\Python\Python313\python.exe" push_gp_month.py >> logs\scheduler.log 2>&1
echo %DATE% %TIME% GP BQ push finished (exit %ERRORLEVEL%) >> %LOCALLOG%

REM Fetch coupon/promo data for current month
echo %DATE% %TIME% Fetching coupon data for %CURR_MONTH% >> %LOCALLOG%
"C:\Users\mzaki\AppData\Local\Programs\Python\Python313\python.exe" fetch_coupon_data.py --from %CURR_MONTH% --months 1 >> logs\scheduler.log 2>&1
echo %DATE% %TIME% Coupon fetch finished (exit %ERRORLEVEL%) >> %LOCALLOG%
