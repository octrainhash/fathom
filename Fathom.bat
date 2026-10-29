@echo off
setlocal EnableExtensions
title Fathom
cd /d "%~dp0"

set "APPDIR=%~dp0"
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"
set "DATA=%LOCALAPPDATA%\Fathom"
set "LOG=%DATA%\setup.log"
set "BATLOG=%DATA%\bat.log"
set "SELF=%~f0"
set "SELF_PS=%SELF:'=''%"
set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

if not exist "%DATA%" mkdir "%DATA%" >nul 2>&1

rem ---- Is this really the whole, extracted folder? (Double-clicking Fathom.bat inside the zip would otherwise start an OLD copy.)
if not exist "%APPDIR%\app\main.py" goto :not_extracted
if not exist "%APPDIR%\launch.py" goto :not_extracted

rem ---- Already set up? Then just start the app. (Type: Fathom.bat repair   to run the setup again.)
if /i "%~1"=="setup" goto :run_wizard
if /i "%~1"=="repair" goto :need_setup
rem  "Fathom.bat lite" = small install (no LibreOffice, Calibre, 7-Zip or local AI).  "Fathom.bat full" = add everything later.
if /i "%~1"=="lite" type nul > "%APPDIR%\LITE"
if /i "%~1"=="lite" goto :need_setup
if /i "%~1"=="full" if exist "%APPDIR%\LITE" del /f /q "%APPDIR%\LITE"
if /i "%~1"=="full" set "FATHOM_FULL=1"
if /i "%~1"=="full" goto :need_setup
rem ---- Already installed, but is it the newest version? If this folder is newer, run the setup once to UPDATE it (nothing is reinstalled that is already there).
set "WANT="
for /f "tokens=3" %%v in ('findstr /b /c:"VERSION" "%APPDIR%\app\paths.py" 2^>nul') do set "WANT=%%~v"
set "HAVE="
if exist "%DATA%\build.txt" set /p HAVE=<"%DATA%\build.txt"
if not defined WANT set "WANT=%HAVE%"
if exist "%DATA%\installed-2.ok" if exist "%DATA%\venv\Scripts\pythonw.exe" if /i "%HAVE%"=="%WANT%" goto :launch
goto :need_setup

:run_wizard
rem the installer wizard: choose what to install and where
if not exist "%APPDIR%\tools\wizard.ps1" goto :not_extracted
powershell -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%\tools\wizard.ps1"
exit /b 0

:need_setup
rem ---- Make sure the whole folder is here (a common problem: running the .bat from inside the zip without extracting it)
if not exist "%APPDIR%\setup_app.py" goto :not_extracted
if not exist "%APPDIR%\app\main.py" goto :not_extracted

rem ---- Windows checks (before asking for administrator permission)
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 goto :bad_arch
set "WINMAJOR=10"
for /f "tokens=2 delims=[]" %%v in ('ver') do for /f "tokens=2 delims=. " %%a in ("%%v") do set "WINMAJOR=%%a"
if %WINMAJOR% LSS 10 goto :bad_windows

rem ---- First run needs administrator rights (it installs Python and Windows components).
fltmc >nul 2>&1
if not errorlevel 1 goto :is_admin
echo Windows will now ask for administrator permission. Please click Yes.
if "%~1"=="" goto :elevate_plain
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%SELF_PS%' -ArgumentList '%~1' -Verb RunAs"
goto :elevate_done
:elevate_plain
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%SELF_PS%' -Verb RunAs"
:elevate_done
if errorlevel 1 goto :admin_failed
exit /b 0

:admin_failed
echo.
echo Could not get administrator permission.
echo Right-click Fathom.bat and choose Run as administrator.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1

:take_choice
set "K=%~1"
set "V=%~2"
if /i "%K%"=="DEST" set "FATHOM_DEST=%V%"
if /i "%K%"=="PROGRAMS" set "FATHOM_PROGRAMS=%V%"
if /i "%K%"=="SKIP" set "FATHOM_SKIP=%V%"
if /i "%K%"=="MOVEZIP" set "FATHOM_MOVEZIP=%V%"
if /i "%K%"=="APPDIR" set "FATHOM_APPDIR=%V%"
if /i "%K%"=="DATADIR" set "FATHOM_DATADIR=%V%"
if /i "%K%"=="DATA" set "FATHOM_DATA=%V%"
if /i "%K%"=="PROGBASE" set "FATHOM_PROGBASE=%V%"
if /i "%K%"=="DIRS" set "FATHOM_DIRS=%V%"
if /i "%K%"=="WIZARD" set "FATHOM_WIZARD=%V%"
if /i "%K%"=="EDITION" if /i "%V%"=="lite" set "FATHOM_SKIP=libreoffice,calibre,7zip,ollama"
exit /b 0

