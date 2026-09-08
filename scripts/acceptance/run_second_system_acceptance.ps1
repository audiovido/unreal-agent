<#
AIVIDO V2 — SECOND-SYSTEM ACCEPTANCE RUNNER
============================================

One-command installation + acceptance validation for a completely different
Windows machine. Validates an extracted Aivido V2 package, installs the
declared runtime dependencies into a fully isolated temporary environment,
starts the certified backend, exercises the live Unreal bridge with ONE
read-only mission, verifies fresh screenshot evidence, tests a clean
restart, and emits a machine-readable acceptance JSON.

Usage (run from this checkout on the second machine):

  powershell -ExecutionPolicy Bypass -File scripts\acceptance\run_second_system_acceptance.ps1 `
      -PackagePath "C:\...\Aivido-V2"

  powershell -ExecutionPolicy Bypass -File scripts\acceptance\run_second_system_acceptance.ps1 `
      -PackagePath "C:\...\Aivido-V2" -ExpectedProject "AividoHQ" `
      -ExpectedMap "/Game/Maps/AividoHQ" -OutputPath "C:\reports\acceptance.json"

Phases (mirrors the second-system acceptance contract):
   01 validate package            11 verify active map
   02 create isolated runtime env 12 verify UI HTTP
   03 install runtime deps        13 run doctor
   04 validate python/runtime     14 run one READ-ONLY mission
   05 detect Unreal installation  15 wait for terminal mission result
   06 verify expected UE version  16 validate fresh screenshot/evidence
   07 start Aivido backend        17 verify no stale evidence
   08 verify backend health       18 test clean restart
   09 discover/verify bridge      19 emit machine-readable acceptance JSON
   10 verify project identity     20 shut down only processes it started

Failure model: every failure record contains stage, code, a human-readable
reason, and a suggested remediation. Codes:
  UNREAL_NOT_INSTALLED, UNSUPPORTED_UNREAL_VERSION, PYTHON_RUNTIME_FAILURE,
  DEPENDENCY_INSTALL_FAILURE, PORT_COLLISION, BACKEND_START_FAILURE,
  BRIDGE_UNAVAILABLE, WRONG_UNREAL_PROJECT, WRONG_ACTIVE_MAP,
  UI_UNAVAILABLE, DOCTOR_FAILURE, MISSION_TIMEOUT, MISSION_FAILURE,
  STALE_EVIDENCE, SCREENSHOT_INVALID, RESTART_FAILURE,
  PACKAGE_INTEGRITY_FAILURE

Safety guarantees:
  - never runs git reset/clean or touches any repository
  - never kills a process it did not start (command line verified)
  - never mutates the certified AividoHQ project (mission is read-only:
    no actor spawns, no level save; only the transient proof PNG is written)
  - cleans only its own temp dirs and processes; preserves logs on failure
  - -Mock/-MockScenario support hermetic testing without any live Unreal

Compatibility: Windows PowerShell 5.1. All python-side work is delegated to
plain native calls of scripts\acceptance\second_system_checks.py /
scripts\aivido_install_check.py (no inline python here-strings).
#>
[CmdletBinding()]
param(
    [string]$PackagePath = "",
    [int]$BackendPort = 8765,
    [int]$BridgePort = 6766,
    [string]$BaseUrl = "",
    [string]$ExpectedProject = "",
    [string]$ExpectedMap = "/Game/Maps/AividoHQ",
    [string]$UnrealExePath = "",
    [string]$OutputPath = "",
    [int]$BackendReadyTimeoutSeconds = 120,
    [int]$MissionTimeoutSeconds = 180,
    [int]$PipTimeoutSeconds = 600,
    [int]$EvidenceMaxAgeMinutes = 60,
    [switch]$KeepLogs,
    [switch]$SkipCleanup,
    [switch]$Mock,
    [string]$MockScenario = "success"
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Identity / paths
# ---------------------------------------------------------------------------
# scripts/acceptance/<this file> -> repo root (3 levels up).
$script:RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$script:RunId = "run_" + (Get-Date -Format "yyyyMMdd-HHmmss") + "_" + [Guid]::NewGuid().ToString("N").Substring(0, 6)
$script:RunDir = Join-Path $env:TEMP ("aivido-second-system-" + $script:RunId)
$script:EnvDir = Join-Path $script:RunDir "env"
$script:VenvPy = Join-Path $script:EnvDir ".venv\Scripts\python.exe"
$script:LogsDir = Join-Path $script:RunDir "logs"
$script:ReportDir = Join-Path $script:RepoRoot ("reports\second_system\" + $script:RunId)
$script:PackageRoot = ""
$script:PackageVersion = "unknown"
$script:PackageSha = ""
$script:BackendLogOut = ""
$script:BackendLogErr = ""

# Accumulators
$script:Steps = @()
$script:Failures = @()
$script:Warnings = @()
$script:Started = @()          # @{Pid; CommandLine; StartedAt}
$script:TempDirs = @($script:RunDir)

# Inter-phase state
$script:EnvReport = $null
$script:BridgeReport = $null
$script:UnrealVersion = ""
$script:UnrealBuilds = @()
$script:DoctorJson = $null
$script:MissionResult = $null
$script:MissionStartedAt = 0
$script:BaselineEvidenceSha = $null
$script:PostEvidence = $null
$script:BackendPid = $null
$script:CleanupResult = $null
$script:ReportFile = ""

# ---------------------------------------------------------------------------
# Mock scaffolding (hermetic tests only; never touches a live editor)
# ---------------------------------------------------------------------------
function Init-MockValues([string]$scenario) {
    $script:MockValues = @{
        python_ok            = $true
        deps_install_ok      = $true
        imports_ok           = $true
        unreal_builds        = @(@{ label = "5.8"; exe = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" })
        unreal_version       = "5.8"
        port_occupied        = $false
        backend_healthy      = $true
        bridge_reachable     = $true
        bridge_ping_ok       = $true
        identity_project     = "AividoHQ"
        active_map           = "/Game/Maps/AividoHQ"
        ui_ok                = $true
        doctor_ok            = $true
        mission_ok           = $true
        mission_diag         = $null
        mission_times_out    = $false
        evidence_ok          = $true
        evidence_diag        = $null
        baseline_evidence    = $true
        restart_ok           = $true
    }
    switch (([string]$scenario).ToLower()) {
        "python-runtime-fail" { $script:MockValues.python_ok = $false }
        "dep-install-fail"    { $script:MockValues.deps_install_ok = $false }
        "unreal-missing"      { $script:MockValues.unreal_builds = @() }
        "unsupported-version" { $script:MockValues.unreal_version = "4.27" }
        "port-collision"      { $script:MockValues.port_occupied = $true }
        "backend-fail"        { $script:MockValues.backend_healthy = $false }
        "bridge-down"         { $script:MockValues.bridge_reachable = $false; $script:MockValues.bridge_ping_ok = $false }
        "wrong-project"       { $script:MockValues.identity_project = "SomeOtherProject" }
        "wrong-map"           { $script:MockValues.active_map = "/Game/Maps/NotAivido" }
        "ui-down"             { $script:MockValues.ui_ok = $false }
        "doctor-fail"         { $script:MockValues.doctor_ok = $false }
        "mission-timeout"     { $script:MockValues.mission_times_out = $true }
        "mission-fail"        { $script:MockValues.mission_ok = $false; $script:MockValues.mission_diag = "MISSION_FAILED" }
        "stale-evidence"      { $script:MockValues.evidence_ok = $false; $script:MockValues.evidence_diag = "EVIDENCE_STALE" }
        "screenshot-invalid"  { $script:MockValues.evidence_ok = $false; $script:MockValues.evidence_diag = "EVIDENCE_INVALID" }
        "restart-fail"        { $script:MockValues.restart_ok = $false }
    }
}

$script:Mock = [bool]$Mock
$script:MockScenario = $MockScenario
Init-MockValues $MockScenario

function Get-MockValue([string]$key) {
    return $script:MockValues[$key]
}

function Test-Mock([string]$key, $defaultValue) {
    if ($script:Mock) { return $script:MockValues[$key] }
    return $defaultValue
}

# ---------------------------------------------------------------------------
# State reset (Main re-runs cleanly; also used by the hermetic tests)
# ---------------------------------------------------------------------------
function Reset-RunnerState([bool]$mock = $false, [string]$scenario = "success") {
    $script:Mock = $mock
    $script:MockScenario = $scenario
    Init-MockValues $scenario
    $script:RunId = "run_" + (Get-Date -Format "yyyyMMdd-HHmmss") + "_" + [Guid]::NewGuid().ToString("N").Substring(0, 6)
    $script:RunDir = Join-Path $env:TEMP ("aivido-second-system-" + $script:RunId)
    $script:EnvDir = Join-Path $script:RunDir "env"
    $script:VenvPy = Join-Path $script:EnvDir ".venv\Scripts\python.exe"
    $script:LogsDir = Join-Path $script:RunDir "logs"
    if ($env:AIVIDO_ACCEPTANCE_REPORT_DIR) {
        $script:ReportDir = Join-Path $env:AIVIDO_ACCEPTANCE_REPORT_DIR $script:RunId
    } else {
        $script:ReportDir = Join-Path $script:RepoRoot ("reports\second_system\" + $script:RunId)
    }
    $script:PackageRoot = ""
    $script:PackageVersion = "unknown"
    $script:PackageSha = ""
    $script:BackendLogOut = ""
    $script:BackendLogErr = ""
    $script:Steps = @()
    $script:Failures = @()
    $script:Warnings = @()
    $script:Started = @()
    $script:TempDirs = @($script:RunDir)
    $script:EnvReport = $null
    $script:BridgeReport = $null
    $script:BridgeDown = $false
    $script:UnrealVersion = ""
    $script:UnrealBuilds = @()
    $script:DoctorJson = $null
    $script:MissionResult = $null
    $script:MissionTimedOut = $false
    $script:MissionStartedAt = 0
    $script:BaselineEvidenceSha = $null
    $script:PostEvidence = $null
    $script:BackendPid = $null
    $script:CleanupResult = $null
}

# ---------------------------------------------------------------------------
# Failure classification catalog (stage is set at the call site)
# ---------------------------------------------------------------------------
$script:FailureCatalog = @{
    "UNREAL_NOT_INSTALLED"        = "Install Unreal Engine 5.x through the Epic Games Launcher (or pass -UnrealExePath pointing at an existing UnrealEditor.exe), then re-run acceptance."
    "UNSUPPORTED_UNREAL_VERSION"  = "Aivido V2 requires Unreal Engine 5.x. Install/set the required engine version, or pass -UnrealExePath to a UE 5.x editor, then re-run."
    "PYTHON_RUNTIME_FAILURE"      = "Install Python 3.9 or newer (python.org, check 'Add to PATH'), then re-run; a fresh isolated environment is created on every run."
    "DEPENDENCY_INSTALL_FAILURE"  = "The declared runtime dependencies (requirements.txt) could not be installed. Check network access to PyPI and pip output in the run logs, then re-run."
    "PORT_COLLISION"              = "Another process is already listening on the Aivido backend port (127.0.0.1:8765). Stop that process or free the port, then re-run. Aivido's backend port is fixed at 8765 by the certified product."
    "BACKEND_START_FAILURE"       = "The Aivido backend did not become healthy. Inspect the backend error log listed in the report (reports/second_system/<run>/logs/), fix the cause (often a missing dependency or a port conflict), then re-run."
    "BRIDGE_UNAVAILABLE"          = "Open the AividoHQ project in the Unreal Editor with the Aivido bridge running on 127.0.0.1:6766 (UA_BRIDGE_PORT overrides are supported), wait for the editor to fully load, then re-run."
    "WRONG_UNREAL_PROJECT"        = "The Unreal Editor has the wrong project open. Open the expected project (see report field unreal.project / pass -ExpectedProject), then re-run."
    "WRONG_ACTIVE_MAP"            = "The active map is not the expected Aivido map. Open the expected map in the editor (default /Game/Maps/AividoHQ, override with -ExpectedMap), then re-run."
    "UI_UNAVAILABLE"              = "The Aivido UI is not being served over HTTP. Confirm the backend is healthy (step 8) and that the package contains the UI resources, then re-run."
    "DOCTOR_FAILURE"              = "The Aivido doctor self-test reported failures. Review the doctor JSON in the report logs and fix the flagged checks, then re-run."
    "MISSION_TIMEOUT"             = "The read-only mission did not finish within the allowed time. The editor may be busy or unresponsive; wait for it to idle, increase -MissionTimeoutSeconds, then re-run."
    "MISSION_FAILURE"             = "The read-only mission did not pass. Inspect the mission steps in the report (mission.steps) for the failing check and remediate, then re-run."
    "STALE_EVIDENCE"              = "The proof endpoint served evidence that was not freshly produced by this run. Ensure the editor viewport renders (not minimized/occluded) so a fresh capture can be written, then re-run."
    "SCREENSHOT_INVALID"          = "The viewport capture/proof is missing, too small, or not a valid PNG. Bring the editor viewport to the foreground (a minimized or occluded editor cannot capture), then re-run."
    "RESTART_FAILURE"             = "The clean stop/start cycle failed. Check the backend logs for crash-on-start, free the backend port, then re-run."
    "PACKAGE_INTEGRITY_FAILURE"   = "The extracted package is incomplete or not an Aivido V2 package. Re-extract the package zip and verify the required files listed in the failure reason, then re-run."
}

function Get-Remedy([string]$code) {
    if ($script:FailureCatalog.ContainsKey($code)) { return $script:FailureCatalog[$code] }
    return "Inspect the run report and logs, remediate, and re-run acceptance."
}

function Add-Failure([string]$stage, [string]$code, [string]$reason) {
    $entry = @{
        stage       = $stage
        code        = $code
        reason      = $reason
        remediation = Get-Remedy $code
    }
    # Dedupe identical (stage, code) so a cascading failure is reported once.
    foreach ($f in $script:Failures) {
        if ($f["stage"] -eq $stage -and $f["code"] -eq $code) { return }
    }
    $script:Failures += $entry
    Write-Host ("  FAIL [{0}] {1}: {2}" -f $code, $stage, $reason) -ForegroundColor Red
}

function Add-Warning([string]$detail) {
    $script:Warnings += $detail
    Write-Host ("  WARN: {0}" -f $detail) -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------
function New-Step([int]$number, [string]$name) {
    $step = @{ number = $number; name = $name; status = "PENDING"; detail = ""; duration_s = 0; started = (Get-Date) }
    $script:Steps += $step
    return $step
}

function Complete-Step($step, [string]$status, [string]$detail) {
    $step.status = $status
    $step.detail = $detail
    $step.duration_s = [Math]::Round(((Get-Date) - $step.started).TotalSeconds, 1)
    $marker = "OK  "
    if ($status -eq "FAIL") { $marker = "FAIL" }
    if ($status -eq "SKIP") { $marker = "SKIP" }
    Write-Host ("  [{0}] {1:D2} {2}: {3}" -f $marker, $step.number, $step.name, $detail)
}

# ---------------------------------------------------------------------------
# Process / port / HTTP helpers (Windows PowerShell 5.1)
# ---------------------------------------------------------------------------
function ConvertTo-ArgumentString([string[]]$args) {
    $quoted = @()
    foreach ($a in $args) {
        $quoted += '"' + ($a -replace '"', '\"') + '"'
    }
    return ($quoted -join " ")
}

function Get-HttpResponse([string]$uri, [int]$timeoutSeconds = 5) {
    try {
        $r = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec $timeoutSeconds
        return @{ status = [int]$r.StatusCode; body = ([string]$r.Content); ok = $true }
    } catch {
        $code = 0
        if ($_.Exception.Response) {
            try { $code = [int]$_.Exception.Response.StatusCode } catch {}
        }
        return @{ status = $code; body = ""; ok = $false }
    }
}

function Test-TcpPort([string]$hostname, [int]$port, [int]$timeoutSeconds = 1) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $iar = $client.BeginConnect($hostname, $port, $null, $null)
            $wait = $iar.AsyncWaitHandle.WaitForExit($timeoutSeconds * 1000, $false)
            if (-not $wait) { return $false }
            if ($client.Connected) { return $true }
            return $false
        } finally {
            $client.Close()
        }
    } catch {
        return $false
    }
}

function Get-ListenerPids([int]$port) {
    $pids = @()
    try {
        $out = netstat -ano
        $needle = "127.0.0.1:$port"
        foreach ($line in $out) {
            if ($line -notmatch "LISTENING") { continue }
            $parts = ($line -split "\s+") | Where-Object { $_ -ne "" }
            if ($parts.Count -ge 5 -and $parts[1] -like "*$needle*") {
                $p = 0
                if ([int]::TryParse($parts[-1], [ref]$p)) { $pids += $p }
            }
        }
    } catch {}
    return ($pids | Sort-Object -Unique)
}

function Get-ProcessCommandLine([int]$processId) {
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if ($p) { return [string]$p.CommandLine }
    } catch {}
    return ""
}

function Register-RunnerProcess([int]$processId, [string]$commandLine) {
    $script:Started += @{ Pid = $processId; CommandLine = $commandLine; StartedAt = (Get-Date) }
}

# ---------------------------------------------------------------------------
# Bounded native invocation (no inline python here-strings)
# ---------------------------------------------------------------------------
function Invoke-Bounded {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [int]$TimeoutSeconds = 120,
        [string]$Tag = "cmd",
        [switch]$Detached
    )
    $tag = $Tag -replace "[^a-zA-Z0-9_-]", "_"
    $outFile = Join-Path $script:RunDir ("out_" + $tag + "_" + [Guid]::NewGuid().ToString("N").Substring(0, 8) + ".log")
    $errFile = Join-Path $script:RunDir ("err_" + $tag + "_" + [Guid]::NewGuid().ToString("N").Substring(0, 8) + ".log")
    $argString = ConvertTo-ArgumentString $ArgumentList
    $p = $null
    try {
        $p = Start-Process -FilePath $FilePath -ArgumentList $argString -WorkingDirectory $WorkingDirectory `
            -WindowStyle Hidden -RedirectStandardOutput $outFile -RedirectStandardError $errFile -PassThru
    } catch {
        return @{ ExitCode = -1; StdOut = ""; StdErr = "spawn failed: $_"; TimedOut = $false; OutFile = $outFile; ErrFile = $errFile; Process = $null; SpawnError = $true }
    }
    if ($Detached) {
        return @{ ExitCode = $null; StdOut = ""; StdErr = ""; TimedOut = $false; OutFile = $outFile; ErrFile = $errFile; Process = $p; SpawnError = $false }
    }
    $timedOut = -not $p.WaitForExit($TimeoutSeconds * 1000)
    if ($timedOut) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
    $stdout = ""
    $stderr = ""
    if (Test-Path $outFile) { try { $stdout = Get-Content $outFile -Raw } catch {} }
    if (Test-Path $errFile) { try { $stderr = Get-Content $errFile -Raw } catch {} }
    return @{
        ExitCode   = if ($timedOut) { -2 } else { $p.ExitCode }
        StdOut     = $stdout
        StdErr     = $stderr
        TimedOut   = $timedOut
        OutFile    = $outFile
        ErrFile    = $errFile
        Process    = $p
        SpawnError = $false
    }
}

