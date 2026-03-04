Write-Output '--- Attempt Start-Service ---'
try {
    Start-Service -Name HLSConverter -ErrorAction Stop
    Write-Output 'Start-Service succeeded'
} catch {
    Write-Output 'Start-Service failed:'
    Write-Output $_.Exception.Message
}

Write-Output '--- Service state ---'
Get-Service -Name HLSConverter | Format-List
