# remove_task_scheduler.ps1
# Unregisters Task Scheduler tasks for MDDP.
# Run from Administrator PowerShell:
# powershell -ExecutionPolicy Bypass -File .\remove_task_scheduler.ps1

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MDDP Task Scheduler Cleanup (Windows)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$TaskNames = @("MDDP_StartServices", "MDDP_Watchdog")

foreach ($task in $TaskNames) {
    if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $task -Confirm:$false
        Write-Host "[OK] Removed task: $task" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Task not found: $task" -ForegroundColor Yellow
    }
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Cleanup complete." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
