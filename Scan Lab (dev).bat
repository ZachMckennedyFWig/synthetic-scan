@echo off
REM Scan Lab with UI hot reload (Vite on :5173, API on :8849).
title Scan Lab (dev)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Dev %*
if errorlevel 1 pause
