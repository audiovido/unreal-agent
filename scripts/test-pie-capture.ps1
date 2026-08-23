$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$test = Join-Path $PSScriptRoot "test_pie_capture.py"

if (-not (Test-Path $python)) {
    Write-Host "FAIL: Agent venv Python not found: $python"
    exit 10
}

& $python $test
exit $LASTEXITCODE
