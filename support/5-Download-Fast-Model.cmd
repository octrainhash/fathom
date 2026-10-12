@echo off
rem Downloads the fast assistant model and times it.
rem This file only starts 5-Download-Fast-Model.ps1 (same folder). Open both in Notepad to read exactly what they do. Nothing is deleted.
set "H=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%5-Download-Fast-Model.ps1"
