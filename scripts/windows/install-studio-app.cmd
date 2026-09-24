@echo off
rem Double-click once to install FCC Studio as a desktop app (Desktop and Start menu icon).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-studio-app.ps1" %*
if errorlevel 1 pause
if not errorlevel 1 timeout /t 8