:not_extracted
echo.
echo Fathom cannot find its files next to Fathom.bat.
echo You probably opened Fathom.bat from inside the zip file.
echo Please right-click the zip, choose "Extract All...", and then run
echo Fathom.bat from the extracted folder.
echo.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1

:bad_arch
echo.
echo This is a 32-bit version of Windows. Fathom needs 64-bit Windows 10 or 11.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1

:bad_windows
echo.
echo This Windows is too old. Fathom needs Windows 10 or Windows 11.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1

:is_admin
echo ================================================================
echo   Fathom setup - first run only. Please keep this window open.
echo ================================================================
echo.
if not exist "%DATA%" mkdir "%DATA%"

rem ---- The installer (Fathom-Setup.vbs, or "Fathom.bat setup") saves YOUR choices in install-choice.txt: where to keep everything, what to install.
rem      Nothing is moved unless you chose a folder there. "Fathom.bat here" ignores it and installs right where this folder is.
set "FATHOM_DEST="
set "FATHOM_PROGRAMS="
set "FATHOM_SKIP="
set "FATHOM_MOVEZIP="
set "FATHOM_APPDIR="
set "FATHOM_DATADIR="
set "FATHOM_DATA="
set "FATHOM_PROGBASE="
set "FATHOM_DIRS="
set "FATHOM_WIZARD="
if exist "%DATA%\install-failed.txt" del /f /q "%DATA%\install-failed.txt" >nul 2>&1
if exist "%APPDIR%\install-choice.txt" for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%APPDIR%\install-choice.txt") do call :take_choice "%%a" "%%b"
if /i "%~1"=="here" set "FATHOM_DEST="
if /i "%~1"=="full" set "FATHOM_SKIP="
if not defined FATHOM_DEST goto :after_d
if not exist "%APPDIR%\Move-Fathom.cmd" goto :after_d
if not exist "%APPDIR%\tools\relocate.ps1" goto :after_d
echo Putting Fathom in %FATHOM_DEST% as you chose ...
echo.
call "%APPDIR%\Move-Fathom.cmd" auto
set "MVRC=%errorlevel%"
rem 0 = the app was copied to the chosen folder and is starting from there; this window is done
if "%MVRC%"=="0" exit /b 0
if "%MVRC%"=="10" goto :after_d
echo.
echo Moving to %FATHOM_DEST% did not finish. Details: %TEMP%\Fathom-move.log
echo Fix the problem and run Fathom.bat again, or run   Fathom.bat here   to install where this folder is instead.
if exist "%DATA%\move-reason.txt" (copy /y "%DATA%\move-reason.txt" "%DATA%\install-failed.txt" >nul) else (>"%DATA%\install-failed.txt" echo Moving to the chosen folders did not finish. See %TEMP%\Fathom-move.log)
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1
:after_d
rem installers download into temporary files: keep those in the chosen folder too
if not defined FATHOM_DEST goto :temp_done
if not exist "%DATA%\tmp" mkdir "%DATA%\tmp" >nul 2>&1
if exist "%DATA%\tmp" set "TEMP=%DATA%\tmp"
if exist "%DATA%\tmp" set "TMP=%DATA%\tmp"
:temp_done
echo %date% %time% setup started from %APPDIR% >> "%BATLOG%"
ver >> "%BATLOG%"

rem ---- Fathom needs exactly Python 3.12 (its OCR engine does not support newer versions yet)
set "PY="
call :find_python
if defined PY goto :have_python

echo Python 3.12 was not found. Installing it now - about 25 MB...
set "PYSETUP=%TEMP%\python-3.12.10-amd64.exe"
if exist "%PYSETUP%" del /f /q "%PYSETUP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%PYSETUP%'" >> "%BATLOG%" 2>&1
call :check_download
if "%DL_OK%"=="1" goto :run_python_setup
echo First download method failed. Trying another one...
if exist "%PYSETUP%" del /f /q "%PYSETUP%"
curl.exe -L --fail --silent --show-error -o "%PYSETUP%" "%PYURL%" >> "%BATLOG%" 2>&1
call :check_download
if "%DL_OK%"=="1" goto :run_python_setup
echo Direct download failed. Trying the Windows Package Manager instead...
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >> "%BATLOG%" 2>&1
goto :after_python_setup

