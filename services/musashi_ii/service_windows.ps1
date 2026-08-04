# ============================================================
#  MUSASHI Telemetry - Windows Background Service Manager
#  
#  Usage (Run as Administrator):
#    .\service_windows.ps1 install      # Install as scheduled task
#    .\service_windows.ps1 start        # Start the service
#    .\service_windows.ps1 stop         # Stop the service
#    .\service_windows.ps1 status       # Check service status
#    .\service_windows.ps1 uninstall    # Remove the scheduled task
#    .\service_windows.ps1 logs         # View log file
#    .\service_windows.ps1 run-hidden   # Run in hidden window (internal)
# ============================================================

param(
    [Parameter(Position=0)]
    [ValidateSet("install", "start", "stop", "status", "uninstall", "logs", "run-hidden")]
    [string]$Action = "status"
)

# --- Configuration ---
$TaskName        = "MusashiTelemetryService"
$TaskDescription = "MUSASHI Super Sigma CMII Dispenser - Telemetry Ingestion Service"
$ProjectDir      = $PSScriptRoot
$PythonExe       = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
$PythonFallback  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Script          = Join-Path $ProjectDir "read_musashi.py"
$ConfigFile      = if (Test-Path (Join-Path $ProjectDir "config.windows.json")) { "config.windows.json" } else { "config.json" }
$LogDir          = Join-Path $ProjectDir "logs"
$LogFile         = Join-Path $LogDir "musashi_service.log"
$PidFile         = Join-Path $LogDir "musashi_service.pid"

# --- Ensure log directory exists ---
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# --- Select Python executable ---
if (-not (Test-Path $PythonExe)) {
    if (Test-Path $PythonFallback) {
        $PythonExe = $PythonFallback
    } else {
        # Fall back to system python
        $PythonExe = "pythonw.exe"
    }
}

function Write-Status($icon, $msg) {
    $color = switch ($icon) {
        "OK"    { "Green" }
        "ERR"   { "Red" }
        "WARN"  { "Yellow" }
        "INFO"  { "Cyan" }
        default { "White" }
    }
    Write-Host "  [$icon] " -ForegroundColor $color -NoNewline
    Write-Host $msg
}

function Show-Header {
    Write-Host ""
    Write-Host "  =============================================" -ForegroundColor Cyan
    Write-Host "   MUSASHI Telemetry - Background Service" -ForegroundColor White
    Write-Host "  =============================================" -ForegroundColor Cyan
    Write-Host ""
}

# ============================================================
#  ACTION: install
# ============================================================
function Install-Service {
    Show-Header

    # Check if already installed
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Status "WARN" "Task '$TaskName' already exists. Uninstall first or use 'start'."
        return
    }

    # Build the wrapper command that logs output
    $wrapperScript = Join-Path $ProjectDir "service_windows.ps1"
    
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapperScript`" run-hidden" `
        -WorkingDirectory $ProjectDir

    # Trigger: at logon of current user
    $triggerLogon = New-ScheduledTaskTrigger -AtLogon

    # Settings: restart on failure, don't stop on idle, run indefinitely
    $settings = New-ScheduledTaskSettingsSet `
        -RestartCount 5 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -DontStopIfGoingOnBatteries `
        -AllowStartIfOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Days 0)  # No time limit (run forever)

    try {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $triggerLogon `
            -Settings $settings `
            -Description $TaskDescription `
            -RunLevel Highest `
            -Force | Out-Null

        Write-Status "OK" "Scheduled task '$TaskName' installed."
        Write-Status "INFO" "Trigger: Runs at user logon"
        Write-Status "INFO" "Auto-restart: 5 retries, 1 min interval"
        Write-Status "INFO" "Log file: $LogFile"
        Write-Host ""
        Write-Status "INFO" "Run '.\service_windows.ps1 start' to start now."
    } catch {
        Write-Status "ERR" "Failed to register task: $_"
        Write-Status "INFO" "Try running PowerShell as Administrator."
    }
}

# ============================================================
#  ACTION: run-hidden (internal - called by Task Scheduler)
# ============================================================
function Start-Hidden {
    Set-Location $ProjectDir
    
    # Activate venv
    $activateScript = Join-Path $ProjectDir ".venv\Scripts\Activate.ps1"
    if (Test-Path $activateScript) {
        & $activateScript
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$timestamp] Service starting..."
    Add-Content -Path $LogFile -Value "[$timestamp] Python: $PythonExe"
    Add-Content -Path $LogFile -Value "[$timestamp] Config: $ConfigFile"
    Add-Content -Path $LogFile -Value "[$timestamp] Working dir: $ProjectDir"

    # Start the process and save PID
    $proc = Start-Process -FilePath $PythonExe `
        -ArgumentList "read_musashi.py --config $ConfigFile" `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir "musashi_stdout.log") `
        -RedirectStandardError  (Join-Path $LogDir "musashi_stderr.log") `
        -PassThru

    # Save PID for stop command
    $proc.Id | Out-File -FilePath $PidFile -Force

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$timestamp] Process started with PID: $($proc.Id)"

    # Wait for the process to exit (keeps the task alive)
    $proc.WaitForExit()

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$timestamp] Process exited with code: $($proc.ExitCode)"
}

