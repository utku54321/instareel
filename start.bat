@echo off
cd /d "%~dp0"
title Lyric Studio
if not exist ".venv\Scripts\python.exe" (
  echo Lyric Studio is not set up yet. Double-click install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" server.py
pause
