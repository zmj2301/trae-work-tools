# Script to create a scheduled task for TRAE Work auto sign-in
# Run this script as Administrator

$action = New-ScheduledTaskAction -Execute "python.exe" -Argument "C:\Users\ZHOUy\Desktop\coing\trae_signin.py --manual" -WorkingDirectory "C:\Users\ZHOUy\Desktop\coing"
$trigger = New-ScheduledTaskTrigger -Daily -At "10:00AM"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Highest

Register-ScheduledTask -TaskName "TRAE Work Daily Sign-In" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Auto sign-in for TRAE Work daily credits"

Write-Host "Scheduled task created successfully!" -ForegroundColor Green
Write-Host "Task will run daily at 10:00 AM" -ForegroundColor Yellow
Write-Host "To manage the task, open Task Scheduler and search for 'TRAE Work Daily Sign-In'" -ForegroundColor Cyan
