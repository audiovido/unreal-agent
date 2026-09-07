<#
AIVIDO V1 - ONE-CLICK INSTALLER / BOOTSTRAP

What it does (idempotent - a second run reuses what already exists):
  1. checks Python on the machine
  2. creates .venv if missing
  3. installs requirements.txt only when needed (fresh venv, missing
     imports, or -Upgrade)
  4. validates the runtime import contract
  5. detects the Unreal Editor build (read-only registry scan)
  6. detects / selects a .uproject (recent project first, then scan)
  7. starts the PERSISTENT backend (survives this terminal closing)
  8. opens the Aivido UI at http://127.0.0.1:8765/app

Usage:
  .\install-aivido.ps1                one-click install + start + UI
  .\install-aivido.ps1 -Upgrade       force dependency reinstall
  .\install-aivido.ps1 -NoBrowser     start without opening the UI
  .\install-aivido.ps1 -Project C:\...\X.uproject   pin a project

Compatibility: Windows PowerShell 5.1. All python-side checks run through
scripts\aivido_install_check.py (a plain native call); no inline python
here-strings are generated, so the script parses under PS 5.1 regardless
of console encoding.
#>
[CmdletBinding()]
param(
    [switch]$Upgrade,
    [switch]$NoBrowser,
    [string]$Project = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-WarnMsg($msg) { Write-Host "    WARN: $msg" -ForegroundColor Yellow }

# Invoke a native command without letting stderr trip $ErrorActionPreference.
function Invoke-Native($FilePath, [string[]]$ArgumentList) {
    & $FilePath @ArgumentList 2>&1 | Out-Null
    return $LASTEXITCODE
}

Write-Host "==============================================" -ForegroundColor Magenta
Write-Host " AIVIDO V1 - installer" -ForegroundColor Magenta
Write-Host "==============================================" -ForegroundColor Magenta

# ---------------------------------------------------------------------------
# 1. Python
# ---------------------------------------------------------------------------
Write-Step "1/8 Python"

$python = $null
foreach ($cand in @("py", "python")) {
    $probe = Get-Command $cand -ErrorAction SilentlyContinue
    if ($probe) {
        try {
            $verLine = (& $cand -3 --version 2>&1 | Select-Object -First 1)
            if (-not $verLine) { $verLine = (& $cand --version 2>&1 | Select-Object -First 1) }
            if ($verLine -match "Python (\d+)\.(\d+)") {
                $major = [int]$Matches[1]; $minor = [int]$Matches[2]
                if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 9)) {
                    $python = $cand
                    Write-OK "Python $major.$minor via '$cand'"
                    break
                } else {
                    Write-WarnMsg "'$cand' is Python $major.$minor (need >= 3.9)"
                }
            }
        } catch {}
    }
}
if (-not $python) {
    Write-Host "FAIL: no usable Python (>= 3.9) found. Install Python from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 2. .venv
# ---------------------------------------------------------------------------
Write-Step "2/8 Virtual environment"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-OK "creating .venv (first run)"
    $rc = Invoke-Native $python @("-m", "venv", "$Root\.venv")
    if (-not (Test-Path $venvPy)) {
        Write-Host "FAIL: could not create .venv" -ForegroundColor Red
        exit 1
    }
} else {
    Write-OK ".venv exists - reusing"
}

$checker = Join-Path $Root "scripts\aivido_install_check.py"

# ---------------------------------------------------------------------------
# 3. requirements (only when needed)
# ---------------------------------------------------------------------------
Write-Step "3/8 Dependencies (idempotent)"
$needInstall = $Upgrade
if (-not $needInstall) {
    $probeRc = Invoke-Native $venvPy @($checker, "imports")
    if ($probeRc -ne 0) { $needInstall = $true }
}
if ($needInstall) {
    Write-OK "installing requirements.txt"
    $rc = Invoke-Native $venvPy @("-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip")
    $rc = Invoke-Native $venvPy @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "$Root\requirements.txt")
    if ($rc -ne 0) {
        Write-Host "FAIL: dependency installation failed; see pip output above" -ForegroundColor Red
        exit 1
    }
} else {
    Write-OK "import contract satisfied - no reinstall"
}

# ---------------------------------------------------------------------------
# 4. Validate imports
# ---------------------------------------------------------------------------
Write-Step "4/8 Import validation"
$rc = Invoke-Native $venvPy @($checker, "imports")
if ($rc -ne 0) {
    Write-Host "FAIL: runtime imports still broken after install" -ForegroundColor Red
    exit 1
}
Write-OK "all runtime imports resolve"

# ---------------------------------------------------------------------------
# 5. Unreal Editor detection (read-only)
# ---------------------------------------------------------------------------
Write-Step "5/8 Unreal Editor"
$editorLine = (& $venvPy $checker editor 2>&1 | Select-Object -Last 1)
if ($editorLine -like "EDITOR=*" -and $editorLine -ne "EDITOR=none") {
    $parts = $editorLine.Substring(7).Split("|")
    if ($parts.Count -ge 2) {
        Write-OK "Unreal build: $($parts[0]) -> $($parts[1])"
    } else {
        Write-OK "Unreal build detected: $($editorLine.Substring(7))"
    }
} else {
    Write-WarnMsg "no Epic build registry found (fine when an editor is already open on the bridge)"
}

# ---------------------------------------------------------------------------
# 6. Project detection / selection
# ---------------------------------------------------------------------------
Write-Step "6/8 Project"
$projectArgs = @($checker, "project")
if ($Project) { $projectArgs += $Project }
$projLine = (& $venvPy $projectArgs 2>&1 | Select-Object -Last 1)
if ($projLine -like "PROJECT=*" -and $projLine -ne "PROJECT=none" -and $projLine -notlike "PROJECT=probe_error*") {
    $projectPath = $projLine.Substring(8)
    Write-OK "project selected: $projectPath"
} else {
    Write-WarnMsg "no .uproject found; proceeding (bridge editor already open is fine)"
}

# ---------------------------------------------------------------------------
# 7. Persistent backend
# ---------------------------------------------------------------------------
Write-Step "7/8 Persistent backend (survives terminal close)"
& $venvPy "$Root\scripts\aivido_runtime.py" start 2>&1 | Tee-Object -Variable startOut | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: backend did not start. Run: .\start-aivido.ps1 status" -ForegroundColor Red
    exit 1
}
$startOut | ForEach-Object { Write-OK $_ }
Write-OK "backend persistent + healthy"

# ---------------------------------------------------------------------------
# 8. Open UI
# ---------------------------------------------------------------------------
Write-Step "8/8 Aivido UI"
Write-Host ""
Write-Host "  Local  : http://127.0.0.1:8765/app" -ForegroundColor Green
Write-Host "  Status : .\start-aivido.ps1 status" -ForegroundColor Green
Write-Host "  Stop   : .\stop-aivido.cmd" -ForegroundColor Green
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:8765/app"
    Write-OK "opened UI in your browser"
}
Write-Host "`nAIVIDO V1 INSTALL OK" -ForegroundColor Green
exit 0