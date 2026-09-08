<#
run_second_system_tests.ps1 — hermetic tests for the second-system acceptance
runner. Runs entirely in this lane: no live Unreal, no real backend, no
network installs. It dot-sources the runner (functions only — the entry
guard prevents auto-run) and drives the mocked scenarios.

Covered:
  1. PowerShell syntax (AST parse) of the runner and this harness
  2. python syntax of scripts/acceptance/second_system_checks.py (when a
     system python is available)
  3. dot-source guard (no auto-run, functions exposed)
  4. argument validation (missing -PackagePath -> ARGUMENT_VALIDATION)
  5. mocked success path (exit 0, PASS verdict, 20 steps, JSON report)
  6. every mocked failure scenario -> correct failure code + stage
  7. package-integrity failure via a real incomplete package fixture
  8. JSON output schema conformance to the template
  9. cleanup logic (only processes it started are stopped; foreign
     processes untouched; recycled/dead pids skipped; temp dirs removed)
 10. port collision, missing dependency, missing Unreal behavior

Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\acceptance\tests\run_second_system_tests.ps1
#>
[CmdletBinding()]
param([string]$RunnerPath = "")

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Locate repo root + runner
# ---------------------------------------------------------------------------
$script:HarnessPath = $MyInvocation.MyCommand.Path

if (-not $RunnerPath) {
    $script:TestRoot = Split-Path -Parent $MyInvocation.MyCommand.Path   # tests/
    $script:RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $script:TestRoot))  # tests/ -> acceptance -> scripts -> repo
    $script:RunnerPath = Join-Path $script:RepoRoot "scripts\acceptance\run_second_system_acceptance.ps1"
} else {
    $script:RunnerPath = $RunnerPath
    $script:RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $RunnerPath))
}
$script:CheckerPath = Join-Path $script:RepoRoot "scripts\acceptance\second_system_checks.py"
$script:TemplatePath = Join-Path $script:RepoRoot "reports\templates\AIVIDO_SECOND_SYSTEM_ACCEPTANCE_TEMPLATE.json"

# ---------------------------------------------------------------------------
# Tiny assertion framework (no Pester dependency)
# ---------------------------------------------------------------------------
$script:Passed = 0
$script:Failed = 0
$script:TestFailures = @()

function Assert-True([bool]$cond, [string]$name, [string]$detail = "") {
    if ($cond) {
        $script:Passed++
        Write-Host ("  [PASS] {0}" -f $name) -ForegroundColor Green
    } else {
        $script:Failed++
        $script:TestFailures += ("{0} :: {1}" -f $name, $detail)
        Write-Host ("  [FAIL] {0} :: {1}" -f $name, $detail) -ForegroundColor Red
    }
}

function Test-Block([string]$name, [scriptblock]$body) {
    Write-Host ("`n== {0}" -f $name) -ForegroundColor Cyan
    try {
        & $body
    } catch {
        $script:Failed++
        $script:TestFailures += ("{0} :: EXCEPTION {1}" -f $name, $_.Exception.Message)
        Write-Host ("  [FAIL] {0} :: {1}" -f $name, $_.Exception.Message) -ForegroundColor Red
    }
}

