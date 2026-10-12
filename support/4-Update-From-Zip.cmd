@echo off
rem Updates this Fathom from a newer zip in Downloads.
rem This file only starts 4-Update-From-Zip.ps1 (same folder). Open both in Notepad to read exactly what they do. Nothing is deleted.
set "H=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%4-Update-From-Zip.ps1"
