@echo off
rem =====================================================================================================================
rem  Fathom: install everything, or update what is already there.
rem  Double-click it from anywhere (Downloads is fine). It finds your Fathom folder, downloads the newest Fathom, copies the
rem  new program files over it (your settings, chats and data are NOT touched, nothing is deleted) and then runs the Fathom
rem  setup, which only installs what is MISSING and skips what you already have (Python, LibreOffice, Calibre, 7-Zip, Ollama,
rem  the AI models).   Options:   Install-or-Update-Fathom.bat lite          small install (no LibreOffice, Calibre, local AI)
rem                               Install-or-Update-Fathom.bat "C:\MyFolder"  use this folder
rem  Open this file in Notepad to read every step. Log: %LOCALAPPDATA%\Fathom\install-update.log
rem =====================================================================================================================
setlocal EnableExtensions EnableDelayedExpansion
title Fathom - install or update

rem ---- run from a temporary copy, because the update replaces the files in the Fathom folder (this one included)
if not defined FATHOM_IOU_ORIG (
  set "FATHOM_IOU_ORIG=%~dp0"
  copy /y "%~f0" "%TEMP%\fathom-install-update.bat" >nul 2>&1
  if exist "%TEMP%\fathom-install-update.bat" (
    call "%TEMP%\fathom-install-update.bat" %*
    exit /b !errorlevel!
  )
)
set "ORIG=%FATHOM_IOU_ORIG%"
if not defined ORIG set "ORIG=%~dp0"

set "SITE=https://fathomfile.pages.dev/downloads"
set "MODE=full"
set "TARGET="
for %%a in (%*) do (
  if /i "%%~a"=="lite" (set "MODE=lite") else if /i "%%~a"=="full" (set "MODE=full") else if exist "%%~a\" set "TARGET=%%~fa"
)
set "ZIPNAME=fathom.zip"

set "DATA=%LOCALAPPDATA%\Fathom"
if not exist "%DATA%" mkdir "%DATA%" >nul 2>&1
set "LOG=%DATA%\install-update.log"
echo ===== %DATE% %TIME% (%MODE%) =====>>"%LOG%"

echo.
echo   Fathom - install or update
echo   --------------------------

rem ---- 1. Where is Fathom?
if defined TARGET goto :have_target
if exist "%ORIG%app\main.py" set "TARGET=%ORIG%"
if defined TARGET goto :have_target
for %%d in ("D:\Fathom" "C:\Fathom" "E:\Fathom" "%USERPROFILE%\Fathom" "%LOCALAPPDATA%\Programs\Fathom") do if not defined TARGET if exist "%%~d\app\main.py" set "TARGET=%%~d"
if defined TARGET goto :have_target
set "TARGET=%USERPROFILE%\Fathom"
echo   No Fathom was found on this computer, so this will be a new install.
set "ASK="
set /p "ASK=  Install into [%TARGET%]  - press Enter, or type another folder: "
if defined ASK set "TARGET=!ASK!"
set "TARGET=!TARGET:"=!"
:have_target
if "%TARGET:~-1%"=="\" set "TARGET=%TARGET:~0,-1%"
if exist "%TARGET%\app\main.py" (set "NOW=update") else (set "NOW=install")
echo   Folder: %TARGET%   (%NOW%)
echo Folder %TARGET% %NOW%>>"%LOG%"
set "OLDV=none"
if exist "%TARGET%\app\paths.py" for /f "tokens=3" %%v in ('findstr /b /c:"VERSION" "%TARGET%\app\paths.py" 2^>nul') do set "OLDV=%%~v"

rem ---- 2. Get the newest Fathom (download; if that fails, use a zip that is already on this computer)
set "WORK=%TEMP%\fathom-update-%RANDOM%"
mkdir "%WORK%" >nul 2>&1
set "ZIP=%WORK%\%ZIPNAME%"
set "URL=%SITE%/%ZIPNAME%"
echo.
echo   Downloading the newest Fathom (about 3 MB) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:URL -OutFile $env:ZIP } catch { exit 1 }" >>"%LOG%" 2>&1
set "SZ=0"
if exist "%ZIP%" for %%f in ("%ZIP%") do set "SZ=%%~zf"
if %SZ% GEQ 1000000 goto :got_zip
echo   Could not download it ^(no internet?^). Looking for a Fathom zip on this computer ...
del /f /q "%ZIP%" >nul 2>&1
set "FOUND="
for %%z in ("%ORIG%%ZIPNAME%" "%ORIG%fathom.zip" "%ORIG%fathom-final.zip" "%USERPROFILE%\Downloads\%ZIPNAME%" "%USERPROFILE%\Downloads\fathom.zip" "%USERPROFILE%\Downloads\fathom-final.zip") do if not defined FOUND if exist "%%~z" set "FOUND=%%~z"
if defined FOUND (
  echo   Using %FOUND%
  copy /y "%FOUND%" "%ZIP%" >nul
  goto :got_zip
)
if "%NOW%"=="update" (
  echo   No new zip. The setup will still run now, to finish anything that is missing.
  goto :run_setup
)
echo.
echo   There is nothing to install from: no internet and no Fathom zip in this folder or in Downloads.
echo   Download fathom.zip from https://fathomfile.pages.dev, put it next to this file and run this again.
goto :fail

:got_zip
echo   Unpacking ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory($env:ZIP, $env:WORK + '\x') } catch { Write-Output $_.Exception.Message; exit 1 }" >>"%LOG%" 2>&1
if errorlevel 1 (
  echo   The zip could not be opened. See %LOG%
  goto :fail
)
set "NEW="
if exist "%WORK%\x\app\main.py" set "NEW=%WORK%\x"
if not defined NEW for /d %%d in ("%WORK%\x\*") do if exist "%%~d\app\main.py" set "NEW=%%~d"
if not defined NEW (
  echo   That zip does not contain a Fathom folder.
  goto :fail
)
set "NEWV=?"
for /f "tokens=3" %%v in ('findstr /b /c:"VERSION" "%NEW%\app\paths.py" 2^>nul') do set "NEWV=%%~v"
echo   Installed version: %OLDV%    Newest version: %NEWV%

rem ---- 3. Close Fathom if it is running (so no file is locked), then copy the new program files over the folder
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*launch.py*' -or $_.CommandLine -like '*app.main:app*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 2 /nobreak >nul
if not exist "%TARGET%" mkdir "%TARGET%" >nul 2>&1
echo   Copying the new files (your settings and data are not touched) ...
robocopy "%NEW%" "%TARGET%" /E /XF install-choice.txt LITE /XD __pycache__ /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >>"%LOG%" 2>&1
if errorlevel 8 (
  echo   The copy did not finish. Is the folder read-only, or Fathom still open? See %LOG%
  goto :fail
)

rem ---- 4. Run the Fathom setup: installs only what is missing, updates what changed, then starts Fathom
:run_setup
if not exist "%TARGET%\Fathom.bat" (
  echo   Fathom.bat is missing in %TARGET%.
  goto :fail
)
echo.
echo   Now the Fathom setup runs. Windows will ask for permission: click Yes.
echo   What is already installed is skipped. A first install can take a while (it downloads the helpers).
echo.
rmdir /s /q "%WORK%" >nul 2>&1
start "" /d "%TARGET%" "%TARGET%\Fathom.bat" %MODE%
echo   Done here. You can close this window.
timeout /t 8 >nul
exit /b 0

:fail
echo Failed >>"%LOG%"
echo.
echo   Nothing was damaged. Details are in: %LOG%
pause
exit /b 1