# ---------------------------------------------------------------------------
# Fixture: a minimal Aivido V2 package
# ---------------------------------------------------------------------------
function New-TestPackage([string]$dir, [string[]]$missing = @()) {
    if (Test-Path $dir) { Remove-Item -Path $dir -Recurse -Force }
    New-Item -ItemType Directory -Path (Join-Path $dir "app") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dir "ui") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dir "scripts") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dir "core") -Force | Out-Null

    function Put-File([string]$rel, [string]$content) {
        if ($missing -contains $rel) { return }
        $target = Join-Path $dir $rel
        $parent = Split-Path -Parent $target
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Set-Content -Path $target -Value $content -Encoding ASCII
    }

    Put-File "requirements.txt" "fastapi`nuvicorn`npillow`nnumpy`npydantic`nrequests`nrich`n"
    Put-File "version.json" '{"version": "2.0.0-test", "branch": "aivido/v2-autonomous-qa", "sha": "6772f353f99625e9d257c626995ba772861f600d"}'
    Put-File "app\served.py" 'app = None'
    Put-File "app\__init__.py" ''
    Put-File "core\__init__.py" ''
    Put-File "ui\aivido.html" '<html><body>Aivido Director UI</body></html>'
    Put-File "install-aivido.ps1" '<# fixture #>'
    Put-File "start-aivido.ps1" '<# fixture #>'
    Put-File "scripts\aivido_doctor.py" 'import sys; sys.exit(0)'
    return $dir
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Read-Json([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    return (Get-Content $path -Raw | ConvertFrom-Json)
}

function Invoke-MockedMain([string]$scenario, [string]$package, [string]$outPath, [hashtable]$extra = @{}) {
    $rc = Main -PackagePath $package -Mock -MockScenario $scenario -OutputPath $outPath @extra
    return @{ exit = $rc; report = (Read-Json $outPath) }
}

# ---------------------------------------------------------------------------
# Dot-source the runner (entry guard prevents auto-run)
# ---------------------------------------------------------------------------
Write-Host "Loading runner (dot-source, no auto-run)..." -ForegroundColor Cyan
. $script:RunnerPath

# ---------------------------------------------------------------------------
# 1. PowerShell syntax
# ---------------------------------------------------------------------------
Test-Block "1. PowerShell syntax" {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($script:RunnerPath, [ref]$tokens, [ref]$errors) | Out-Null
    Assert-True ($errors -eq $null -or $errors.Count -eq 0) "runner parses without syntax errors" (($errors | ForEach-Object { $_.Message }) -join "; ")

    $tokens2 = $null
    $errors2 = $null
    [System.Management.Automation.Language.Parser]::ParseFile($script:HarnessPath, [ref]$tokens2, [ref]$errors2) | Out-Null
    Assert-True ($errors2 -eq $null -or $errors2.Count -eq 0) "test harness parses without syntax errors" (($errors2 | ForEach-Object { $_.Message }) -join "; ")
}

# ---------------------------------------------------------------------------
# 2. Python syntax of the checker
# ---------------------------------------------------------------------------
Test-Block "2. checker python syntax" {
    $py = $null
    foreach ($cand in @("py", "python")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { $py = $cand; break }
    }
    if (-not $py) {
        Assert-True $true "python syntax check skipped (no python on PATH)" "graceful skip"
    } else {
        $args = if ($py -eq "py") { @("-3", "-m", "py_compile", $script:CheckerPath) } else { @("-m", "py_compile", $script:CheckerPath) }
        $res = & $py @args 2>&1
        $rc = $LASTEXITCODE
        Assert-True ($rc -eq 0) "second_system_checks.py compiles" (($res | Out-String))
    }
}

# ---------------------------------------------------------------------------
# 3. Dot-source guard
# ---------------------------------------------------------------------------
Test-Block "3. dot-source guard" {
    Assert-True ((Get-Command Main -ErrorAction SilentlyContinue) -ne $null) "Main function exposed by dot-source"
    Assert-True (-not $script:RunStarted) "no auto-run happened during dot-source"
    Assert-True ((Get-Command Invoke-Phase01-ValidatePackage -ErrorAction SilentlyContinue) -ne $null) "phase functions exposed by dot-source"
    Assert-True ((Test-Path (Join-Path $script:RepoRoot "requirements.txt")) -and (Test-Path (Join-Path $script:RepoRoot "scripts\acceptance\second_system_checks.py"))) "RepoRoot resolves to the checkout root" "$script:RepoRoot"
    Assert-True ((Test-Path (Join-Path $script:RepoRoot "scripts\acceptance\second_system_checks.py"))) "checker path resolves inside repo" (Join-Path $script:RepoRoot "scripts\acceptance\second_system_checks.py")
}

# ---------------------------------------------------------------------------
# 4. Argument validation
# ---------------------------------------------------------------------------
Test-Block "4. argument validation (missing -PackagePath)" {
    $out = Join-Path $env:TEMP ("aivido-argtest-" + [Guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
    $rc = Main -PackagePath "" -OutputPath $out
    $report = Read-Json $out
    Assert-True ($rc -eq 2) "missing package path exits 2" "rc=$rc"
    Assert-True ($report -ne $null) "validation report written" "report missing"
    if ($report) {
        Assert-True ($report.final_verdict -eq "FAIL") "validation verdict FAIL" $report.final_verdict
        $f = $report.failures | Where-Object { $_.code -eq "ARGUMENT_VALIDATION" } | Select-Object -First 1
        Assert-True ($f -ne $null) "ARGUMENT_VALIDATION failure present"
        if ($f) {
            Assert-True ([bool]$f.stage -and [bool]$f.code -and [bool]$f.reason -and [bool]$f.remediation) "failure record has stage/code/reason/remediation"
        }
    }
    Remove-Item $out -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 5. Mocked success path
# ---------------------------------------------------------------------------
Test-Block "5. mocked success path" {
    $reportDir = Join-Path $env:TEMP ("aivido-ss-tests-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    $env:AIVIDO_ACCEPTANCE_REPORT_DIR = $reportDir
    $fixture = New-TestPackage (Join-Path $reportDir "package")
    $out = Join-Path $reportDir "success.json"
    $res = Invoke-MockedMain "success" $fixture $out
    Assert-True ($res.exit -eq 0) "success exits 0" "rc=$($res.exit)"
    $r = $res.report
    Assert-True ($r -ne $null) "success report exists"
    if ($r) {
        Assert-True ($r.final_verdict -eq "PASS") "verdict PASS" $r.final_verdict
        Assert-True ($r.failures.Count -eq 0) "no failures" ($r.failures | ConvertTo-Json -Compress)
        Assert-True ($r.steps.Count -eq 20) "20 steps recorded" "got $($r.steps.Count)"
        Assert-True (@($r.steps | Where-Object { $_.status -eq "FAIL" }).Count -eq 0) "no FAIL steps"
        Assert-True ([bool]$r.package_sha) "package checksum present" $r.package_sha
        Assert-True ($r.package_version -eq "2.0.0-test") "package version from version.json" $r.package_version
        Assert-True ($r.machine -and $r.os) "machine/os populated"
        Assert-True ($r.duration_s -ge 0) "duration populated" $r.duration_s
        Assert-True ($r.mission.result -eq "PASS") "mission result PASS"
        Assert-True ($r.evidence.validated) "evidence validated"
        Assert-True ($r.restart.ok) "restart ok"
        Assert-True ($r.backend.healthy) "backend healthy"
        Assert-True ($r.doctor.overall -eq "PASS") "doctor overall PASS"
        # cleanup ran and removed the temp run dir
        Assert-True ($r.cleanup -ne $null) "cleanup results recorded"
        Assert-True (-not (Test-Path (Join-Path $env:TEMP ("aivido-second-system-*")))) "no leftover runner temp dirs" "glob still matches"
    }
    Remove-Item $reportDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:AIVIDO_ACCEPTANCE_REPORT_DIR -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 6. All mocked failure scenarios
# ---------------------------------------------------------------------------
Test-Block "6. mocked failure scenarios" {
    $reportDir = Join-Path $env:TEMP ("aivido-ss-failtests-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    $env:AIVIDO_ACCEPTANCE_REPORT_DIR = $reportDir
    $fixture = New-TestPackage (Join-Path $reportDir "package")

    $scenarios = @(
        @{ s = "python-runtime-fail";    code = "PYTHON_RUNTIME_FAILURE";       stage = "validate_runtime" }
        @{ s = "dep-install-fail";       code = "DEPENDENCY_INSTALL_FAILURE";   stage = "install_dependencies" }
        @{ s = "unreal-missing";         code = "UNREAL_NOT_INSTALLED";         stage = "detect_unreal" }
        @{ s = "unsupported-version";    code = "UNSUPPORTED_UNREAL_VERSION";   stage = "verify_unreal_version" }
        @{ s = "port-collision";         code = "PORT_COLLISION";               stage = "start_backend" }
        @{ s = "backend-fail";           code = "BACKEND_START_FAILURE";        stage = "backend_health" }
        @{ s = "bridge-down";            code = "BRIDGE_UNAVAILABLE";           stage = "discover_bridge" }
        @{ s = "wrong-project";          code = "WRONG_UNREAL_PROJECT";         stage = "project_identity"; extra = @{ ExpectedProject = "AividoHQ" } }
        @{ s = "wrong-map";              code = "WRONG_ACTIVE_MAP";             stage = "active_map" }
        @{ s = "ui-down";                code = "UI_UNAVAILABLE";               stage = "ui_http" }
        @{ s = "doctor-fail";            code = "DOCTOR_FAILURE";               stage = "doctor" }
        @{ s = "mission-timeout";        code = "MISSION_TIMEOUT";              stage = "mission" }
        @{ s = "mission-fail";           code = "MISSION_FAILURE";              stage = "mission_result" }
        @{ s = "stale-evidence";         code = "STALE_EVIDENCE";               stage = "evidence_fresh" }
        @{ s = "screenshot-invalid";     code = "SCREENSHOT_INVALID";           stage = "evidence_fresh" }
        @{ s = "restart-fail";           code = "RESTART_FAILURE";              stage = "restart" }
    )

    foreach ($sc in $scenarios) {
        $out = Join-Path $reportDir ("fail_" + $sc.s + ".json")
        $extra = if ($sc.extra) { $sc.extra } else { @{} }
        $res = Invoke-MockedMain $sc.s $fixture $out $extra
        $r = $res.report
        $name = "scenario '{0}' -> {1}@{2}" -f $sc.s, $sc.code, $sc.stage
        if ($res.exit -ne 1) {
            Assert-True $false $name ("expected exit 1, got $($res.exit)")
            continue
        }
        if (-not $r) {
            Assert-True $false $name "no report JSON"
            continue
        }
        Assert-True ($r.final_verdict -eq "FAIL") $name ("verdict " + $r.final_verdict)
        $hit = $r.failures | Where-Object { $_.code -eq $sc.code -and $_.stage -eq $sc.stage } | Select-Object -First 1
        if ($hit) {
            Assert-True $true $name "matched"
            Assert-True ([bool]$hit.reason -and [bool]$hit.remediation) ("{0}: reason/remediation populated" -f $name)
        } else {
            Assert-True $false $name ("codes present: " + (($r.failures | ForEach-Object { $_.stage + ":" + $_.code }) -join ", "))
        }
        # Every failure record must carry the full contract fields.
        foreach ($f in $r.failures) {
            Assert-True ([bool]$f.stage -and [bool]$f.code -and [bool]$f.reason -and [bool]$f.remediation) ("failure record contract: {0}/{1}" -f $f.stage, $f.code)
        }
    }
    Remove-Item $reportDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:AIVIDO_ACCEPTANCE_REPORT_DIR -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 7. Package integrity failure (real incomplete fixture)
# ---------------------------------------------------------------------------
Test-Block "7. package integrity failure" {
    $reportDir = Join-Path $env:TEMP ("aivido-ss-pkgtest-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    $env:AIVIDO_ACCEPTANCE_REPORT_DIR = $reportDir
    $bad = New-TestPackage (Join-Path $reportDir "badpackage") @("requirements.txt", "version.json", "app\served.py")
    $out = Join-Path $reportDir "package_invalid.json"
    $res = Invoke-MockedMain "success" $bad $out   # phase 1 runs before any mock value is consulted
    $r = $res.report
    Assert-True ($res.exit -eq 1) "incomplete package exits 1" "rc=$($res.exit)"
    if ($r) {
        $hit = $r.failures | Where-Object { $_.code -eq "PACKAGE_INTEGRITY_FAILURE" -and $_.stage -eq "validate_package" } | Select-Object -First 1
        Assert-True ($hit -ne $null) "PACKAGE_INTEGRITY_FAILURE at validate_package" (($r.failures | ForEach-Object { $_.code }) -join ",")
        if ($hit) {
            Assert-True ($hit.reason -match "requirements.txt") "reason lists missing files" $hit.reason
        }
    }
    Remove-Item $reportDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:AIVIDO_ACCEPTANCE_REPORT_DIR -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 8. JSON output schema conformance
# ---------------------------------------------------------------------------
Test-Block "8. JSON output schema" {
    $reportDir = Join-Path $env:TEMP ("aivido-ss-schema-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    $env:AIVIDO_ACCEPTANCE_REPORT_DIR = $reportDir
    $fixture = New-TestPackage (Join-Path $reportDir "package")
    $out = Join-Path $reportDir "schema.json"
    $res = Invoke-MockedMain "success" $fixture $out
    $template = Read-Json $script:TemplatePath
    Assert-True ($template -ne $null) "template readable" $script:TemplatePath
    if ($template -and $res.report) {
        foreach ($key in $template.PSObject.Properties.Name) {
            if ($key -eq "_comment") { continue }
            Assert-True ($res.report.PSObject.Properties.Name -contains $key) "output has template key '$key'" "missing $key"
        }
        # Nested contract: failures entries, steps entries, backend/bridge/mission.
        foreach ($f in $res.report.failures) {
            Assert-True ($f.PSObject.Properties.Name -contains "stage" -and $f.PSObject.Properties.Name -contains "code" -and $f.PSObject.Properties.Name -contains "reason" -and $f.PSObject.Properties.Name -contains "remediation") "failure record schema"
        }
        foreach ($s in $res.report.steps) {
            Assert-True ($s.PSObject.Properties.Name -contains "number" -and $s.PSObject.Properties.Name -contains "name" -and $s.PSObject.Properties.Name -contains "status") "step record schema"
        }
        Assert-True ($res.report.mission.PSObject.Properties.Name -contains "id") "mission.id present"
        Assert-True ($res.report.evidence.PSObject.Properties.Name -contains "validated") "evidence.validated present"
        Assert-True ($res.report.backend.PSObject.Properties.Name -contains "port") "backend.port present"
    }
    Remove-Item $reportDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:AIVIDO_ACCEPTANCE_REPORT_DIR -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 9. Cleanup logic (real processes, hermetic)
# ---------------------------------------------------------------------------
Test-Block "9. cleanup logic" {
    $sandbox = Join-Path $env:TEMP ("aivido-ss-cleanup-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
    $fakeVenvPy = Join-Path $sandbox "env\.venv\Scripts\python.exe"
    New-Item -ItemType Directory -Path (Split-Path -Parent $fakeVenvPy) -Force | Out-Null
    Set-Content -Path $fakeVenvPy -Value "Start-Sleep -Seconds 120" -Encoding ASCII
    $script:VenvPy = $fakeVenvPy

    # A) Tracked process: its command line embeds our isolated venv path, so
    #    cleanup must recognize and stop it.
    $tracked = Start-Process powershell -ArgumentList @("-NoProfile", "-Command", "& '$fakeVenvPy'") -PassThru -WindowStyle Hidden
    Register-RunnerProcess -processId $tracked.Id -commandLine ("& $fakeVenvPy")

    # B) Foreign process: never registered, must survive cleanup untouched.
    $foreign = Start-Process powershell -ArgumentList @("-NoProfile", "-Command", "Start-Sleep 120") -PassThru -WindowStyle Hidden

    # C) Recycled/dead pid: nothing to stop, must not crash.
    Register-RunnerProcess -processId 999999 -commandLine "dead pid"

    # D) Temp dir: must be removed unless -KeepLogs.
    $tempDir = Join-Path $sandbox "tempdir"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $script:TempDirs = @($tempDir)

    try {
        $results = Invoke-RunnerCleanup
        # Tracked process should be gone.
        Start-Sleep -Milliseconds 500
        Assert-True (-not (Get-Process -Id $tracked.Id -ErrorAction SilentlyContinue)) "tracked process stopped by cleanup"
        # Foreign process untouched.
        Assert-True ([bool](Get-Process -Id $foreign.Id -ErrorAction SilentlyContinue)) "foreign process untouched"
        # Temp dir removed.
        Assert-True (-not (Test-Path $tempDir)) "temp dir removed"
        # Stopped list contains tracked pid only.
        Assert-True ($results.stopped -contains $tracked.Id) "stopped list records tracked pid"
        Assert-True (-not ($results.stopped -contains $foreign.Id)) "foreign pid not in stopped list"
    } finally {
        Stop-Process -Id $foreign.Id -Force -ErrorAction SilentlyContinue
        Remove-Item $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# 10. Port collision / missing dependency / missing Unreal behavior
# ---------------------------------------------------------------------------
Test-Block "10. port collision, missing dependency, missing Unreal" {
    $reportDir = Join-Path $env:TEMP ("aivido-ss-behav-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    $env:AIVIDO_ACCEPTANCE_REPORT_DIR = $reportDir
    $fixture = New-TestPackage (Join-Path $reportDir "package")

    $pc = Invoke-MockedMain "port-collision" $fixture (Join-Path $reportDir "pc.json")
    $pcHit = @($pc.report.failures | Where-Object { $_.code -eq "PORT_COLLISION" }) | Select-Object -First 1
    Assert-True ($pcHit -ne $null -and $pcHit.remediation -match "8765") "port collision remediation mentions the port"

    $md = Invoke-MockedMain "dep-install-fail" $fixture (Join-Path $reportDir "md.json")
    $mdFails = @($md.report.failures | Where-Object { $_.code -eq "DEPENDENCY_INSTALL_FAILURE" })
    Assert-True ($mdFails.Count -gt 0) "missing dependency -> DEPENDENCY_INSTALL_FAILURE"

    $mu = Invoke-MockedMain "unreal-missing" $fixture (Join-Path $reportDir "mu.json")
    $muHit = @($mu.report.failures | Where-Object { $_.code -eq "UNREAL_NOT_INSTALLED" }) | Select-Object -First 1
    Assert-True ($muHit -ne $null -and $muHit.remediation -match "Epic Games Launcher") "missing unreal remediation suggests Epic Games Launcher"

    # Bridge-down cascades must not double-report: discover_bridge is the
    # single BRIDGE_UNAVAILABLE failure; identity/map steps are SKIP.
    $bd = Invoke-MockedMain "bridge-down" $fixture (Join-Path $reportDir "bd.json")
    $bridgeFails = @($bd.report.failures | Where-Object { $_.code -eq "BRIDGE_UNAVAILABLE" })
    Assert-True ($bridgeFails.Count -eq 1) "bridge-down reports BRIDGE_UNAVAILABLE exactly once" "count=$($bridgeFails.Count)"
    $skips = @($bd.report.steps | Where-Object { $_.status -eq "SKIP" })
    Assert-True ($skips.Count -ge 2) "bridge-down skips identity/map steps" "skips=$($skips.Count)"

    Remove-Item $reportDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:AIVIDO_ACCEPTANCE_REPORT_DIR -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==============================================" -ForegroundColor Magenta
Write-Host " SECOND-SYSTEM RUNNER TESTS: $($script:Passed) passed, $($script:Failed) failed" -ForegroundColor $(if ($script:Failed -eq 0) { "Green" } else { "Red" })
Write-Host "==============================================" -ForegroundColor Magenta
if ($script:Failed -gt 0) {
    Write-Host "Failures:" -ForegroundColor Red
    foreach ($f in $script:TestFailures) { Write-Host "  - $f" -ForegroundColor Red }
}
exit $script:Failed