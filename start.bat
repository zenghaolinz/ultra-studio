@echo off
chcp 65001 >nul
title Ultra Studio Launcher
setlocal enabledelayedexpansion

set PROJECT_DIR=%~dp0

echo ==========================================
echo   Ultra Studio - Agent + 3D Workstation
echo ==========================================
echo.

REM Check prerequisites
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found. Please install Node.js 18+
    pause
    exit /b 1
)

REM === Python Setup ===
set VENV_PATH=%PROJECT_DIR%sidecar\.venv
if not exist "%VENV_PATH%" (
    echo [SETUP] Creating Python virtual environment...
    python -m venv "%VENV_PATH%"
)

echo [INFO] Checking Python dependencies...
"%VENV_PATH%\Scripts\pip" install -r "%PROJECT_DIR%sidecar\requirements.txt" -q >nul 2>&1

REM === Node Setup ===
if not exist "%PROJECT_DIR%node_modules" (
    echo [SETUP] Installing npm dependencies...
    cd /d "%PROJECT_DIR%"
    call npm install
    if %errorlevel% neq 0 (
        echo [WARN] npm install failed, retrying with --legacy-peer-deps...
        call npm install --legacy-peer-deps
        if %errorlevel% neq 0 (
            echo [ERROR] npm install failed.
            pause
            exit /b 1
        )
    )
)

if not exist "%PROJECT_DIR%node_modules\.bin\tauri.cmd" (
    echo [ERROR] Tauri CLI not found.
    pause
    exit /b 1
)

REM === Start Backend ===
echo.
echo [INFO] Starting backend (Python Sidecar on :9257)...
start "Ultra-Studio-Backend" cmd /c ""%VENV_PATH%\Scripts\python.exe" "%PROJECT_DIR%sidecar\main.py""

echo [INFO] Waiting for backend...
set /a retry=0
:wait_loop
set /a retry+=1
if %retry% gtr 30 (
    echo [ERROR] Backend failed to start.
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:9257/api/config/persona >nul 2>&1
if %errorlevel% neq 0 goto wait_loop

echo [INFO] Backend is ready.

REM === Start Frontend ===
echo.
echo [INFO] Starting frontend (Tauri)...
echo [INFO] Close the Tauri window to stop all services.
echo.
cd /d "%PROJECT_DIR%"
call npx tauri dev

REM === Shutdown ===
echo.
echo [INFO] Shutting down services...

REM Method 1: Graceful stop via API
echo [INFO] Requesting ComfyUI graceful stop...
curl -s -X POST http://127.0.0.1:9257/api/comfyui/stop >nul 2>&1
timeout /t 3 /nobreak >nul

REM Method 2: Force kill by port 8188
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8188" ^| findstr "LISTENING"') do (
    echo [INFO] Force killing PID %%a on port 8188
    taskkill /F /T /PID %%a >nul 2>&1
)

REM Method 3: Clear VRAM
curl -s http://127.0.0.1:8188/memory/free >nul 2>&1

REM Stop sidecar
echo [INFO] Stopping sidecar...
taskkill /FI "WINDOWTITLE eq Ultra-Studio-Backend*" /F >nul 2>&1

echo [INFO] All services stopped.

endlocal
pause
