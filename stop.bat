@echo off
setlocal

set FOUND=0
for /f "tokens=2 delims==; " %%P in ('wmic process where "name='python.exe' and commandline like '%%fund_dashboard%%server.py%%'" get ProcessId /value ^| find "ProcessId"') do (
  set FOUND=1
  taskkill /PID %%P /F >nul 2>nul
)

if "%FOUND%"=="1" (
  echo Fund dashboard stopped.
) else (
  echo Fund dashboard is not running.
)

endlocal
pause
