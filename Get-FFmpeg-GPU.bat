@echo off
title Get a full FFmpeg (for graphics-card encoding)
echo.
echo  Fathom's built-in FFmpeg has no NVIDIA graphics-card encoder.
echo  This installs a full FFmpeg once, with winget, so the option
echo  "Use the graphics card (NVIDIA)" in Convert can work.
echo  It needs Windows 10 or 11 with winget (App Installer), an internet
echo  connection and an NVIDIA graphics card. Nothing of yours is changed.
echo.
where winget >nul 2>&1
if errorlevel 1 (
  echo  winget was not found. Install "App Installer" from the Microsoft Store, then run this again.
  echo  Or install FFmpeg yourself and make sure "ffmpeg" works in a new Command Prompt.
  pause
  exit /b 1
)
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
  echo.
  echo  The install did not finish. If FFmpeg was already installed, that is fine.
  echo  Otherwise check your internet connection and try again.
  pause
  exit /b 1
)
echo.
echo  Done. Close Fathom and open it again, so it can find the new FFmpeg.
echo  To check: open a new Command Prompt and type   ffmpeg -encoders ^| findstr nvenc
pause
