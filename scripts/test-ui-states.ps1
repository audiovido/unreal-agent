$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$test = Join-Path $PSScriptRoot "test_ui_states.py"

if (-not (Test-Path $python)) {
    Write-Host "FAIL: Agent Python not found: $python"
    exit 10
}

& $python $test
exit $LASTEXITCODE
