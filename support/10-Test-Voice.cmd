@echo off
rem Tests the computer's own voice outside Fathom, to find out why the assistant cannot be heard.
rem This file only starts 10-Test-Voice.ps1 (same folder). Open both in Notepad to read exactly what they do. Nothing is deleted.
set "H=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%10-Test-Voice.ps1"
