@echo off
setlocal
rem Turns portable mode off. Fathom goes back to keeping its data in the Windows user folder. The FathomData folder is left alone.
set "APP=%~dp0.."
for %%I in ("%APP%") do set "APP=%%~fI"
if exist "%APP%\portable.txt" del /f /q "%APP%\portable.txt"
echo Portable mode is off. Close Fathom if it is open, then start it again.
pause