:run_python_setup
start /wait "" "%PYSETUP%" /quiet InstallAllUsers=1 PrependPath=0 Include_launcher=1 InstallLauncherAllUsers=1 Include_pip=1 Include_tcltk=1 Include_test=0 Include_doc=0 Shortcuts=0
echo Python installer finished with code %errorlevel% >> "%BATLOG%"

:after_python_setup
set "PY="
call :find_python
if not defined PY goto :no_python

:have_python
echo Using Python: %PY%
echo Using Python: %PY% >> "%BATLOG%"
echo.
"%PY%" "%APPDIR%\setup_app.py"
if errorlevel 1 goto :failed
rem the setup just made the shortcuts for THIS folder
>"%DATA%\app-dir.txt" echo "%APPDIR%"
goto :launch

:launch
rem ---- "Fathom.bat serve [--https] [--port N]": run as a private web server so phones, tablets and other computers can use it
if /i "%~1"=="serve" goto :launch_serve
rem ---- The Fathom shortcut must point at THIS folder. If Fathom was moved, or a newer copy was extracted somewhere else,
rem      the saved shortcut still points at the old folder and would start the OLD version. So check, and make it again if needed.
set "LASTDIR="
if exist "%DATA%\app-dir.txt" set /p LASTDIR=<"%DATA%\app-dir.txt"
if not defined LASTDIR goto :remake_shortcuts
if /i %LASTDIR%=="%APPDIR%" goto :launch_go
:remake_shortcuts
if not exist "%DATA%\venv\Scripts\python.exe" goto :launch_go
echo Pointing the Fathom shortcuts at %APPDIR% ...
pushd "%APPDIR%"
"%DATA%\venv\Scripts\python.exe" -c "import setup_app; setup_app.make_shortcuts()" >> "%BATLOG%" 2>&1
set "MKRC=%errorlevel%"
popd
if "%MKRC%"=="0" >"%DATA%\app-dir.txt" echo "%APPDIR%"
:launch_go
rem ---- Start through Explorer so Fathom runs as a normal user (dragging files in from folders needs that).
set "LASTDIR="
if exist "%DATA%\app-dir.txt" set /p LASTDIR=<"%DATA%\app-dir.txt"
if not defined LASTDIR goto :launch_direct
if /i not %LASTDIR%=="%APPDIR%" goto :launch_direct
if exist "%DATA%\Fathom.lnk" goto :launch_shortcut
:launch_direct
start "" "%DATA%\venv\Scripts\pythonw.exe" "%APPDIR%\launch.py"
exit /b 0
:launch_shortcut
start "" explorer.exe "%DATA%\Fathom.lnk"
exit /b 0

:launch_serve
echo Starting Fathom in server mode. Keep this window open. Press Ctrl+C to stop.
"%DATA%\venv\Scripts\python.exe" "%APPDIR%\launch.py" --serve %2 %3 %4 %5 %6
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 0

:check_download
set "DL_OK=0"
set "SZ=0"
if exist "%PYSETUP%" for %%F in ("%PYSETUP%") do set "SZ=%%~zF"
if %SZ% GTR 10000000 set "DL_OK=1"
exit /b 0

:find_python
for /f "usebackq delims=" %%P in (`py -3.12 -c "import sys;print(sys.executable)" 2^>nul`) do set "PY=%%P"
if defined PY exit /b 0
if exist "%ProgramFiles%\Python312\python.exe" set "PY=%ProgramFiles%\Python312\python.exe"
if defined PY exit /b 0
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PY exit /b 0
rem updating an existing install: Fathom's own private Python is enough to run the setup
if exist "%DATA%\installed-2.ok" if exist "%DATA%\venv\Scripts\python.exe" set "PY=%DATA%\venv\Scripts\python.exe"
exit /b 0

:no_python
echo.
echo Could not install Python 3.12 automatically.
echo Please install it from https://www.python.org/downloads/release/python-31210/
echo (tick "Add python.exe to PATH" is not needed) and then run Fathom.bat again.
goto :failed

:failed
if not exist "%DATA%\installed-2.ok" goto :failed_fresh
if not exist "%DATA%\venv\Scripts\pythonw.exe" goto :failed_fresh
>"%DATA%\install-failed.txt" echo Setup did not finish. See setup.log and bat.log in %DATA%
echo.
echo The update did not finish (details in %LOG%).
echo Your installed Fathom still works, so it will start now.
if not "%FATHOM_WIZARD%"=="1" pause
goto :launch
:failed_fresh
echo.
echo Setup did not finish. The details are saved in:
echo   %LOG%
echo   %BATLOG%
echo Send me those two files or a photo of this window and I will fix it.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1