function Find-SystemPython {
    foreach ($cand in @("py", "python")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            if ($cand -eq "py") {
                $line = (& py -3 --version 2>&1 | Select-Object -First 1)
            } else {
                $line = (& python --version 2>&1 | Select-Object -First 1)
            }
            if (-not $line) { $line = (& $cand --version 2>&1 | Select-Object -First 1) }
            if ($line -match "Python (\d+)\.(\d+)") {
                $major = [int]$Matches[1]; $minor = [int]$Matches[2]
                if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 9)) {
                    return @{ command = $cand; version = "$major.$minor" }
                }
            }
        } catch {}
    }
    return $null
}

function Get-PackageChecksum([string]$root) {
    # Stable content checksum: SHA-256 over sorted "relativepath:filehash" lines.
    $entries = @()
    try {
        $files = Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.FullName -notmatch "\\.venv\\|\\__pycache__\\|\\.git\\|\\config\\logs\\|\\config\\runtime\\"
            }
        foreach ($f in $files) {
            $rel = $f.FullName.Substring($root.Length).TrimStart("\", "/").Replace("\", "/")
            $hash = (Get-FileHash -Path $f.FullName -Algorithm SHA256 -ErrorAction SilentlyContinue).Hash
            if ($hash) { $entries += ("{0}:{1}" -f $rel, $hash) }
        }
    } catch {}
    $entries = $entries | Sort-Object
    $joined = ($entries -join "`n")
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($joined)
    return ([System.BitConverter]::ToString($sha.ComputeHash($bytes)) -replace "-", "").ToLower()
}

