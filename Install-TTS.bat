@echo off
REM Wayward - install optional voice / text-to-speech support (one-time).
REM Double-click to download and set up the voice engine (chatterbox-tts + torch)
REM and pre-fetch the voice model. This is a large, multi-GB download; the base
REM app (Run.bat) does NOT need it. Auto-detects an NVIDIA GPU for acceleration.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-TTS.ps1"
if errorlevel 1 (
  echo.
  echo Install failed - see the messages above.
  pause
)
