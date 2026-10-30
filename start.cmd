@echo off
rem Hm2api gateway - one-click start (ASCII only, CRLF).
rem Usage: double-click this file, or run with --check to only report status.
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PORT=8788"
set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV%" set "UV=uv"

rem --- 1. prepare folders / .env ---
if not exist "logs" mkdir "logs" >nul 2>&1
if not exist "data" mkdir "data" >nul 2>&1
if not exist "cred\loomy" mkdir "cred\loomy" >nul 2>&1
if not exist "cred\qwenwork" mkdir "cred\qwenwork" >nul 2>&1
if not exist ".env" if exist ".env.example" copy /y ".env.example" ".env" >nul 2>&1

rem --- 1.5 build frontend when the compiled assets are missing ---
if not exist "ui\dist\index.html" (
  where pnpm >nul 2>&1
  if errorlevel 1 (
    echo [warn] ui\dist missing and pnpm not found: dashboard will be unavailable, API still works.
    echo        Install Node.js + pnpm, then run ui\build.cmd
  ) else (
    echo Building frontend for the first time ...
    pushd "ui" && call pnpm install && call pnpm run build & popd
  )
)

rem --- 2. status check only ---
netstat -ano | findstr ":%PORT%" | findstr LISTENING >nul 2>&1
if not errorlevel 1 (
  if /i "%~1"=="--check" (
    echo RUNNING
    exit /b 0
  )
  echo Gateway already running on port %PORT%, opening dashboard...
  start "" "http://127.0.0.1:%PORT%/dashboard/"
  exit /b 0
)
if /i "%~1"=="--check" (
  echo STOPPED
  exit /b 0
)

rem --- 3. make sure uv exists (auto install, no commands needed) ---
where uv >nul 2>&1
if errorlevel 1 if not exist "%UV%" (
  echo uv not found, installing uv ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" >>"logs\setup.log" 2>&1
  if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
)
if not exist "%UV%" (
  where uv >nul 2>&1
  if errorlevel 1 (
    echo Failed to install uv. See logs\setup.log
    pause
    exit /b 1
  )
  set "UV=uv"
)

rem --- 4. start gateway ---
set "PYTHONUNBUFFERED=1"
set "NO_PROXY=localhost,127.0.0.1,.cn,xunfei.cn,loomyad.xunfei.cn,qwenwork.cn,gateway.qwenwork.cn,api9.qwenwork.cn"
echo Starting Hm2api gateway on http://127.0.0.1:%PORT% ...
echo First run installs Python dependencies, please wait...
start "" "http://127.0.0.1:%PORT%/dashboard/"
"%UV%" run --locked --no-build --env-file .env src\converter.py 1>>"logs\gateway.out.log" 2>>"logs\gateway.err.log"
