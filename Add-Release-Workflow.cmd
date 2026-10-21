@echo off
cd /d "%~dp0"
if not exist ".github\workflows" mkdir ".github\workflows"
if exist "release.yml.txt" move /y "release.yml.txt" ".github\workflows\release.yml" >nul
if exist ".github\workflows\release.yml" (echo Done. Now open GitHub Desktop, commit and push.) else (echo Could not find release.yml.txt next to this file.)
del "%~f0" >/dev/null 2>&1
pause
