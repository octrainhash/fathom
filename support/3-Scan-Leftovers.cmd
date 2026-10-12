@echo off
rem Lists every copy, link and leftover of Fathom (it only looks).
rem This file only starts 3-Scan-Leftovers.ps1 (same folder). Open both in Notepad to read exactly what they do. Nothing is deleted.
set "H=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%3-Scan-Leftovers.ps1"
