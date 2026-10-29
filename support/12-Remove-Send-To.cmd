@echo off
setlocal
rem Takes Fathom out of the right-click "Send to" menu. Nothing else is touched.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$f=Join-Path ([Environment]::GetFolderPath('SendTo')) 'Fathom.lnk'; if (Test-Path $f) { Remove-Item $f; 'Removed.' } else { 'It was not there.' }"
pause
