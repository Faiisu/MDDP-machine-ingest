# watchdog.ps1
# Health-check script that verifies all MDDP service ports are listening.
# If any service is down, it restarts the service stack.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.." | Select-Object -ExpandProperty Path
$LogFile = Join-Path $ProjectRoot "logs\watchdog.log"

if (-not (Test-Path "$ProjectRoot\logs")) {
    New-Item -ItemType Directory -Path "$ProjectRoot\logs" | Out-Null
}

function Write-Log($message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $message" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

$Ports = @(8080, 8081, 8082, 8083, 8084, 8085, 18085)
$DownPorts = @()

foreach ($port in $Ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conn) {
        $DownPorts += $port
    }
}

if ($DownPorts.Count -gt 0) {
    Write-Log "[RESTART] Services down on ports: $($DownPorts -join ', '). Triggering run.bat..."
    Set-Location $ProjectRoot
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c ""`$ProjectRoot\deploy\windows\run.bat""" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
} else {
    Write-Log "[HEARTBEAT] All services UP (8080, 8081, 8082, 8083, 8084, 8085, 18085)"
}
