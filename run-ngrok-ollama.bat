@echo off
setlocal

cd /d "%~dp0"

REM Run this on the machine that hosts Ollama (GPU box).
REM Set credentials here or in environment before running.
if not defined OLLAMA_TUNNEL_USER set "OLLAMA_TUNNEL_USER=ollama"
if not defined OLLAMA_TUNNEL_PASSWORD set "OLLAMA_TUNNEL_PASSWORD=change-me"

echo Tunneling Ollama http://127.0.0.1:11434
echo ngrok basic-auth user: %OLLAMA_TUNNEL_USER%
echo.
echo On the Vanna app machine, set in .env:
echo   OLLAMA_HOST=https://YOUR-NGROK-URL
echo   OLLAMA_BASIC_AUTH_USER=%OLLAMA_TUNNEL_USER%
echo   OLLAMA_BASIC_AUTH_PASSWORD=^<same password^>
echo.

ngrok http 11434 --basic-auth="%OLLAMA_TUNNEL_USER%:%OLLAMA_TUNNEL_PASSWORD%"

endlocal
