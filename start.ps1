# Ultra Studio Launcher (PowerShell)
$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Ultra Studio Launcher"

$ProjectDir = $PSScriptRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Ultra Studio - Agent + 3D Workstation" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found. Please install Python 3.10+" -ForegroundColor Red
    Pause; exit 1
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Node.js not found. Please install Node.js 18+" -ForegroundColor Red
    Pause; exit 1
}

function Shutdown-All {
    Write-Host ""
    Write-Host "[INFO] Shutting down services..." -ForegroundColor Yellow
    
    # Method 1: Call sidecar stop API (graceful)
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:9257/api/comfyui/stop" -Method Post -TimeoutSec 10 -UseBasicParsing
        Write-Host "[INFO] ComfyUI stop requested via API" -ForegroundColor Gray
        Start-Sleep -Seconds 3
    } catch {
        Write-Host "[WARN] Could not reach sidecar for graceful stop" -ForegroundColor Gray
    }

    # Method 2: Direct kill by port 8188
    $portPid = (netstat -ano 2>$null | Select-String ":8188" | Select-String "LISTENING" | ForEach-Object { 
        ($_ -split '\s+')[-1] 
    } | Select-Object -First 1)
    if ($portPid -and $portPid -ne "0") {
        Write-Host "[INFO] Force killing process on port 8188 (PID: $portPid)" -ForegroundColor Yellow
        taskkill /F /T /PID $portPid 2>$null | Out-Null
        Start-Sleep -Seconds 2
    }

    # Method 3: Clear ComfyUI VRAM
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:8188/memory/free" -TimeoutSec 5 -UseBasicParsing
    } catch {}

    # Kill sidecar
    if ($BackendProc -and !$BackendProc.HasExited) {
        Stop-Process -Id $BackendProc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "[INFO] Sidecar stopped" -ForegroundColor Gray
    }

    Write-Host "[INFO] Cleanup complete" -ForegroundColor Green
}

# === Python Setup ===
$VenvPath = Join-Path $ProjectDir "sidecar\.venv"
$SidecarConfig = Join-Path $ProjectDir "sidecar\config.ini"
$SidecarConfigExample = Join-Path $ProjectDir "sidecar\config.example.ini"

if (-not (Test-Path $SidecarConfig) -and (Test-Path $SidecarConfigExample)) {
    Copy-Item $SidecarConfigExample $SidecarConfig
    Write-Host "[SETUP] Created sidecar\config.ini from config.example.ini" -ForegroundColor Yellow
    Write-Host "[INFO] Edit sidecar\config.ini to set your ComfyUI path when using image/3D generation." -ForegroundColor Gray
}

if (-not (Test-Path $VenvPath)) {
    Write-Host "[SETUP] Creating Python virtual environment..." -ForegroundColor Yellow
    python -m venv $VenvPath
}

Write-Host "[INFO] Checking Python dependencies..." -ForegroundColor Gray
& "$VenvPath\Scripts\pip.exe" install -r (Join-Path $ProjectDir "sidecar\requirements.txt") -q 2>&1 | Out-Null

# === Node Setup ===
if (-not (Test-Path (Join-Path $ProjectDir "node_modules"))) {
    Write-Host "[SETUP] Installing npm dependencies..." -ForegroundColor Yellow
    Push-Location $ProjectDir
    try {
        npm install 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[WARN] Retrying with --legacy-peer-deps..." -ForegroundColor Yellow
            npm install --legacy-peer-deps 2>&1 | Out-Null
        }
    } finally {
        Pop-Location
    }
}

# Verify Tauri CLI
if (-not (Test-Path (Join-Path $ProjectDir "node_modules\.bin\tauri.cmd"))) {
    Write-Host "[ERROR] Tauri CLI not found. npm install may have failed." -ForegroundColor Red
    Write-Host "Run 'npm install' manually and check errors." -ForegroundColor Yellow
    Pause; exit 1
}

# === Start Backend ===
Write-Host ""
Write-Host "[INFO] Starting backend (Python Sidecar on :9257)..." -ForegroundColor Green
$BackendProc = Start-Process `
    -FilePath "$VenvPath\Scripts\python.exe" `
    -ArgumentList (Join-Path $ProjectDir "sidecar\main.py") `
    -WindowStyle Minimized `
    -PassThru

Write-Host "[INFO] Waiting for backend..." -ForegroundColor Yellow
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:9257/api/config/persona" -TimeoutSec 2 -UseBasicParsing | Out-Null
        Write-Host "[INFO] Backend is ready." -ForegroundColor Green
        break
    } catch {
        if ($i -eq 29) {
            Write-Host "[ERROR] Backend failed to start. Check sidecar output." -ForegroundColor Red
            Stop-Process -Id $BackendProc.Id -ErrorAction SilentlyContinue
            Pause; exit 1
        }
        Start-Sleep -Seconds 2
    }
}

# === Start Frontend ===
Write-Host ""
Write-Host "[INFO] Starting frontend (Tauri)..." -ForegroundColor Green
Push-Location $ProjectDir
try {
    npx tauri dev
} finally {
    Pop-Location
    Shutdown-All
}

Pause
