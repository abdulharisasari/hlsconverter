Write-Output '--- Checking nssm ---'
$cmd = Get-Command nssm -ErrorAction SilentlyContinue
if ($cmd) {
    Write-Output "nssm found at: $($cmd.Source)"
} else {
    Write-Output 'nssm not found'
}

Write-Output '--- Attempting Restart-Service ---'
try {
    Restart-Service -Name HLSConverter -Force -ErrorAction Stop
    Write-Output 'Restart-Service succeeded'
} catch {
    Write-Output 'Restart-Service failed:'
    Write-Output $_.Exception.Message
}

Write-Output '--- Service state ---'
Get-Service -Name HLSConverter | Format-List
