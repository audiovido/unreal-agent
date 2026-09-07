$ErrorActionPreference = "Continue"
$log = "C:\Users\Shadow\Desktop\Unreal-Agent\cinematic-v2\reports\cinematic\cast_durable\regression.log"
Start-Process -FilePath "C:\Users\Shadow\Desktop\Unreal-Agent\.venv\Scripts\python.exe" `
  -ArgumentList "-m","pytest","tests","-q" `
  -WorkingDirectory "C:\Users\Shadow\Desktop\Unreal-Agent\cinematic-v2" `
  -RedirectStandardOutput $log -RedirectStandardError "$log.err" `
  -WindowStyle Hidden
Write-Output "launched"