@echo off
setlocal

cd /d "%~dp0"

echo Run this on the machine that hosts the Vanna app (Oracle access).
echo Start the app first in another terminal: run.bat
echo Set APP_BASIC_AUTH_USER and APP_BASIC_AUTH_PASSWORD in .env for remote users.
echo.

ngrok http 8000

endlocal
