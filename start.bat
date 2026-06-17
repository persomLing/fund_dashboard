@echo off
setlocal
cd /d "%~dp0"

for /f "tokens=2 delims==; " %%P in ('wmic process where "name='python.exe' and commandline like '%%fund_dashboard%%server.py%%'" get ProcessId /value ^| find "ProcessId"') do (
  taskkill /PID %%P /F >nul 2>nul
)

start "Fund Dashboard" /min python "%~dp0server.py" 8787
timeout /t 1 >nul
start "" "http://127.0.0.1:8787/"
endlocal
