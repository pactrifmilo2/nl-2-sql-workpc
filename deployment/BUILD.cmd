@echo off
title Build NL2SQL Production Release
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-Release.ps1"
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" echo Release build failed. Review the error above.
pause
exit /b %EXIT_CODE%