# ============================================================
#  ACTION: start
# ============================================================
function Start-Service-Now {
    Show-Header

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Status "WARN" "Task not installed. Run '.\service_windows.ps1 install' first."
        return
    }

    if ($task.State -eq "Running") {
        Write-Status "WARN" "Service is already running."
        Get-ServiceStatus
        return
    }

    try {
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
        Write-Status "OK" "Service started."
        Get-ServiceStatus
    } catch {
        Write-Status "ERR" "Failed to start: $_"
    }
}

# ============================================================
#  ACTION: stop
# ============================================================
function Stop-Service-Now {
    Show-Header

    # Stop the scheduled task
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Status "OK" "Scheduled task stopped."
    }

    # Also kill the Python process if PID file exists
    if (Test-Path $PidFile) {
        $procId = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($procId) {
            try {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc) {
                    Stop-Process -Id $procId -Force
                    Write-Status "OK" "Python process (PID: $procId) terminated."
                }
            } catch {
                Write-Status "INFO" "Process already stopped."
            }
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        }
    }

    # Kill any remaining read_musashi processes
    $procs = Get-Process -Name "python*" -ErrorAction SilentlyContinue | 
        Where-Object { $_.CommandLine -like "*read_musashi*" }
    foreach ($p in $procs) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        Write-Status "OK" "Killed orphan process PID: $($p.Id)"
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$timestamp] Service stopped by user."
    
    Write-Status "OK" "Service stopped."
}

# ============================================================
#  ACTION: status
# ============================================================
function Get-ServiceStatus {
    Show-Header

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Status "INFO" "Service is NOT installed."
        Write-Status "INFO" "Run '.\service_windows.ps1 install' to set up."
        return
    }

    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue

    $stateColor = switch ($task.State) {
        "Running" { "Green" }
        "Ready"   { "Yellow" }
        default   { "Red" }
    }

    Write-Host "  Task Name:    " -NoNewline; Write-Host $TaskName -ForegroundColor White
    Write-Host "  State:        " -NoNewline; Write-Host $task.State -ForegroundColor $stateColor
    if ($info) {
        Write-Host "  Last Run:     $($info.LastRunTime)"
        Write-Host "  Last Result:  $($info.LastTaskResult)"
        Write-Host "  Next Run:     $($info.NextRunTime)"
    }

    # Show PID if running
    if ((Test-Path $PidFile)) {
        $procId = Get-Content $PidFile -ErrorAction SilentlyContinue
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  PID:          " -NoNewline; Write-Host $procId -ForegroundColor Green
            Write-Host "  Memory:       $([math]::Round($proc.WorkingSet64 / 1MB, 1)) MB"
            Write-Host "  CPU Time:     $($proc.TotalProcessorTime.ToString('hh\:mm\:ss'))"
        }
    }

    Write-Host "  Log File:     $LogFile"
    Write-Host ""
}

# ============================================================
#  ACTION: uninstall
# ============================================================
function Uninstall-Service {
    Show-Header

    # Stop first
    Stop-Service-Now 2>$null

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Status "OK" "Scheduled task '$TaskName' removed."
    } else {
        Write-Status "INFO" "Task was not installed."
    }
}

# ============================================================
#  ACTION: logs
# ============================================================
function Show-Logs {
    Show-Header
    
    Write-Host "  --- Service Log ---" -ForegroundColor Cyan
    if (Test-Path $LogFile) {
        Get-Content $LogFile -Tail 30
    } else {
        Write-Status "INFO" "No service log found yet."
    }

    Write-Host ""
    Write-Host "  --- Application Output (last 20 lines) ---" -ForegroundColor Cyan
    $stdoutLog = Join-Path $LogDir "musashi_stdout.log"
    if (Test-Path $stdoutLog) {
        Get-Content $stdoutLog -Tail 20
    } else {
        Write-Status "INFO" "No stdout log found yet."
    }

    Write-Host ""
    Write-Host "  --- Errors (last 10 lines) ---" -ForegroundColor Red
    $stderrLog = Join-Path $LogDir "musashi_stderr.log"
    if (Test-Path $stderrLog) {
        $content = Get-Content $stderrLog -Tail 10
        if ($content) { $content } else { Write-Status "OK" "No errors." }
    } else {
        Write-Status "OK" "No error log found."
    }
}

# ============================================================
#  DISPATCH
# ============================================================
switch ($Action) {
    "install"    { Install-Service }
    "start"      { Start-Service-Now }
    "stop"       { Stop-Service-Now }
    "status"     { Get-ServiceStatus }
    "uninstall"  { Uninstall-Service }
    "logs"       { Show-Logs }
    "run-hidden" { Start-Hidden }
}
