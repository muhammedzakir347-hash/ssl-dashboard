@echo off
REM Wait up to 120 seconds for G: drive to mount (Google Drive can be slow after PC wakes).
set /a TRIES=0
:WAIT_DRIVE
if exist "G:\Shared drives\Demand Planning\ssl_dashboard\main.py" goto RUN
set /a TRIES=%TRIES%+1
if %TRIES% GEQ 24 (
    echo %DATE% %TIME% ERROR: G: drive not available after 120s. Aborting.
    exit /b 1
)
timeout /t 5 /nobreak >nul
goto WAIT_DRIVE

:RUN
cd /d "G:\Shared drives\Demand Planning\ssl_dashboard"
"C:\Users\mzaki\AppData\Local\Programs\Python\Python313\python.exe" main.py >> logs\scheduler.log 2>&1
