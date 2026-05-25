@echo off
setlocal

cd /d "%~dp0"

REM Avoid mixing with another project's activated venv (e.g. nl-2-sql-vanna-oracle)
if defined VIRTUAL_ENV (
    echo %VIRTUAL_ENV% | findstr /I /C:"%~dp0.venv" >nul
    if errorlevel 1 set VIRTUAL_ENV=
)
set PYTHONPATH=

uv run python -m uvicorn nl_2_sql_vanna_oracle_pc.asgi:app ^
  --host 0.0.0.0 ^
  --port 8000 ^
  --reload ^
  --reload-dir src ^
  --reload-include .env

endlocal
