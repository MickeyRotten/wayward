@echo off
REM Wayward Alpha launcher - double-click to set up and run the app.
REM Installs Node (portable) + Python/npm deps if missing, starts both
REM servers, and opens the browser at http://localhost:5173.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run.ps1"
if errorlevel 1 (
  echo.
  echo Launch failed - see the messages above.
  pause
)
