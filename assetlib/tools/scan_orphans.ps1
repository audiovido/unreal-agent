$targets = 3256, 15428, 16104, 11928, 19636
foreach ($id in $targets) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    if ($p) {
        $cl = $p.CommandLine
        if ($cl.Length -gt 220) { $cl = $cl.Substring(0, 220) }
        Write-Output ($p.ProcessId.ToString() + ' | ' + $p.Name + ' | ' + $cl)
    } else {
        Write-Output ($id.ToString() + ' | NOT_RUNNING')
    }
}
Write-Output '--- UE sessions ---'
Get-Process -Name 'UnrealEditor*' -ErrorAction SilentlyContinue |
    Select-Object Id, SessionId, @{n='WS_MB'; e={[int]($_.WorkingSet64 / 1MB)}} |
    Format-Table -AutoSize
