@echo off
setlocal
rem Portable mode: Fathom keeps your settings, history, saved tools and chats in a "FathomData" folder next to the app,
rem so they travel with this folder (for example on a USB stick). Big downloads (AI models) stay where they are.
rem The program parts still need Fathom set up on each computer (run Fathom.bat there once).
set "APP=%~dp0.."
for %%I in ("%APP%") do set "APP=%%~fI"
if exist "%APP%\portable.txt" (
  echo Portable mode is already on.
  pause
  exit /b 0
)
mkdir "%APP%\FathomData" >nul 2>&1
if exist "%LOCALAPPDATA%\Fathom" (
  echo Copying your current settings into the FathomData folder...
  robocopy "%LOCALAPPDATA%\Fathom" "%APP%\FathomData" /E /XD venv hf models tmp logs Ollama flows /XF *.log *.zip >nul
)
> "%APP%\portable.txt" echo Delete this file to turn portable mode off.
echo Done. Close Fathom if it is open, then start it again.
pause
