@echo off
setlocal EnableExtensions
title Move Fathom
rem ======================================================================================
rem  Puts EVERYTHING in the folder YOU choose (for example on another drive), so nothing big stays on C: :
rem     the app folder                 ->  <folder>\Fathom
rem     its data (packages, models, chats, history)  ->  <folder>\Fathom Data
rem     Python 3.12, LibreOffice, Calibre, 7-Zip, Ollama and its AI model  ->  <folder>\Programs
rem  Windows keeps a tiny link at the old place, so every program still finds what it needs.
rem  The installer (Fathom-Setup.vbs) saves your folder choice and Fathom.bat runs this. You can also run it yourself (it asks for the folder). Safe to run twice.
rem  Nothing is deleted until the copy has been checked. Log: <folder>\Fathom-move.log
rem  Exit codes (used by Fathom.bat):  0 = moved and restarted from the new place,  10 = already there / nothing to do, carry on here,  1 = failed
rem  Settings come from Fathom.bat (install-choice.txt): FATHOM_DEST, FATHOM_PROGRAMS (dest|default), FATHOM_SKIP, FATHOM_MOVEZIP
rem ======================================================================================
set "AUTO=%~1"
set "DEST=%FATHOM_DEST%"
if defined DEST goto :dest_known
echo Where should Fathom (its app, data and programs) be kept? Type a folder, for example  D:\Softwares
set /p "DEST=Folder: "
if not defined DEST exit /b 1
:dest_known
set "DEST=%DEST:"=%"
if "%DEST:~-1%"=="\" set "DEST=%DEST:~0,-1%"
set "NEWAPP=%DEST%\Fathom"
set "NEWDATA=%DEST%\Fathom Data"
set "PROGBASE=%DEST%\Programs"
rem the installer wizard can name each folder exactly (install-choice.txt: APPDIR, DATADIR, PROGBASE); otherwise they are placed inside the one folder
if defined FATHOM_APPDIR set "NEWAPP=%FATHOM_APPDIR%"
if defined FATHOM_DATADIR set "NEWDATA=%FATHOM_DATADIR%"
if defined FATHOM_PROGBASE set "PROGBASE=%FATHOM_PROGBASE%"
set "SRC=%~dp0"
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"
set "OLDDATA=%LOCALAPPDATA%\Fathom"
set "LOG=%TEMP%\Fathom-move.log"
set "APP_ON_D="
if exist "%OLDDATA%\move-reason.txt" del /f /q "%OLDDATA%\move-reason.txt" >nul 2>&1

rem ---- administrator (Fathom.bat has it already; run on its own this file asks)
fltmc >nul 2>&1
if not errorlevel 1 goto :admin_ok
echo Windows will ask for administrator permission. Please click Yes.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0
:admin_ok

if not exist "%SRC%\Fathom.bat" goto :not_here
if not exist "%SRC%\app\main.py" goto :not_here
if not exist "%SRC%\tools\relocate.ps1" goto :not_here

if not exist "%DEST:~0,2%\" goto :no_d
if not exist "%DEST%" mkdir "%DEST%" >nul 2>&1
if not exist "%DEST%" goto :no_d
echo %date% %time% move started from %SRC% >> "%LOG%"

rem ---- is the app folder already inside the chosen folder? then it stays where it is
if defined FATHOM_APPDIR goto :app_exact
call set "REST=%%SRC:%DEST%\=%%"
if /i not "%REST%"=="%SRC%" set "APP_ON_D=1"
goto :app_cmp_done
:app_exact
if /i "%SRC%"=="%NEWAPP%" set "APP_ON_D=1"
:app_cmp_done
if defined APP_ON_D set "NEWAPP=%SRC%"

