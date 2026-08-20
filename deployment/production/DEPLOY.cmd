@echo off
title NL2SQL Production Deployment
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Deploy-Production.ps1"
set EXIT_CODE=%ERRORLEVEL%
echo.
if "%EXIT_CODE%"=="2" echo Configuration was created. Ask the technical owner to check .env, then run DEPLOY.cmd again.
if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="2" echo Deployment did not finish successfully. Please send this screen to technical support.
pause
exit /b %EXIT_CODE%
