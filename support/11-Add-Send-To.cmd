@echo off
setlocal
rem Adds "Fathom" to the right-click menu: right-click any file or folder > Send to > Fathom puts it in Fathom's list.
set "APP=%~dp0.."
for %%I in ("%APP%") do set "APP=%%~fI"
set "PYW=%LOCALAPPDATA%\Fathom\venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo Fathom is not set up on this computer yet. Run Fathom.bat once, then run this again.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$q=[char]34; $ws=New-Object -ComObject WScript.Shell; $l=$ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('SendTo')) 'Fathom.lnk')); $l.TargetPath='%PYW%'; $l.Arguments=$q+'%APP%\launch.py'+$q; $l.WorkingDirectory='%APP%'; if (Test-Path '%APP%\assets\fathom.ico') { $l.IconLocation='%APP%\assets\fathom.ico' }; $l.Save()"
if errorlevel 1 (
  echo Could not add it. Nothing was changed.
  pause
  exit /b 1
)
echo Done. Right-click a file or folder, choose Send to, then Fathom.
echo (If you move the Fathom folder later, run this again.)
pause
