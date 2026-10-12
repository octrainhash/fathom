@echo off
rem Times the assistant with Fathom's real instructions.
rem This file only starts 6-Speed-Test.ps1 (same folder). Open both in Notepad to read exactly what they do. Nothing is deleted.
set "H=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%6-Speed-Test.ps1"
