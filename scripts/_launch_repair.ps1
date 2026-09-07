$ErrorActionPreference = "Continue"
$log = "C:\Users\Shadow\Desktop\Unreal-Agent\cinematic-v2\reports\cinematic\cast_durable\all_run.log"
Start-Process -FilePath "C:\Users\Shadow\Desktop\Unreal-Agent\.venv\Scripts\python.exe" `
  -ArgumentList "scripts/cast_durable_repair.py","--all","--save" `
  -WorkingDirectory "C:\Users\Shadow\Desktop\Unreal-Agent\cinematic-v2" `
  -RedirectStandardOutput $log -RedirectStandardError "$log.err" `
  -WindowStyle Hidden
Write-Output "launched"