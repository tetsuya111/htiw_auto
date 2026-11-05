@echo off
setlocal

rem Move to the folder containing this bat (project root: .env and logs\ are resolved from here)
cd /d "%~dp0"

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Use .venv if it exists, otherwise python on PATH
set "PY=python"
if exist "%~dp0venv\Scripts\python.exe" set "PY=%~dp0venv\Scripts\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"

"%PY%" -m with_auto_reply %*

echo.
pause
endlocal
