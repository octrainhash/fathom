@echo off
rem Fixes the Assistant saying the model was not found (asks for permission once).
rem This file only starts 2-Fix-Ollama.ps1 (same folder). Open both in Notepad to read exactly what they do. Nothing is deleted.
set "H=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%2-Fix-Ollama.ps1"
