@echo off
rem Double-click to start FCC Studio. Keeps the window open so you can read errors.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-studio.ps1" %*
if errorlevel 1 pause
