# setup_task_scheduler.ps1
# Sets up Windows Task Scheduler tasks for 24-hour unattended operation.
# Run from Administrator PowerShell:
# powershell -ExecutionPolicy Bypass -File .\setup_task_scheduler.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.." | Select-Object -ExpandProperty Path

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MDDP Task Scheduler Setup (Windows)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Project directory: $ProjectRoot"

# 1. Task: Start all services on system boot
$TaskNameStart = "MDDP_StartServices"
$ActionStart   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c ""`$ProjectRoot\deploy\windows\run.bat""" -WorkingDirectory $ProjectRoot
$TriggerStart  = New-ScheduledTaskTrigger -AtStartup
$SettingsStart = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask -TaskName $TaskNameStart `
                       -Action $ActionStart `
                       -Trigger $TriggerStart `
                       -Settings $SettingsStart `
                       -User "NT AUTHORITY\SYSTEM" `
                       -RunLevel Highest `
                       -Force | Out-Null

Write-Host "[OK] Created task: $TaskNameStart (runs on system startup)" -ForegroundColor Green

# 2. Task: Watchdog (checks every 5 minutes)
$TaskNameWatchdog = "MDDP_Watchdog"
$ActionWatchdog   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File ""`$ProjectRoot\deploy\windows\watchdog.ps1""" -WorkingDirectory $ProjectRoot
$TriggerWatchdog  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$SettingsWatchdog = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

Register-ScheduledTask -TaskName $TaskNameWatchdog `
                       -Action $ActionWatchdog `
                       -Trigger $TriggerWatchdog `
                       -Settings $SettingsWatchdog `
                       -User "NT AUTHORITY\SYSTEM" `
                       -RunLevel Highest `
                       -Force | Out-Null

Write-Host "[OK] Created task: $TaskNameWatchdog (runs every 5 minutes)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Setup complete! Services will auto-start on next reboot." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
