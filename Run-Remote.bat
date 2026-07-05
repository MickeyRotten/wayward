@echo off
REM Wayward Alpha launcher (REMOTE) - double-click to run and expose the app
REM to other devices on your local network. Same setup as Run.bat, but the
REM frontend also binds to 0.0.0.0 so you can connect from a phone/tablet/PC
REM at http://<this-pc-ip>:5173 (the address is printed once it's up).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run.ps1" -Remote
if errorlevel 1 (
  echo.
  echo Launch failed - see the messages above.
  pause
)
