@echo off
rem Reads the state of Fathom and Ollama and asks the assistant a test question.
rem This file only starts 1-Check-Everything.ps1 (same folder). Open both in Notepad to read exactly what they do. Nothing is deleted.
set "H=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%1-Check-Everything.ps1"
