@echo off
REM Double-click this to update Namma Agent on Windows.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" -Relaunch
echo.
pause
