$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectDir "logs"
$watchdogLog = Join-Path $logDir "watchdog.log"

if (-Not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

function Log-Message {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] $Message" | Out-File -FilePath $watchdogLog -Append
}

# Python Resolution
$pythonBin = "python"
if (Test-Path (Join-Path $projectDir ".venv\Scripts\python.exe")) {
    $pythonBin = Join-Path $projectDir ".venv\Scripts\python.exe"
} elseif (Test-Path (Join-Path $projectDir "venv\Scripts\python.exe")) {
    $pythonBin = Join-Path $projectDir "venv\Scripts\python.exe"
}

$services = @(
    @{ Name = "Portal Gateway"; Port = 8080; Command = "-m http.server 8080 --directory portal"; LogFile = "portal.log" },
    @{ Name = "DAQ Control Panel"; Port = 8081; Command = "USB4716\web_gui.py"; LogFile = "daq_panel.log" },
    @{ Name = "Musashi IV Panel"; Port = 8083; Command = "mushashi_IV\web_gui.py"; LogFile = "musashi_iv_panel.log" },
    @{ Name = "Database Plotter"; Port = 8084; Command = "plot_service\app.py"; LogFile = "plotter.log" }
)

$allUp = $true

foreach ($service in $services) {
    $portActive = Get-NetTCPConnection -LocalPort $service.Port -State Listen -ErrorAction SilentlyContinue
    if (-not $portActive) {
        $allUp = $false
        Log-Message "Service $($service.Name) on port $($service.Port) is DOWN. Attempting restart..."
        
        $serviceLog = Join-Path $logDir $service.LogFile
        $fullCommand = "cmd.exe"
        $arguments = "/c `"`"$pythonBin`" $($service.Command) >> `"$serviceLog`" 2>&1`""
        
        Start-Process -FilePath $fullCommand -ArgumentList $arguments -WindowStyle Hidden -WorkingDirectory $projectDir
        Log-Message "Restarted $($service.Name)"
    }
}

if ($allUp) {
    Log-Message "Heartbeat: All services are running."
}
