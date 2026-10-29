@echo off
rem  Fathom: update everything on THIS PC and download every model now (all speech models, object search, faces,
rem  handwriting, Ollama model), so nothing has to download later. Put it in your Fathom folder and double-click it.
rem  Safe to run again any time; it only fetches what is missing. Log: %LOCALAPPDATA%\Fathom\setup.log
setlocal
title Fathom - update and download everything
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Fathom\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Fathom has not been installed on this PC yet. Run Fathom.bat once first, then run this again.
  pause & exit /b 1
)
set "FATHOM_WHISPER=all"
set "PYTHONUTF8=1"
echo Updating packages and downloading every model. This can take a long time the first run (several GB).
"%PY%" setup_app.py
echo.
if errorlevel 1 (echo Something did not finish - see the lines above, then run this again.) else (echo Done. Everything is installed and downloaded.)
pause
