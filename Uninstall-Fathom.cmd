@echo off
setlocal EnableExtensions
title Uninstall Fathom
rem Removes Fathom (asks before each part). Keep this file next to Fathom.bat. Needs administrator rights.
fltmc >nul 2>&1
if not errorlevel 1 goto :admin_ok
echo Windows will ask for administrator permission. Please click Yes.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0
:admin_ok
if not exist "%~dp0tools\uninstall.ps1" goto :missing
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\uninstall.ps1" -AppDir "%~dp0."
echo.
pause
exit /b 0
:missing
echo Cannot find tools\uninstall.ps1 next to this file. Run it from the Fathom folder.
pause
exit /b 1
