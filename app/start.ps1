param(
    [switch]$NoBrowser
)

$Root =
    Split-Path -Parent $PSScriptRoot

Set-Location $Root

$Python =
    Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Virtual environment not found."
    exit 1
}

Write-Host ""
Write-Host "===================================="
Write-Host " Unreal Agent Studio"
Write-Host " http://127.0.0.1:8765"
Write-Host "===================================="
Write-Host ""

if (-not $NoBrowser) {
    Start-Job {
        Start-Sleep -Seconds 2
        Start-Process "http://127.0.0.1:8765"
    } | Out-Null
}

& $Python -m uvicorn app.api:app `
    --host 127.0.0.1 `
    --port 8765
