@echo off
title NL2SQL Production Check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Check-Production.ps1"
echo.
pause

