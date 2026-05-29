@echo off
REM Sound Effect Generator - development launch (Vite hot reload + DevTools)
cd /d "%~dp0frontend"
echo [dev] Starting in development mode (Vite + Electron + Python)...
call npm run dev
if errorlevel 1 pause