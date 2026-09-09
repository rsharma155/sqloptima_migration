@echo off
REM Double-click this file after installing Docker Desktop.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sql-optima.ps1" %*
if errorlevel 1 pause
