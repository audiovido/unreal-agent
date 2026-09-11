$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'ASSET_Showcase' -or $_.CommandLine -match 'assetlib'
}
if (-not $procs) { Write-Output "NONE_MATCH" }
foreach ($p in $procs) {
    $cl = $p.CommandLine
    if ($cl.Length -gt 200) { $cl = $cl.Substring(0, 200) }
    Write-Output ($p.ProcessId.ToString() + ' | ' + $p.Name + ' | ' + $cl)
}
