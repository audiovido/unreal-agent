<#
AIVIDO V1 - control launcher (start / stop / restart / status / ui / remote)

One launcher for the whole runtime:
  .\start-aivido.ps1                 start backend + open UI (default)
  .\start-aivido.ps1 start           start persistent backend
  .\start-aivido.ps1 stop            stop backend (bridge/gateway untouched)
  .\start-aivido.ps1 restart         stop then start
  .\start-aivido.ps1 status          state + health + log paths
  .\start-aivido.ps1 ui              open http://127.0.0.1:8765/app
  .\start-aivido.ps1 doctor          full V1 self-test (PASS/WARN/FAIL)
  .\start-aivido.ps1 doctor -Quick   non-destructive self-test
  .\start-aivido.ps1 smoke           real bounded Unreal smoke mission
  .\start-aivido.ps1 remote          Tailscale remote status
  .\start-aivido.ps1 remote on       expose UI via Tailscale only
  .\start-aivido.ps1 remote off      disable Tailscale exposure

Compatibility: Windows PowerShell 5.1 (no here-strings / inline python).
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "start",
    [Parameter(Position = 1)]
    [string]$RemoteAction = "",
    [switch]$Quick,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Bootstrap: an empty clone must self-heal before any command runs.
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "No .venv found - running installer bootstrap..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$Root\install-aivido.ps1" -NoBrowser 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

function Invoke-Aivido($argsList) {
    & $venvPy "$Root\scripts\aivido_runtime.py" @argsList 2>&1
    exit $LASTEXITCODE
}

switch ($Command.ToLower()) {
    "start" {
        & $venvPy "$Root\scripts\aivido_runtime.py" start 2>&1
        if ($LASTEXITCODE -ne 0) { exit 1 }
        if (-not $NoBrowser) {
            Start-Process "http://127.0.0.1:8765/app"
        }
        exit 0
    }
    "stop"   { Invoke-Aivido @("stop") }
    "restart" { Invoke-Aivido @("restart") }
    "status" { Invoke-Aivido @("status") }
    "ui"     { Invoke-Aivido @("ui") }
    "logs"   { Invoke-Aivido @("logs") }
    "remote" {
        $action = "status"
        if ($RemoteAction) { $action = $RemoteAction }
        Invoke-Aivido @("remote", $action)
    }
    "doctor" {
        $dArgs = @()
        if ($Quick) { $dArgs += "--quick" }
        & $venvPy "$Root\scripts\aivido_doctor.py" @dArgs 2>&1
        exit $LASTEXITCODE
    }
    "smoke" {
        & $venvPy "$Root\scripts\aivido_smoke.py" 2>&1
        exit $LASTEXITCODE
    }
    default {
        Write-Host "Unknown command: $Command"
        Write-Host "Commands: start stop restart status ui logs doctor smoke remote"
        exit 1
    }
}