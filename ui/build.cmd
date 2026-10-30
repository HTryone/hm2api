@echo off
rem Build the Vue + TS frontend (needs Node + pnpm).
setlocal
cd /d "%~dp0"
where pnpm >nul 2>&1
if errorlevel 1 (
  echo pnpm not found. Install Node.js, then: npm i -g pnpm
  exit /b 1
)
call pnpm install
if errorlevel 1 exit /b 1
call pnpm run build
if errorlevel 1 exit /b 1
echo Built into dist\. Commit ui/dist to ship it with the repo.
