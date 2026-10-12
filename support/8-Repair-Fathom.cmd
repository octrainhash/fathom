@echo off
rem Runs the Fathom setup again (after an update, or if something was missing). Windows asks for permission once.
set "H=%~dp0"
call "%H%..\Fathom.bat" repair
