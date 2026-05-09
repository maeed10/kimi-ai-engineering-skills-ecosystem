$policyEngine = Start-Process -FilePath "python" -ArgumentList "$env:USERPROFILE\.kimi\skills\policy-engine\scripts\policy-engine-server.py", "--policy-dir", "$env:USERPROFILE\.kimi\policy", "--manifest", "$env:USERPROFILE\.kimi\policy\manifest.json", "--port", "9100", "--host", "127.0.0.1" -PassThru -WindowStyle Hidden
$phaseController = Start-Process -FilePath "python" -ArgumentList "$env:USERPROFILE\.kimi\skills\phase-controller\scripts\phase-controller-server.py", "--state-dir", "$env:USERPROFILE\.kimi\state", "--port", "9101", "--host", "127.0.0.1" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
$pe = Test-NetConnection -ComputerName 127.0.0.1 -Port 9100 -WarningAction SilentlyContinue
$pc = Test-NetConnection -ComputerName 127.0.0.1 -Port 9101 -WarningAction SilentlyContinue
if ($pe.TcpTestSucceeded -and $pc.TcpTestSucceeded) {
    Write-EventLog -LogName Application -Source "KimiDaemons" -EventId 1000 -EntryType Information -Message "Kimi daemons started successfully." -ErrorAction SilentlyContinue
} else {
    Write-EventLog -LogName Application -Source "KimiDaemons" -EventId 1001 -EntryType Warning -Message "Kimi daemon health check failed." -ErrorAction SilentlyContinue
}
