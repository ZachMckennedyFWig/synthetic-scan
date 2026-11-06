@echo off
REM Double-click to start Scan Lab: builds the UI if needed, starts the server, opens the browser.
REM Closing the window that appears stops everything.
title Scan Lab
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
if errorlevel 1 pause
