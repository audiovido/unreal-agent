$victims = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^UnrealEditor' -and $_.CommandLine -match 'assetlib\\tests\\ue\\ASSET_'
}
$count = 0
foreach ($p in $victims) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        Write-Output ("killed " + $p.ProcessId + " " + $p.Name)
        $count++
    } catch {
        Write-Output ("FAILED " + $p.ProcessId + " " + $_.Exception.Message)
    }
}
Write-Output ("TOTAL " + $count)
