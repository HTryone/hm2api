@echo off
rem Sync the live model list into the DSH provider config (run as yourself, not sandboxed).
setlocal
cd /d "%~dp0"
set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV%" set "UV=uv"
"%UV%" run --locked --no-build src\scripts\sync-dsh-models.py --apply %*
echo.
pause
