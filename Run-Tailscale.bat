@echo off
REM Wayward Alpha launcher (TAILSCALE) - double-click to run and expose the app
REM over your Tailscale tailnet, so you can connect from anywhere (not just the
REM local network). Requires Tailscale installed and signed in on this PC and on
REM the device you connect from. Same setup as Run.bat; the tailnet address to
REM open (IP + MagicDNS name) is printed once it's up.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run.ps1" -Tailscale
if errorlevel 1 (
  echo.
  echo Launch failed - see the messages above.
  pause
)