function Get-UnixTime {
    return [int64](([DateTime]::UtcNow) - (Get-Date "1970-01-01T00:00:00Z")).TotalSeconds
}

function Get-UtcIso {
    return [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}

# ---------------------------------------------------------------------------
# Checker helpers (python side: scripts/acceptance/second_system_checks.py)
# ---------------------------------------------------------------------------
function Invoke-Checker {
    param(
        [string[]]$Args,
        [int]$TimeoutSeconds = 120,
        [string]$Tag = "checker",
        [string]$WorkingDirectory = ""
    )
    if (-not $WorkingDirectory) { $WorkingDirectory = $script:RepoRoot }
    $checker = Join-Path $script:RepoRoot "scripts\acceptance\second_system_checks.py"
    $fullArgs = @($checker) + $Args
    if ($script:Mock) {
        # Hermetic mode: no python is executed; scenarios are driven by
        # mock values, so a canned success envelope is returned here and
        # each phase interprets it through Test-Mock.
        return @{ ExitCode = 0; StdOut = "{}"; StdErr = ""; TimedOut = $false; OutFile = ""; ErrFile = ""; Process = $null; SpawnError = $false }
    }
    return (Invoke-Bounded -FilePath $script:VenvPy -ArgumentList $fullArgs -WorkingDirectory $WorkingDirectory -TimeoutSeconds $TimeoutSeconds -Tag $Tag)
}

function Invoke-AInstallCheck {
    param([string[]]$Args, [int]$TimeoutSeconds = 60)
    $checker = Join-Path $script:RepoRoot "scripts\aivido_install_check.py"
    $fullArgs = @($checker) + $Args
    if ($script:Mock) {
        return @{ ExitCode = 0; StdOut = ""; StdErr = ""; TimedOut = $false; OutFile = ""; ErrFile = ""; Process = $null; SpawnError = $false }
    }
    return (Invoke-Bounded -FilePath $script:VenvPy -ArgumentList $fullArgs -WorkingDirectory $script:RepoRoot -TimeoutSeconds $TimeoutSeconds -Tag "installcheck")
}

function Parse-JsonFile([string]$path) {
    if (-not $path -or -not (Test-Path $path)) { return $null }
    try {
        return (Get-Content $path -Raw | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Copy-ToReport([string]$sourcePath) {
    if (-not $sourcePath -or -not (Test-Path $sourcePath)) { return }
    try {
        if (-not (Test-Path $script:ReportDir)) { New-Item -ItemType Directory -Path $script:ReportDir -Force | Out-Null }
        Copy-Item -Path $sourcePath -Destination $script:ReportDir -Force
    } catch {}
}

# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------
function Invoke-Phase01-ValidatePackage {
    $step = New-Step 1 "validate_package"
    $start = Get-Date
    $script:PackageRoot = $PackagePath
    if (-not $PackagePath -or -not (Test-Path $PackagePath)) {
        Add-Failure "validate_package" "PACKAGE_INTEGRITY_FAILURE" "PackagePath '$PackagePath' does not exist or is not accessible."
        Complete-Step $step "FAIL" "package path missing: $PackagePath"
        return
    }
    $root = $PackagePath
    $required = @("requirements.txt", "version.json", "app\served.py")
    $uiMarkers = @("ui\aivido.html", "ui\index.html")
    $launchers = @("install-aivido.ps1", "install-aivido.cmd", "start-aivido.ps1", "product_launcher.py")
    $missing = @()
    foreach ($r in $required) {
        if (-not (Test-Path (Join-Path $root $r))) { $missing += $r }
    }
    $hasUi = $false
    foreach ($m in $uiMarkers) { if (Test-Path (Join-Path $root $m)) { $hasUi = $true } }
    if (-not $hasUi) { $missing += "(ui/aivido.html or ui/index.html)" }
    $hasLauncher = $false
    foreach ($l in $launchers) { if (Test-Path (Join-Path $root $l)) { $hasLauncher = $true } }
    if (-not $hasLauncher) { $missing += "(install-aivido.ps1 / install-aivido.cmd / start-aivido.ps1 / product_launcher.py)" }

    if ($missing.Count -gt 0) {
        Add-Failure "validate_package" "PACKAGE_INTEGRITY_FAILURE" "package missing required file(s): $($missing -join ', ')"
        Complete-Step $step "FAIL" "missing: $($missing -join ', ')"
        return
    }

    # Version identity from version.json when present.
    try {
        $vj = Join-Path $root "version.json"
        if (Test-Path $vj) {
            $meta = Get-Content $vj -Raw | ConvertFrom-Json
            if ($meta.version) { $script:PackageVersion = [string]$meta.version }
            elseif ($meta.sha) { $script:PackageVersion = [string]$meta.sha }
            elseif ($meta.branch) { $script:PackageVersion = [string]$meta.branch }
        }
    } catch {}

    $script:PackageSha = Get-PackageChecksum $root
    $detail = "files OK; version=$script:PackageVersion checksum=$($script:PackageSha.Substring(0, [Math]::Min(12, $script:PackageSha.Length)))..."
    Complete-Step $step "PASS" $detail
}

function Invoke-Phase02-CreateEnv {
    $step = New-Step 2 "create_env"
    try {
        New-Item -ItemType Directory -Path $script:RunDir -Force | Out-Null
        New-Item -ItemType Directory -Path $script:EnvDir -Force | Out-Null
        New-Item -ItemType Directory -Path $script:LogsDir -Force | Out-Null
        New-Item -ItemType Directory -Path $script:ReportDir -Force | Out-Null
    } catch {
        Add-Failure "create_env" "PYTHON_RUNTIME_FAILURE" "could not create isolated runtime directories: $_"
        Complete-Step $step "FAIL" "temp dirs unavailable"
        return
    }
    if ($script:Mock) {
        # Mock mode: mark the env as created; no real venv is built.
        New-Item -ItemType Directory -Path (Join-Path $script:EnvDir ".venv\Scripts") -Force | Out-Null
        Complete-Step $step "PASS" "isolated env prepared (mock, no venv build)"
        return
    }
    $py = Find-SystemPython
    if (-not $py) {
        Add-Failure "create_env" "PYTHON_RUNTIME_FAILURE" "no usable Python (>= 3.9) found on PATH"
        Complete-Step $step "FAIL" "Python >= 3.9 not found"
        return
    }
    $res = Invoke-Bounded -FilePath $py.command -ArgumentList @("-m", "venv", $script:EnvDir + "\.venv") -WorkingDirectory $script:RunDir -TimeoutSeconds 180 -Tag "venv"
    if (-not (Test-Path $script:VenvPy)) {
        Add-Failure "create_env" "PYTHON_RUNTIME_FAILURE" "venv creation failed (python $($py.command)); stderr: $($res.StdErr)"
        Complete-Step $step "FAIL" "venv creation failed"
        return
    }
    Complete-Step $step "PASS" ("venv created with Python {0} at {1}" -f $py.version, $script:VenvPy)
}

function Invoke-Phase03-InstallDeps {
    $step = New-Step 3 "install_dependencies"
    $req = Join-Path $script:PackageRoot "requirements.txt"
    if (-not (Test-Path $req)) {
        Add-Failure "install_dependencies" "DEPENDENCY_INSTALL_FAILURE" "requirements.txt missing in package"
        Complete-Step $step "FAIL" "requirements.txt missing"
        return
    }
    $depsOk = Test-Mock "deps_install_ok" $true
    if (-not $depsOk) {
        Add-Failure "install_dependencies" "DEPENDENCY_INSTALL_FAILURE" "declared runtime dependencies could not be installed (see run logs)"
        Complete-Step $step "FAIL" "pip install failed"
        return
    }
    if (-not $script:Mock) {
        $res1 = Invoke-Bounded -FilePath $script:VenvPy -ArgumentList @("-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip") -WorkingDirectory $script:RunDir -TimeoutSeconds $PipTimeoutSeconds -Tag "pippip"
        $res2 = Invoke-Bounded -FilePath $script:VenvPy -ArgumentList @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", $req) -WorkingDirectory $script:RunDir -TimeoutSeconds $PipTimeoutSeconds -Tag "pipreq"
        if ($res2.ExitCode -ne 0) {
            Add-Failure "install_dependencies" "DEPENDENCY_INSTALL_FAILURE" "pip install -r requirements.txt failed (exit $($res2.ExitCode)); see log: $($res2.ErrFile)"
            Copy-ToReport $res2.ErrFile
            Complete-Step $step "FAIL" "pip install exit $($res2.ExitCode)"
            return
        }
    }
    Complete-Step $step "PASS" "declared runtime dependencies installed"
}

function Invoke-Phase04-ValidateRuntime {
    $step = New-Step 4 "validate_runtime"
    $res = Invoke-Checker -Args @("env", "--ports", "$BackendPort,$($BackendPort + 1)", "--bridge-port", "$BridgePort") -TimeoutSeconds 90 -Tag "env"
    $report = $null
    if (-not $script:Mock) {
        $report = Parse-JsonFile $res.OutFile
        if (-not $report) {
            Add-Failure "validate_runtime" "PYTHON_RUNTIME_FAILURE" "runtime probe produced no parseable output (exit $($res.ExitCode)); stderr: $($res.StdErr)"
            Complete-Step $step "FAIL" "runtime probe unreadable"
            return
        }
        $script:EnvReport = $report
        $pyOk = [bool]$report.python.ok
        $importsOk = [bool]$report.imports.ok
    } else {
        $pyOk = Test-Mock "python_ok" $true
        $importsOk = Test-Mock "imports_ok" $true
    }
    if (-not $pyOk) {
        Add-Failure "validate_runtime" "PYTHON_RUNTIME_FAILURE" "isolated Python runtime is not usable"
        Complete-Step $step "FAIL" "python runtime invalid"
        return
    }
    if (-not $importsOk) {
        Add-Failure "validate_runtime" "DEPENDENCY_INSTALL_FAILURE" "runtime import contract unresolved in isolated environment"
        Complete-Step $step "FAIL" "import contract missing"
        return
    }
    Complete-Step $step "PASS" "python + import contract OK"
}

function Invoke-Phase05-DetectUnreal {
    $step = New-Step 5 "detect_unreal"
    $builds = @()
    if (-not $script:Mock) {
        if ($UnrealExePath -and (Test-Path $UnrealExePath)) {
            $label = Split-Path (Split-Path (Split-Path (Split-Path $UnrealExePath -Parent) -Parent) -Parent) -Leaf
            $builds = @(@{ label = $label; exe = $UnrealExePath })
        } else {
            $res = Invoke-AInstallCheck -Args @("editor")
            $line = ($res.StdOut -split "`r?`n" | Select-Object -Last 1)
            if ($line -like "EDITOR=*" -and $line -ne "EDITOR=none") {
                $parts = $line.Substring(7).Split("|")
                $label = $parts[0]
                $exe = if ($parts.Count -ge 2) { $parts[1] } else { "" }
                $builds = @(@{ label = $label; exe = $exe })
            } elseif ($line -like "EDITOR=probe_error*") {
                Add-Warning "Unreal build probe reported an error: $line"
            }
        }
    } else {
        $builds = Test-Mock "unreal_builds" @()
    }
    $script:UnrealBuilds = $builds
    if ($builds.Count -eq 0) {
        Add-Failure "detect_unreal" "UNREAL_NOT_INSTALLED" "no Unreal Engine build found in the Epic registry and no -UnrealExePath given"
        Complete-Step $step "FAIL" "no Unreal Editor build detected"
        return
    }
    $detail = "found $($builds.Count) build(s): " + (($builds | ForEach-Object { $_.label }) -join ", ")
    Complete-Step $step "PASS" $detail
}

function Invoke-Phase06-VerifyUnrealVersion {
    $step = New-Step 6 "verify_unreal_version"
    $version = ""
    if (-not $script:Mock) {
        if ($script:UnrealBuilds.Count -gt 0) {
            $version = [string]$script:UnrealBuilds[0].label
        }
    } else {
        $version = [string](Test-Mock "unreal_version" "5.8")
    }
    $script:UnrealVersion = $version
    $nums = @()
    foreach ($t in ($version -split "[^0-9]+")) {
        if ($t -match "^\d+$") { $nums += [int]$t }
    }
    if ($nums.Count -eq 0) {
        Add-Failure "verify_unreal_version" "UNSUPPORTED_UNREAL_VERSION" "could not parse UE version from build label '$version'"
        Complete-Step $step "FAIL" "unparseable UE version '$version'"
        return
    }
    if ($nums[0] -lt 5) {
        Add-Failure "verify_unreal_version" "UNSUPPORTED_UNREAL_VERSION" "detected UE $version; Aivido V2 requires UE 5.x"
        Complete-Step $step "FAIL" "UE $version not supported"
        return
    }
    Complete-Step $step "PASS" "UE $version supported"
}

function Invoke-Phase07-StartBackend {
    $step = New-Step 7 "start_backend"
    $occupied = Test-Mock "port_occupied" $false
    if (-not $script:Mock) { $occupied = Test-TcpPort "127.0.0.1" $BackendPort }
    if ($occupied) {
        $owners = @()
        if (-not $script:Mock) { $owners = Get-ListenerPids $BackendPort }
        $ours = $false
        foreach ($o in $owners) {
            $cmdline = Get-ProcessCommandLine $o
            if ($cmdline -like "*$($script:VenvPy)*") { $ours = $true; break }
        }
        if ($ours) {
            Add-Warning "port $BackendPort already owned by our isolated env (adopted)"
            $script:BackendPid = $owners[0]
            Complete-Step $step "PASS" "adopted our own listener on $BackendPort"
            return
        }
        Add-Failure "start_backend" "PORT_COLLISION" "port 127.0.0.1:$BackendPort occupied by foreign process(es): $($owners -join ', ')"
        Complete-Step $step "FAIL" "port $BackendPort in use by foreign process"
        return
    }
    if (-not $script:Mock) {
        $res = Invoke-Bounded -FilePath $script:VenvPy -ArgumentList @("-m", "uvicorn", "app.served:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--log-level", "info") -WorkingDirectory $script:PackageRoot -TimeoutSeconds 15 -Tag "backend" -Detached
        if ($res.SpawnError -or -not $res.Process) {
            Add-Failure "start_backend" "BACKEND_START_FAILURE" "backend process could not be spawned: $($res.StdErr)"
            Complete-Step $step "FAIL" "backend spawn failed"
            return
        }
        Register-RunnerProcess -processId $res.Process.Id -commandLine ("uvicorn app.served:app --port $BackendPort")
        $script:BackendPid = $res.Process.Id
        $script:BackendLogOut = $res.OutFile
        $script:BackendLogErr = $res.ErrFile
        Complete-Step $step "PASS" "backend spawned pid $($res.Process.Id) (isolated env)"
        return
    }
    $script:BackendPid = 424242  # mock-only placeholder pid
    $script:BackendLogOut = Join-Path $script:LogsDir "backend.out.log"
    $script:BackendLogErr = Join-Path $script:LogsDir "backend.err.log"
    Complete-Step $step "PASS" "backend started (mock)"
}

function Invoke-Phase08-BackendHealth {
    $step = New-Step 8 "backend_health"
    $healthy = Test-Mock "backend_healthy" $true
    if (-not $script:Mock) {
        $deadline = (Get-Date).AddSeconds($BackendReadyTimeoutSeconds)
        $healthy = $false
        while ((Get-Date) -lt $deadline) {
            $resp = Get-HttpResponse ("http://127.0.0.1:{0}/api/status" -f $BackendPort) 3
            if ($resp.ok -and $resp.status -eq 200 -and $resp.body -match '"ok"\s*:\s*true') {
                $healthy = $true
                break
            }
            Start-Sleep -Seconds 2
        }
    }
    if (-not $healthy) {
        $log = if ($script:BackendLogErr) { $script:BackendLogErr } else { "n/a" }
        Add-Failure "backend_health" "BACKEND_START_FAILURE" "backend did not answer /api/status healthy within ${BackendReadyTimeoutSeconds}s (log: $log)"
        Copy-ToReport $script:BackendLogErr
        Complete-Step $step "FAIL" "backend unhealthy after ${BackendReadyTimeoutSeconds}s"
        return
    }
    Complete-Step $step "PASS" ("/api/status healthy on 127.0.0.1:{0}" -f $BackendPort)
}

function Invoke-Phase09-DiscoverBridge {
    $step = New-Step 9 "discover_bridge"
    $reachable = Test-Mock "bridge_reachable" $true
    $pingOk = Test-Mock "bridge_ping_ok" $true
    $engine = ""
    if (-not $script:Mock) {
        $reachable = Test-TcpPort "127.0.0.1" $BridgePort 3
        $pingOk = $reachable
        if ($reachable) {
            # Real ping via the checker bridge probe (TCP + ping + engine).
            $res = Invoke-Checker -Args @("bridge", "--bridge-host", "127.0.0.1", "--bridge-port", "$BridgePort") -TimeoutSeconds 60 -Tag "bridge"
            $rep = Parse-JsonFile $res.OutFile
            if ($rep) {
                $script:BridgeReport = $rep
                $pingOk = [bool]$rep.ping_ok
                $engine = [string]$rep.engine
            }
        }
    } else {
        $script:BridgeReport = @{ tcp_ok = $true; ping_ok = $pingOk; engine = "5.8.0"; project_name = (Test-Mock "identity_project" "AividoHQ"); world_path = (Test-Mock "active_map" "/Game/Maps/AividoHQ") }
        $engine = "5.8.0"
    }
    if (-not $reachable -or -not $pingOk) {
        Add-Failure "discover_bridge" "BRIDGE_UNAVAILABLE" "Unreal bridge not reachable on 127.0.0.1:$BridgePort (is the editor open with Aivido bridge running?)"
        $script:BridgeDown = $true
        Complete-Step $step "FAIL" "bridge 127.0.0.1:$BridgePort unreachable"
        return
    }
    Complete-Step $step "PASS" ("bridge alive on 127.0.0.1:{0} engine={1}" -f $BridgePort, $engine)
}

function Invoke-Phase10-ProjectIdentity {
    $step = New-Step 10 "project_identity"
    if ($script:BridgeDown) {
        Complete-Step $step "SKIP" "bridge unavailable at step 9; root cause reported there"
        return
    }
    $project = ""
    if (-not $script:Mock) {
        if (-not $script:BridgeReport) {
            $res = Invoke-Checker -Args @("bridge", "--bridge-host", "127.0.0.1", "--bridge-port", "$BridgePort") -TimeoutSeconds 60 -Tag "identity"
            $rep = Parse-JsonFile $res.OutFile
            if ($rep) { $script:BridgeReport = $rep }
        }
        $project = [string]$script:BridgeReport.project_name
    } else {
        $project = [string](Test-Mock "identity_project" "AividoHQ")
    }
    if (-not $project) {
        Add-Failure "project_identity" "WRONG_UNREAL_PROJECT" "bridge did not report a project identity"
        Complete-Step $step "FAIL" "no project identity from bridge"
        return
    }
    if ($ExpectedProject -and $project.ToLower() -ne $ExpectedProject.ToLower()) {
        Add-Failure "project_identity" "WRONG_UNREAL_PROJECT" "editor project '$project' does not match expected '$ExpectedProject'"
        Complete-Step $step "FAIL" "project '$project' != expected '$ExpectedProject'"
        return
    }
    Complete-Step $step "PASS" "project=$project"
}

function Invoke-Phase11-ActiveMap {
    $step = New-Step 11 "active_map"
    if ($script:BridgeDown) {
        Complete-Step $step "SKIP" "bridge unavailable at step 9; root cause reported there"
        return
    }
    $worldPath = ""
    if (-not $script:Mock) {
        if (-not $script:BridgeReport) {
            $res = Invoke-Checker -Args @("bridge", "--bridge-host", "127.0.0.1", "--bridge-port", "$BridgePort") -TimeoutSeconds 60 -Tag "map"
            $rep = Parse-JsonFile $res.OutFile
            if ($rep) { $script:BridgeReport = $rep }
        }
        $worldPath = [string]$script:BridgeReport.world_path
    } else {
        $worldPath = [string](Test-Mock "active_map" "/Game/Maps/AividoHQ")
    }
    if ($worldPath -notlike "$ExpectedMap*") {
        Add-Failure "active_map" "WRONG_ACTIVE_MAP" "active map '$worldPath' does not start with expected '$ExpectedMap'"
        Complete-Step $step "FAIL" "map '$worldPath' != '$ExpectedMap'"
        return
    }
    Complete-Step $step "PASS" "map=$worldPath"
}

function Invoke-Phase12-UiHttp {
    $step = New-Step 12 "ui_http"
    $ok = Test-Mock "ui_ok" $true
    $status = 200
    $url = "http://127.0.0.1:$BackendPort/app"
    if (-not $script:Mock) {
        $resp = Get-HttpResponse $url 5
        $status = $resp.status
        $ok = ($resp.ok -and $resp.status -eq 200 -and ($resp.body -match "Aivido|aivido|Director"))
    }
    if (-not $ok) {
        Add-Failure "ui_http" "UI_UNAVAILABLE" "$url returned HTTP $status without the Aivido UI marker"
        Complete-Step $step "FAIL" "$url -> HTTP $status"
        return
    }
    Complete-Step $step "PASS" "$url -> HTTP 200 (UI marker present)"
}

function Invoke-Phase13-Doctor {
    $step = New-Step 13 "doctor"
    $doctorPath = Join-Path $script:PackageRoot "scripts\aivido_doctor.py"
    $workingDir = $script:PackageRoot
    if (-not (Test-Path $doctorPath)) {
        $doctorPath = Join-Path $script:RepoRoot "scripts\aivido_doctor.py"
        $workingDir = $script:RepoRoot
        Add-Warning "package has no scripts\aivido_doctor.py; using runner checkout doctor"
    }
    $doctorJsonPath = Join-Path $script:ReportDir "doctor.json"
    $exitCode = 0
    if ($script:Mock) {
        $ok = Test-Mock "doctor_ok" $true
        $script:DoctorJson = @{ overall = if ($ok) { "PASS" } else { "FAIL" }; summary = @{ pass = 13; warn = 0; fail = if ($ok) { 0 } else { 1 } }; checks = @() }
        $exitCode = if ($ok) { 0 } else { 1 }
        try { ($script:DoctorJson | ConvertTo-Json -Depth 6) | Set-Content $doctorJsonPath -Encoding UTF8 } catch {}
    } else {
        $res = Invoke-Bounded -FilePath $script:VenvPy -ArgumentList @($doctorPath, "--quick", "--json") -WorkingDirectory $workingDir -TimeoutSeconds 120 -Tag "doctor"
        $exitCode = $res.ExitCode
        try { $res.StdOut | Set-Content $doctorJsonPath -Encoding UTF8 } catch {}
        $script:DoctorJson = Parse-JsonFile $doctorJsonPath
        Copy-ToReport $res.ErrFile
    }
    if ($exitCode -ne 0 -or -not $script:DoctorJson) {
        Add-Failure "doctor" "DOCTOR_FAILURE" "doctor exited $exitCode with overall FAIL (report: $doctorJsonPath)"
        Complete-Step $step "FAIL" "doctor exit $exitCode"
        return
    }
    $overall = [string]$script:DoctorJson.overall
    $summary = $script:DoctorJson.summary
    $detail = "overall=$overall"
    if ($summary) { $detail += (" pass={0} warn={1} fail={2}" -f $summary.pass, $summary.warn, $summary.fail) }
    if ($overall -eq "WARN") { Add-Warning "doctor overall WARN" }
    Complete-Step $step "PASS" $detail
}

function Invoke-Phase14-RunMission {
    $step = New-Step 14 "mission"
    # Baseline evidence snapshot BEFORE the mission (for the stale check).
    $script:BaselineEvidenceSha = $null
    if (-not $script:Mock) {
        $res = Invoke-Checker -Args @("evidence", "--base-url", $script:BaseUrl) -TimeoutSeconds 60 -Tag "baseline"
        $rep = Parse-JsonFile $res.OutFile
        if ($rep -and $rep.overall -eq "PASS" -and $rep.detail.sha256) {
            $script:BaselineEvidenceSha = [string]$rep.detail.sha256
        }
    } elseif (-not (Test-Mock "baseline_evidence" $true)) {
        $script:BaselineEvidenceSha = $null
    } else {
        $script:BaselineEvidenceSha = "baseline-sha-placeholder"
    }

    $script:MissionStartedAt = Get-UnixTime
    if ($script:Mock) {
        if (Test-Mock "mission_times_out" $false) {
            $script:MissionTimedOut = $true
            Add-Failure "mission" "MISSION_TIMEOUT" "read-only mission exceeded the ${MissionTimeoutSeconds}s bound (mock)"
            Complete-Step $step "FAIL" "mission timed out"
            return
        }
        $ok = (Test-Mock "bridge_reachable" $true) -and (Test-Mock "mission_ok" $true)
        $script:MissionResult = @{
            overall = if ($ok) { "PASS" } else { "FAIL" }
            diag = if ((Test-Mock "bridge_reachable" $true)) { (Test-Mock "mission_diag" $null) } else { "BRIDGE_UNAVAILABLE" }
            mission_id = "second_system_mock"
            steps = @(@{ name = "bridge_tcp"; status = "PASS"; detail = "mock" }, @{ name = "viewport_capture"; status = if ($ok) { "PASS" } else { "FAIL" }; detail = "mock" })
            evidence = @{ path = (Join-Path $script:LogsDir "mock_evidence.png"); mtime = $script:MissionStartedAt; size = 2048; ok = $ok }
        }
        Complete-Step $step "PASS" "mission launched (mock)"
        return
    }

    $missionJson = Join-Path $script:RunDir "mission.json"
    $checker = Join-Path $script:RepoRoot "scripts\acceptance\second_system_checks.py"
    $args = @($checker, "mission", "--bridge-host", "127.0.0.1", "--bridge-port", "$BridgePort", "--expected-map", $ExpectedMap)
    if ($ExpectedProject) { $args += @("--expected-project", $ExpectedProject) }
    $argString = ConvertTo-ArgumentString $args
    try {
        $p = Start-Process -FilePath $script:VenvPy -ArgumentList $argString -WorkingDirectory $script:RepoRoot -WindowStyle Hidden -RedirectStandardOutput $missionJson -RedirectStandardError (Join-Path $script:RunDir "mission.err.log") -PassThru
        Register-RunnerProcess -processId $p.Id -commandLine ("second_system_checks.py mission")
    } catch {
        Add-Failure "mission" "MISSION_FAILURE" "mission could not be launched: $_"
        Complete-Step $step "FAIL" "mission launch failed"
        return
    }
    $finished = $p.WaitForExit($MissionTimeoutSeconds * 1000)
    if (-not $finished) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
        $script:MissionTimedOut = $true
        Add-Failure "mission" "MISSION_TIMEOUT" "read-only mission exceeded the ${MissionTimeoutSeconds}s bound"
        Complete-Step $step "FAIL" "mission timed out after ${MissionTimeoutSeconds}s"
        return
    }
    Complete-Step $step "PASS" "mission completed (exit $($p.ExitCode))"
}

function Invoke-Phase15-MissionResult {
    $step = New-Step 15 "mission_result"
    if ($script:MissionTimedOut) {
        Complete-Step $step "SKIP" "mission timed out at step 14; no terminal result produced"
        return
    }
    if ($script:Mock) {
        $bridgeOk = [bool](Test-Mock "bridge_reachable" $true)
        $ok = $bridgeOk -and [bool](Test-Mock "mission_ok" $true)
        $overall = if ($ok) { "PASS" } else { "FAIL" }
        $diag = if ($bridgeOk) { [string](Test-Mock "mission_diag" $null) } else { "BRIDGE_UNAVAILABLE" }
    } else {
        $missionJson = Join-Path $script:RunDir "mission.json"
        $rep = Parse-JsonFile $missionJson
        if (-not $rep) {
            Add-Failure "mission_result" "MISSION_FAILURE" "mission produced no terminal result JSON (log: $missionJson)"
            Complete-Step $step "FAIL" "no mission result"
            return
        }
        $script:MissionResult = $rep
        $overall = [string]$rep.overall
        $diag = [string]$rep.diag
    }
    if ($overall -ne "PASS") {
        # If the bridge was already reported down at step 9, the mission
        # failure is a cascade; do not double-report BRIDGE_UNAVAILABLE.
        if ($diag -like "BRIDGE_UNAVAILABLE*") {
            $already = $false
            foreach ($f in $script:Failures) { if ($f["stage"] -eq "discover_bridge") { $already = $true } }
            if (-not $already) {
                Add-Failure "mission_result" "BRIDGE_UNAVAILABLE" "mission could not reach the bridge: $diag"
            }
        } elseif ($diag -like "CAPTURE_FAILED*") {
            Add-Failure "mission_result" "SCREENSHOT_INVALID" "mission viewport capture failed: $diag"
        } else {
            Add-Failure "mission_result" "MISSION_FAILURE" "mission overall FAIL: $diag"
        }
        Complete-Step $step "FAIL" "mission overall=$overall diag=$diag"
        return
    }
    Complete-Step $step "PASS" ("mission_id={0} overall=PASS" -f $script:MissionResult.mission_id)
}

function Invoke-Phase16-EvidenceFresh {
    $step = New-Step 16 "evidence_fresh"
    $capturePath = ""
    $minMtime = 0
    if ($script:MissionResult -and $script:MissionResult.evidence) {
        $capturePath = [string]$script:MissionResult.evidence.path
        $minMtime = [double]$script:MissionResult.evidence.mtime
    }
    $ok = Test-Mock "evidence_ok" $true
    $diag = [string](Test-Mock "evidence_diag" $null)
    if (-not $script:Mock) {
        $args = @("evidence", "--base-url", $script:BaseUrl, "--max-age-minutes", "$EvidenceMaxAgeMinutes")
        if ($capturePath) { $args += @("--expected-path", $capturePath) }
        if ($minMtime -gt 0) { $args += @("--min-mtime", ("{0:F3}" -f $minMtime)) }
        $res = Invoke-Checker -Args $args -TimeoutSeconds 90 -Tag "evidence"
        $rep = Parse-JsonFile $res.OutFile
        if ($rep) {
            $script:PostEvidence = $rep
            $ok = ($rep.overall -eq "PASS")
            $diag = [string]$rep.diag
        } else {
            $ok = $false
            $diag = "EVIDENCE_MISSING"
        }
    } else {
        $script:PostEvidence = @{ overall = if ($ok) { "PASS" } else { "FAIL" }; diag = $diag; detail = @{ sha256 = if ($ok) { "post-sha-placeholder" } else { "bad-sha" }; bytes = 2048; path = $capturePath } }
    }
    if (-not $ok) {
        if ($diag -like "EVIDENCE_STALE*") {
            Add-Failure "evidence_fresh" "STALE_EVIDENCE" "served evidence is stale: $diag"
        } else {
            Add-Failure "evidence_fresh" "SCREENSHOT_INVALID" "evidence invalid or missing: $diag"
        }
        Complete-Step $step "FAIL" "evidence check failed ($diag)"
        return
    }
    Complete-Step $step "PASS" "fresh evidence validated (sha=$($script:PostEvidence.detail.sha256))"
}

function Invoke-Phase17-NoStaleEvidence {
    $step = New-Step 17 "no_stale_evidence"
    $postSha = ""
    if ($script:PostEvidence -and $script:PostEvidence.detail) { $postSha = [string]$script:PostEvidence.detail.sha256 }
    if ($script:BaselineEvidenceSha -and $postSha -and $script:BaselineEvidenceSha -eq $postSha) {
        Add-Failure "no_stale_evidence" "STALE_EVIDENCE" "evidence unchanged from the pre-mission baseline (served sha identical); capture did not refresh"
        Complete-Step $step "FAIL" "evidence sha identical to baseline"
        return
    }
    $note = "no pre-mission baseline"
    if ($script:BaselineEvidenceSha) { $note = "baseline superseded" }
    Complete-Step $step "PASS" $note
}

function Invoke-Phase18-Restart {
    $step = New-Step 18 "restart"
    $ok = Test-Mock "restart_ok" $true
    if (-not $script:Mock -and $script:BackendPid) {
        # Stop our own backend only (command line verified in cleanup).
        try { Stop-Process -Id $script:BackendPid -Force -ErrorAction SilentlyContinue } catch {}
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline -and (Test-TcpPort "127.0.0.1" $BackendPort)) { Start-Sleep -Milliseconds 500 }
        if (Test-TcpPort "127.0.0.1" $BackendPort) {
            Add-Failure "restart" "RESTART_FAILURE" "backend port $BackendPort still occupied after stopping our own backend"
            Complete-Step $step "FAIL" "port not released after stop"
            return
        }
        $res = Invoke-Bounded -FilePath $script:VenvPy -ArgumentList @("-m", "uvicorn", "app.served:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--log-level", "info") -WorkingDirectory $script:PackageRoot -TimeoutSeconds 15 -Tag "backend2" -Detached
        if (-not $res.Process) {
            Add-Failure "restart" "RESTART_FAILURE" "backend respawn failed: $($res.StdErr)"
            Complete-Step $step "FAIL" "respawn failed"
            return
        }
        Register-RunnerProcess -processId $res.Process.Id -commandLine ("uvicorn app.served:app --port $BackendPort")
        $script:BackendPid = $res.Process.Id
        $deadline = (Get-Date).AddSeconds($BackendReadyTimeoutSeconds)
        $ok = $false
        while ((Get-Date) -lt $deadline) {
            $resp = Get-HttpResponse ("http://127.0.0.1:{0}/api/status" -f $BackendPort) 3
            if ($resp.ok -and $resp.status -eq 200 -and $resp.body -match '"ok"\s*:\s*true') { $ok = $true; break }
            Start-Sleep -Seconds 2
        }
        if (-not $ok) {
            Add-Failure "restart" "RESTART_FAILURE" "backend not healthy after clean restart"
            Complete-Step $step "FAIL" "unhealthy after restart"
            return
        }
    }
    if (-not $ok) {
        Add-Failure "restart" "RESTART_FAILURE" "clean stop/start cycle failed"
        Complete-Step $step "FAIL" "restart cycle failed"
        return
    }
    Complete-Step $step "PASS" "clean stop/start cycle healthy"
}

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
function Build-Report {
    $report = @{
        runner          = "run_second_system_acceptance.ps1"
        runner_version  = $script:RunnerVersion
        run_id          = $script:RunId
        timestamp       = Get-UtcIso
        machine         = $env:COMPUTERNAME
        os              = $script:OsName
        package_path    = $script:PackageRoot
        package_version = $script:PackageVersion
        package_sha     = $script:PackageSha
        backend         = @{
            port    = $BackendPort
            healthy = @($script:Failures | Where-Object { $_.stage -eq "backend_health" }).Count -eq 0
            pid     = $script:BackendPid
            log_out = $script:BackendLogOut
            log_err = $script:BackendLogErr
        }
        bridge          = @{
            host      = "127.0.0.1"
            port      = $BridgePort
            reachable = @($script:Failures | Where-Object { $_.stage -eq "discover_bridge" }).Count -eq 0
            ping_ok   = @($script:Failures | Where-Object { $_.stage -eq "discover_bridge" }).Count -eq 0
            engine    = if ($script:BridgeReport) { [string]$script:BridgeReport.engine } else { "" }
        }
        unreal          = @{
            installed_builds = $script:UnrealBuilds
            detected_version = $script:UnrealVersion
            supported        = @($script:Failures | Where-Object { $_.code -in @("UNREAL_NOT_INSTALLED", "UNSUPPORTED_UNREAL_VERSION") }).Count -eq 0
            project          = if ($script:BridgeReport) { [string]$script:BridgeReport.project_name } else { "" }
            map              = if ($script:BridgeReport) { [string]$script:BridgeReport.world_path } else { "" }
        }
        ui              = @{
            url         = "http://127.0.0.1:$BackendPort/app"
            http_status = if ($script:Mock) { 200 } else { (Get-HttpResponse "http://127.0.0.1:$BackendPort/app" 3).status }
            ok          = @($script:Failures | Where-Object { $_.stage -eq "ui_http" }).Count -eq 0
        }
        doctor          = @{
            overall  = if ($script:DoctorJson) { [string]$script:DoctorJson.overall } else { "not_run" }
            summary  = if ($script:DoctorJson -and $script:DoctorJson.summary) { $script:DoctorJson.summary } else { $null }
            json_path = (Join-Path $script:ReportDir "doctor.json")
        }
        mission         = @{
            id         = if ($script:MissionResult) { [string]$script:MissionResult.mission_id } else { "" }
            result     = if ($script:MissionResult) { [string]$script:MissionResult.overall } else { "not_run" }
            diag       = if ($script:MissionResult) { [string]$script:MissionResult.diag } else { "" }
            steps      = if ($script:MissionResult -and $script:MissionResult.steps) { $script:MissionResult.steps } else { @() }
            evidence   = if ($script:MissionResult -and $script:MissionResult.evidence) { $script:MissionResult.evidence } else { $null }
        }
        evidence        = @{
            path       = if ($script:PostEvidence -and $script:PostEvidence.detail) { [string]$script:PostEvidence.detail.path } else { "" }
            bytes      = if ($script:PostEvidence -and $script:PostEvidence.detail) { $script:PostEvidence.detail.bytes } else { 0 }
            sha256     = if ($script:PostEvidence -and $script:PostEvidence.detail) { [string]$script:PostEvidence.detail.sha256 } else { "" }
            validated  = if ($script:PostEvidence) { $script:PostEvidence.overall -eq "PASS" } else { $false }
            age_minutes = if ($script:PostEvidence -and $script:PostEvidence.detail) { $script:PostEvidence.detail.age_minutes } else { $null }
        }
        restart         = @{
            ok     = @($script:Failures | Where-Object { $_.stage -eq "restart" }).Count -eq 0
            detail = if (($script:Steps | Where-Object { $_.number -eq 18 })) { (($script:Steps | Where-Object { $_.number -eq 18 })[0]).detail } else { "" }
        }
        duration_s      = [Math]::Round(((Get-Date) - $script:RunStarted).TotalSeconds, 1)
        warnings        = $script:Warnings
        failures        = $script:Failures
        steps           = $script:Steps
        final_verdict   = if ($script:Failures.Count -eq 0) { "PASS" } else { "FAIL" }
        mock            = $script:Mock
    }
    if ($script:CleanupResult) { $report.cleanup = $script:CleanupResult }
    return $report
}

function Write-ReportFile($report) {
    $outPath = $script:ReportFile
    try {
        if ($outPath) {
            $parent = Split-Path -Parent $outPath
            if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            ($report | ConvertTo-Json -Depth 12) | Set-Content $outPath -Encoding UTF8
        }
    } catch {
        Write-Host "  WARN: could not write report: $_" -ForegroundColor Yellow
    }
}

function Invoke-Phase19-EmitReport {
    $step = New-Step 19 "report"
    $report = Build-Report
    Write-ReportFile $report
    $verdict = $report.final_verdict
    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Magenta
    Write-Host " AIVIDO V2 SECOND-SYSTEM ACCEPTANCE $verdict" -ForegroundColor $(if ($verdict -eq "PASS") { "Green" } else { "Red" })
    Write-Host " run_id   : $($report.run_id)" -ForegroundColor Gray
    Write-Host " machine  : $($report.machine)" -ForegroundColor Gray
    Write-Host " package  : $($report.package_version) ($($report.package_sha.Substring(0, [Math]::Min(12, $report.package_sha.Length)))...)" -ForegroundColor Gray
    Write-Host " report   : $script:ReportFile" -ForegroundColor Gray
    Write-Host " steps    : $($report.steps.Count) run, $(@($report.steps | Where-Object { $_.status -eq 'FAIL' }).Count) failed" -ForegroundColor Gray
    if ($report.failures.Count -gt 0) {
        Write-Host " failures :" -ForegroundColor Red
        foreach ($f in $report.failures) {
            Write-Host ("   - {0} [{1}]: {2}" -f $f.stage, $f.code, $f.reason) -ForegroundColor Red
            Write-Host ("     fix: {0}" -f $f.remediation) -ForegroundColor DarkGray
        }
    }
    Complete-Step $step "PASS" ("acceptance JSON written to {0}" -f $script:ReportFile)
}

# ---------------------------------------------------------------------------
# Cleanup (only our own processes + temp dirs)
# ---------------------------------------------------------------------------
function Invoke-RunnerCleanup {
    $results = @{ stopped = @(); refused = @(); temp_dirs_removed = @(); logs_preserved = $true }
    # 1. Stop tracked processes — only after verifying the command line still
    #    matches what we launched (never kill a recycled/foreign PID).
    foreach ($rec in $script:Started) {
        $id = [int]$rec.Pid
        if (-not (Get-Process -Id $id -ErrorAction SilentlyContinue)) { continue }
        $cmdline = Get-ProcessCommandLine $id
        $ours = ($cmdline -like "*$($script:VenvPy)*") -or ($cmdline -like "*second_system_checks.py mission*") -or ($cmdline -like "*uvicorn app.served:app*")
        if (-not $ours) {
            $results.refused += "pid $id (command line no longer matches what we started)"
            Add-Warning "refusing to stop pid ${id}: command line does not match anything this runner started"
            continue
        }
        try {
            Stop-Process -Id $id -Force -ErrorAction Stop
            $results.stopped += $id
        } catch {
            $results.refused += "pid $id (could not stop: $_)"
            Add-Warning "could not stop tracked pid ${id}: $_"
        }
    }
    # 2. Temp dirs — remove unless -KeepLogs.
    foreach ($dir in $script:TempDirs) {
        if (Test-Path $dir) {
            if ($KeepLogs -or $SkipCleanup) {
                $results.temp_dirs_removed += "kept $dir"
            } else {
                try {
                    Remove-Item -Path $dir -Recurse -Force -ErrorAction Stop
                    $results.temp_dirs_removed += "removed $dir"
                } catch {
                    Add-Warning "could not remove temp dir ${dir}: $_"
                    $results.temp_dirs_removed += "retained $dir"
                }
            }
        }
    }
    $script:CleanupResult = $results
    return $results
}

function Invoke-Phase20-Cleanup {
    $step = New-Step 20 "cleanup"
    $results = Invoke-RunnerCleanup
    $stopped = $results.stopped -join ", "
    $detail = "stopped processes: $($results.stopped.Count); temp: $($results.temp_dirs_removed -join '; ')"
    if ($results.refused.Count -gt 0) {
        Add-Warning "cleanup refused: $($results.refused -join '; ')"
    }
    Complete-Step $step "PASS" $detail
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
function Main {
    param(
        [string]$PackagePath = "",
        [int]$BackendPort = 8765,
        [int]$BridgePort = 6766,
        [string]$BaseUrl = "",
        [string]$ExpectedProject = "",
        [string]$ExpectedMap = "/Game/Maps/AividoHQ",
        [string]$UnrealExePath = "",
        [string]$OutputPath = "",
        [int]$BackendReadyTimeoutSeconds = 120,
        [int]$MissionTimeoutSeconds = 180,
        [int]$PipTimeoutSeconds = 600,
        [int]$EvidenceMaxAgeMinutes = 60,
        [switch]$KeepLogs,
        [switch]$SkipCleanup,
        [switch]$Mock,
        [string]$MockScenario = "success"
    )

    $script:RunStarted = Get-Date
    Reset-RunnerState -mock ([bool]$Mock) -scenario $MockScenario
    $script:OsName = ""
    try { $script:OsName = [string](Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption } catch {}
    if (-not $script:OsName) { $script:OsName = [System.Environment]::OSVersion.VersionString }
    $script:RunnerVersion = "unknown"
    try {
        $gitOut = git -C $script:RepoRoot rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $gitOut) { $script:RunnerVersion = ([string]$gitOut).Trim() }
    } catch {}

    $script:BaseUrl = if ($BaseUrl) { $BaseUrl } else { "http://127.0.0.1:$BackendPort" }
    $script:ReportFile = if ($OutputPath) { $OutputPath } else { Join-Path $script:ReportDir "acceptance.json" }

    Write-Host "==============================================" -ForegroundColor Magenta
    Write-Host " AIVIDO V2 - SECOND-SYSTEM ACCEPTANCE" -ForegroundColor Magenta
    Write-Host " run id    : $script:RunId" -ForegroundColor Gray
    Write-Host " machine   : $env:COMPUTERNAME" -ForegroundColor Gray
    Write-Host " os        : $script:OsName" -ForegroundColor Gray
    Write-Host " package   : $PackagePath" -ForegroundColor Gray
    Write-Host " mock      : $script:Mock ($script:MockScenario)" -ForegroundColor Gray
    Write-Host "==============================================" -ForegroundColor Magenta

    # Argument validation (usage error).
    if (-not $PackagePath) {
        Add-Failure "argument_validation" "ARGUMENT_VALIDATION" "-PackagePath is required (path to the extracted Aivido V2 package)"
        $report = Build-Report
        Write-ReportFile $report
        Write-Host ""
        Write-Host "Usage: powershell -ExecutionPolicy Bypass -File scripts\acceptance\run_second_system_acceptance.ps1 -PackagePath `"C:\...\Aivido-V2`" [-ExpectedProject X] [-ExpectedMap /Game/Maps/AividoHQ] [-OutputPath C:\path\acceptance.json]" -ForegroundColor Yellow
        Write-Host "SECOND_SYSTEM_ACCEPTANCE FAIL" -ForegroundColor Red
        return 2
    }

    $exitCode = 0
    try {
        Invoke-Phase01-ValidatePackage
        # Package integrity is the gate: without a valid package nothing
        # downstream can run, and cascading failures would be noise.
        if ($script:Failures.Count -eq 0) {
        Invoke-Phase02-CreateEnv
        Invoke-Phase03-InstallDeps
        Invoke-Phase04-ValidateRuntime
        Invoke-Phase05-DetectUnreal
        Invoke-Phase06-VerifyUnrealVersion
        Invoke-Phase07-StartBackend
        Invoke-Phase08-BackendHealth
        Invoke-Phase09-DiscoverBridge
        Invoke-Phase10-ProjectIdentity
        Invoke-Phase11-ActiveMap
        Invoke-Phase12-UiHttp
        Invoke-Phase13-Doctor
        Invoke-Phase14-RunMission
        Invoke-Phase15-MissionResult
        Invoke-Phase16-EvidenceFresh
        Invoke-Phase17-NoStaleEvidence
        Invoke-Phase18-Restart
        }
    } catch {
        Add-Failure "runner" "INTERNAL_ERROR" "unexpected error during acceptance run: $_"
    }

    Invoke-Phase19-EmitReport
    if (-not $SkipCleanup) {
        Invoke-Phase20-Cleanup
        # Re-emit the report with cleanup results included.
        $finalReport = Build-Report
        Write-ReportFile $finalReport
    }

    if ($script:Failures.Count -gt 0) { $exitCode = 1 }
    if ($exitCode -eq 0) {
        Write-Host ""
        Write-Host "SECOND_SYSTEM_ACCEPTANCE PASS" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "SECOND_SYSTEM_ACCEPTANCE FAIL" -ForegroundColor Red
    }
    return $exitCode
}

# ---------------------------------------------------------------------------
# Entry point: auto-run only when executed as a script (not dot-sourced by
# the hermetic test harness).
# ---------------------------------------------------------------------------
if ($MyInvocation.CommandOrigin -eq 'Runspace' -or $MyInvocation.InvocationName -ne '.') {
    exit (Main @PSBoundParameters)
}