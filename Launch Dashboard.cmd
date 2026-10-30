@echo off
powershell.exe -NoProfile -File "%~dp0Start-Dashboard.ps1"
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8766"
