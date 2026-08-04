# ============================================================
#  MUSASHI Super Sigma CMII - Windows PowerShell Launcher
#  Usage:
#    .\run_musashi.ps1                    # Interactive menu
#    .\run_musashi.ps1 -Mode mock         # Direct mock mode
#    .\run_musashi.ps1 -Mode real -Port COM4 -Once
# ============================================================

param(
    [ValidateSet("real", "mock", "")]
    [string]$Mode = "",

    [string]$Port = "",
    [string]$Config = "",
    [switch]$Once,
    [switch]$ListPorts
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "MUSASHI Telemetry Service"

# --- Helper: List available COM ports ---
function Get-SerialPorts {
    try {
        $ports = [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object
        return $ports
    } catch {
        return @()
    }
}

# --- Show available COM ports ---
if ($ListPorts) {
    $ports = Get-SerialPorts
    if ($ports.Count -gt 0) {
        Write-Host "`nAvailable COM Ports:" -ForegroundColor Cyan
        foreach ($p in $ports) {
            Write-Host "  - $p" -ForegroundColor Green
        }
    } else {
        Write-Host "`nNo COM ports detected." -ForegroundColor Yellow
    }
    exit 0
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MUSASHI Super Sigma CMII Telemetry Service - Windows" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# --- Set working directory ---
Set-Location $PSScriptRoot

# --- Activate venv ---
$venvActivate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    & $venvActivate
    Write-Host "[OK] Virtual environment activated." -ForegroundColor Green
} else {
    Write-Host "[WARN] No .venv found. Using system Python." -ForegroundColor Yellow
    Write-Host "       Run install_windows.bat first to set up the environment." -ForegroundColor Yellow
}

# --- Select config ---
if ($Config -eq "") {
    $winConfig = Join-Path $PSScriptRoot "config.windows.json"
    if (Test-Path $winConfig) {
        $Config = "config.windows.json"
    } else {
        $Config = "config.json"
    }
}
Write-Host "[OK] Using config: $Config" -ForegroundColor Green

# --- Show available ports ---
$ports = Get-SerialPorts
if ($ports.Count -gt 0) {
    Write-Host "[INFO] Detected COM ports: $($ports -join ', ')" -ForegroundColor Cyan
}

# --- Interactive menu if no mode specified ---
if ($Mode -eq "") {
    Write-Host ""
    Write-Host "  Select mode:" -ForegroundColor White
    Write-Host "    1) REAL mode   - Connect to physical dispenser via RS-232"
    Write-Host "    2) MOCK mode   - Simulate dispenser (no hardware needed)"
    Write-Host "    3) REAL (once) - Single read, then exit"
    Write-Host "    4) MOCK (once) - Single simulated read, then exit"
    Write-Host "    5) Exit"
    Write-Host ""
    $choice = Read-Host "  Enter choice [1-5]"

    switch ($choice) {
        "1" { $Mode = "real" }
        "2" { $Mode = "mock" }
        "3" { $Mode = "real"; $Once = $true }
        "4" { $Mode = "mock"; $Once = $true }
        "5" { Write-Host "Exiting..."; exit 0 }
        default { Write-Host "Invalid choice. Exiting." -ForegroundColor Red; exit 1 }
    }
}

# --- Build command arguments ---
$cmdArgs = @("read_musashi.py", "--config", $Config)

if ($Mode -eq "mock") {
    $cmdArgs += "--mock"
}

if ($Port -ne "") {
    $cmdArgs += @("--port", $Port)
}

if ($Once) {
    $cmdArgs += "--once"
}

Write-Host ""
Write-Host "Starting $Mode mode..." -ForegroundColor Green
Write-Host "Command: python $($cmdArgs -join ' ')" -ForegroundColor DarkGray
Write-Host ""

# --- Run ---
python @cmdArgs

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Service stopped." -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
Read-Host "Press Enter to close"
