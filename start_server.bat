@echo off
setlocal
cd /d "%~dp0"
if not defined POWER_PLAN_LOCAL_AUTH_BYPASS set "POWER_PLAN_LOCAL_AUTH_BYPASS=1"
set "PYTHON_EXE=%~dp0..\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%~dp0..\venv\bin\python"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
"%PYTHON_EXE%" server.py --host 127.0.0.1 --port 8866
