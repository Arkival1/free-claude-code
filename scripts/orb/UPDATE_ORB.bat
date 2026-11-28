@echo off
setlocal
title FCC + JARVIS Orb update
echo ============================================================
echo  FCC VOICE ORB UPDATE  (your JARVIS folder is not touched)
echo  Close the JARVIS Orb window and quit Free Claude Code in the
echo  system tray first. Do not run this as administrator.
echo ============================================================
echo.
echo STEP 1 of 2: Install or update FCC and the JARVIS Orb (no coding agents)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; & ([scriptblock]::Create((Invoke-RestMethod 'https://raw.githubusercontent.com/Arkival1/free-claude-code/refs/heads/claude/funny-ramanujan-w4p3v6/scripts/install.ps1'))) -OrbOnly -Source 'https://github.com/Arkival1/free-claude-code/archive/refs/heads/claude/funny-ramanujan-w4p3v6.zip'"
if errorlevel 1 goto :failed
echo.
echo STEP 2 of 2: JARVIS's voice and ears (downloads only what is missing)
set "ORB=%USERPROFILE%\.local\bin\fcc-orb.exe"
if not exist "%ORB%" for /f "delims=" %%i in ('where fcc-orb 2^>nul') do set "ORB=%%i"
if exist "%ORB%" (
    echo Please wait, this can take a few minutes the first time.
    start "" /wait "%ORB%" --prepare
    type "%USERPROFILE%\.fcc\orb_prepare.log" 2>nul
) else (
    echo Could not find fcc-orb. The orb will download them the first time it opens.
)
echo.
echo ALL DONE. Double-click "JARVIS Orb" on your desktop.
echo JARVIS also uses FCC by itself for video notes (download + transcribe on this PC).
goto :end
:failed
echo.
echo The update did not finish. If it says FCC is running, quit Free Claude Code
echo in the system tray (bottom right, near the clock) and run this file again.
:end
echo.
pause
