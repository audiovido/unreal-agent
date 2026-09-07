param(
    [switch]$NoBrowser
)

$Root =
    Split-Path -Parent $PSScriptRoot

Set-Location $Root

$Python =
    Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    # Clean-install bootstrap: create the venv from the authoritative
    # runtime dependency contract (requirements.txt) so a fresh clone
    # cannot start with a broken import closure (e.g. missing requests).
    Write-Host "Virtual environment not found; creating it from requirements.txt..."
    python -m venv "$Root\.venv"
    if (-not (Test-Path $Python)) {
        Write-Host "Could not create the virtual environment."
        exit 1
    }
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Dependency installation failed; see pip output above."
        exit 1
    }
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

& $Python -m uvicorn app.served:app `
    --host 127.0.0.1 `
    --port 8765
