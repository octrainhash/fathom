@echo off
rem Fixes the free AI assistant when it says "model not found". Windows asks for permission once.
rem This file only starts support\2-Fix-Ollama.ps1 (open both in Notepad to read what they do). No model or file of yours is deleted.
set "H=%~dp0"
if not exist "%H%support\2-Fix-Ollama.ps1" (
  echo Cannot find support\2-Fix-Ollama.ps1 next to this file. Run it from the Fathom folder.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%H%support\2-Fix-Ollama.ps1"