rem ---- 1. stop Fathom if it is running (otherwise files are locked)
echo [1/8] Closing Fathom if it is open...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and ($_.CommandLine -like '*launch.py*' -or $_.CommandLine -like '*app.main:app*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >> "%LOG%" 2>&1
timeout /t 3 /nobreak >nul

rem ---- 2. is there room in the chosen folder? (the big programs check themselves in step 6)
echo [2/8] Checking free space in %DEST:~0,2% ...
set "COUNTSRC=%SRC%"
if defined APP_ON_D set "COUNTSRC="
set "NEED_MB=0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$n=0; foreach($p in @($env:COUNTSRC, $env:OLDDATA)){ if($p -and (Test-Path -LiteralPath $p)){ $item=Get-Item -LiteralPath $p -Force; if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){continue}; $n += (Get-ChildItem -LiteralPath $p -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } }; $free=(Get-PSDrive -Name ($env:DEST.Substring(0,1))).Free; Write-Output ([int64]($n/1MB)); if($free -lt $n*1.05){ exit 3 }" > "%TEMP%\fathom_need.txt" 2>>"%LOG%"
set "RC=%errorlevel%"
set /p NEED_MB=<"%TEMP%\fathom_need.txt"
del /f /q "%TEMP%\fathom_need.txt" >nul 2>&1
if "%RC%"=="3" goto :no_room
echo     About %NEED_MB% MB to move. There is enough room.

rem ---- 3. the app folder
if defined APP_ON_D goto :app_stays
echo [3/8] Copying the app to %NEWAPP% ...
robocopy "%SRC%" "%NEWAPP%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XD __pycache__ /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1
if errorlevel 8 goto :copy_failed
if not exist "%NEWAPP%\Fathom.bat" goto :copy_failed
if not exist "%NEWAPP%\app\main.py" goto :copy_failed
goto :app_done
:app_stays
echo [3/8] The app is already in %DEST% (%SRC%). Leaving it there.
:app_done

rem ---- 4. the data folder (Python packages, models, results). Left behind as a link so nothing else has to change.
echo [4/8] Moving Fathom's data (Python packages, models, saved results) ...
if /i "%FATHOM_DATA%"=="default" goto :data_default
fsutil reparsepoint query "%OLDDATA%" >nul 2>&1
if not errorlevel 1 goto :data_already_link
goto :data_move

:data_default
echo     Fathom's data stays in %OLDDATA%.
set "NEWDATA=%OLDDATA%"
goto :data_done

:data_move
if not exist "%OLDDATA%" goto :data_none
robocopy "%OLDDATA%" "%NEWDATA%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1
if errorlevel 8 goto :copy_failed
if not exist "%NEWDATA%\venv\Scripts\python.exe" echo     (no Python environment found in the data; Fathom.bat will set it up again)
rem put the old folder aside, make the link, and only then trust it
move "%OLDDATA%" "%OLDDATA%.moved" >> "%LOG%" 2>&1
if exist "%OLDDATA%" goto :link_failed
mklink /J "%OLDDATA%" "%NEWDATA%" >> "%LOG%" 2>&1
if errorlevel 1 goto :link_failed_restore
type nul > "%NEWDATA%\.moved-ok"
if not exist "%OLDDATA%\.moved-ok" goto :link_failed_restore
del /f /q "%NEWDATA%\.moved-ok" >nul 2>&1
goto :data_done

:data_already_link
echo     Fathom's data is already a link; leaving it alone.
goto :data_done
:data_none
echo     No data folder yet (Fathom was never set up). Creating the link so it is set up in the chosen folder.
if not exist "%NEWDATA%" mkdir "%NEWDATA%"
mklink /J "%OLDDATA%" "%NEWDATA%" >> "%LOG%" 2>&1
:data_done

rem ---- 5. new shortcuts (Desktop, Start menu) that point to the new place
echo [5/8] Making the Fathom shortcuts point to the right place ...
if not exist "%OLDDATA%\venv\Scripts\python.exe" goto :no_shortcuts
pushd "%NEWAPP%"
"%OLDDATA%\venv\Scripts\python.exe" -c "import setup_app; setup_app.make_shortcuts()" >> "%LOG%" 2>&1
if not errorlevel 1 >"%OLDDATA%\app-dir.txt" echo "%NEWAPP%"
popd
goto :shortcuts_done
:no_shortcuts
echo     Fathom.bat will make the shortcuts the first time you run it.
:shortcuts_done

rem ---- 6. the big programs: Python, LibreOffice, Calibre, 7-Zip, Ollama and the AI model
echo [6/8] Moving Python, LibreOffice, Calibre, 7-Zip and Ollama (with its AI model) to %PROGBASE% (or the folders you chose) ...
echo     (the AI model is several GB, so this can take a while)
if /i "%FATHOM_PROGRAMS%"=="default" goto :programs_default
set "SKIPARG=%FATHOM_SKIP%"
if exist "%NEWAPP%\LITE" set "SKIPARG=libreoffice,calibre,7zip,ollama"
powershell -NoProfile -ExecutionPolicy Bypass -File "%NEWAPP%\tools\relocate.ps1" -Dest "%PROGBASE%" -Log "%LOG%" -Skip "%SKIPARG%"
set "PRC=%errorlevel%"
if not "%PRC%"=="0" echo     Some programs stayed where they were (see %LOG%). Everything still works.
goto :programs_done
:programs_default
echo     You chose to keep programs where Windows puts them. Nothing moved.
:programs_done

rem ---- 7. remove the old copies (only after everything above worked)
echo [7/8] Removing the old copies ...
if exist "%OLDDATA%.moved" rmdir /s /q "%OLDDATA%.moved" >> "%LOG%" 2>&1
if exist "%OLDDATA%.moved" echo     (some old data could not be removed; you can delete "%OLDDATA%.moved" yourself)

rem ---- 8. the downloaded zip(s): put them in the chosen folder and remove them from Downloads (only after the copy is checked)
echo [8/8] Tidying up the downloaded zip ...
if "%FATHOM_MOVEZIP%"=="1" for %%Z in ("%USERPROFILE%\Downloads\fathom*.zip") do call :movezip "%%~fZ"
if not "%FATHOM_MOVEZIP%"=="1" echo     (you chose to leave your downloads alone)
echo %date% %time% move finished OK >> "%LOG%"

echo.
echo ================================================================
echo   Done. Fathom now lives in the folders you chose :
echo      app        %NEWAPP%
echo      data       %NEWDATA%
echo      programs   %PROGBASE%
echo   The old place only keeps tiny links (a few KB) so Windows can find everything.
echo ================================================================
echo.

if defined APP_ON_D goto :finish_on_d

rem the folder this file is running from is deleted a few seconds after this window closes
echo %SRC%| findstr /i /b /c:"%DEST%" >nul
if not errorlevel 1 goto :skip_cleanup
> "%TEMP%\fathom_cleanup.cmd" echo @echo off
>> "%TEMP%\fathom_cleanup.cmd" echo ping -n 6 127.0.0.1 ^>nul
>> "%TEMP%\fathom_cleanup.cmd" echo rmdir /s /q "%SRC%"
>> "%TEMP%\fathom_cleanup.cmd" echo del /f /q "%%~f0"
start "" /min cmd /c "%TEMP%\fathom_cleanup.cmd"
:skip_cleanup
if "%FATHOM_WIZARD%"=="1" start "" "%NEWAPP%\Fathom.bat" repair
if not "%FATHOM_WIZARD%"=="1" start "" "%NEWAPP%\Fathom.bat"
if "%AUTO%"=="" timeout /t 6 /nobreak >nul
exit /b 0

:movezip
if not exist "%~1" exit /b 0
copy /Y "%~1" "%DEST%\%~nx1" >> "%LOG%" 2>&1
if errorlevel 1 exit /b 0
if /i "%~z1"=="" exit /b 0
for %%A in ("%DEST%\%~nx1") do if "%%~zA"=="%~z1" del /f /q "%~1" >nul 2>&1
if not exist "%~1" echo     Moved %~nx1 from Downloads to %DEST%
exit /b 0

:finish_on_d
if /i "%AUTO%"=="auto" exit /b 10
echo Run Fathom.bat from this folder to start Fathom.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 0

:not_here
>"%OLDDATA%\move-reason.txt" echo The wizard could not find the Fathom files (Fathom.bat, app, tools) next to the move script in %SRC%.
echo.
echo Put this file in the Fathom folder (next to Fathom.bat, with the app and tools folders) and run it again.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1

:no_d
>"%OLDDATA%\move-reason.txt" echo The drive or folder %DEST% does not exist or could not be created.
echo.
echo The drive for "%DEST%" does not exist or the folder could not be created. Nothing was changed.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1

:no_room
>"%OLDDATA%\move-reason.txt" echo Not enough free room in %DEST:~0,2% (needs about %NEED_MB% MB).
echo.
echo There is not enough free room in %DEST:~0,2% (needs about %NEED_MB% MB). Nothing was changed.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1

:copy_failed
>"%OLDDATA%\move-reason.txt" echo Copying the app or data to the chosen folder did not finish. See %LOG%.
echo.
echo The copy did not finish (see %LOG%). The original Fathom was NOT touched and still works.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1

:link_failed_restore
>"%OLDDATA%\move-reason.txt" echo Could not link the data folder, so everything was put back. See %LOG%.
echo.
echo Could not link the data folder. Putting everything back...
if exist "%OLDDATA%" rmdir "%OLDDATA%" >nul 2>&1
move "%OLDDATA%.moved" "%OLDDATA%" >> "%LOG%" 2>&1
:link_failed
>"%OLDDATA%\move-reason.txt" echo The data folder could not be moved. See %LOG%.
echo The data folder could not be moved (see %LOG%). The original Fathom still works from where it was.
if not "%FATHOM_WIZARD%"=="1" pause
exit /b 1
