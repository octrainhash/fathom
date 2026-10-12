@echo off
rem Collects what is needed to understand an Ollama problem.
rem This file only starts 7-Diagnose-Ollama.ps1 (same folder). Open both in Notepad to read exactly what they do. Nothing is deleted.
set "H=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%7-Diagnose-Ollama.ps1"
