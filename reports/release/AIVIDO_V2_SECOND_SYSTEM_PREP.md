# AIVIDO V2 — SECOND-SYSTEM PREPARATION HANDOFF

Prepared in the isolated lane **`aivido/v2-second-system-prep`** (worktree
`.worktrees/v2-second-system-prep`), sourced from
`aivido/v2-autonomous-qa` @ `6772f353f99625e9d257c626995ba772861f600d`.

This lane builds a professional **one-command installation + acceptance
system** for running Aivido V2 on a completely different Windows machine.
Nothing in the root checkout, `aivido/v2-release`, the live release
acceptance run, `main`, or the live Unreal editor was touched.

---

## 1. What was built

| Artifact | Purpose |
|---|---|
| `scripts/acceptance/run_second_system_acceptance.ps1` | The 20-step one-command acceptance runner (PowerShell 5.1). Validates the package, creates an isolated runtime env, installs declared dependencies, detects/verifies Unreal, starts the backend, verifies health/bridge/project/map/UI, runs the doctor, runs ONE read-only mission, validates fresh screenshot evidence + no stale evidence, tests a clean restart, emits machine-readable acceptance JSON, and shuts down only the processes it started. |
| `scripts/acceptance/second_system_checks.py` | Python-side hermetic/read-only checks (`env`, `bridge`, `mission`, `evidence`) invoked as plain native commands by the runner. The mission never spawns actors and never saves the level — it writes only the transient proof PNG. |
| `reports/templates/AIVIDO_SECOND_SYSTEM_ACCEPTANCE_TEMPLATE.json` | The acceptance JSON output contract (template). |
| `scripts/acceptance/tests/run_second_system_tests.ps1` | Hermetic test harness (no Pester dependency): syntax, argument validation, mocked success + every failure scenario, JSON schema conformance, cleanup logic, port-collision / missing-dependency / missing-Unreal behavior. |
| `docs/SECOND_SYSTEM_INSTALL.md` | Full install guide for a new machine/user. |
| `reports/release/AIVIDO_V2_SECOND_SYSTEM_PREP.md` | This handoff. |

## 2. Command to run on the second machine

From this checkout on the second machine (after extracting the package):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\acceptance\run_second_system_acceptance.ps1 `
    -PackagePath "C:\Aivido\Aivido-V2"
```

Typical pinned run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\acceptance\run_second_system_acceptance.ps1 `
    -PackagePath "C:\Aivido\Aivido-V2" `
    -ExpectedProject "AividoHQ" `
    -ExpectedMap "/Game/Maps/AividoHQ" `
    -OutputPath "C:\Aivido\acceptance.json"
```

## 3. Prerequisites (second machine)

- Windows 10/11 64-bit with Windows PowerShell 5.1.
- Python 3.9+ on PATH (used only to create the isolated environment).
- Unreal Engine 5.x installed via the Epic Games Launcher (registry-detectable),
  or pass `-UnrealExePath` explicitly.
- The AividoHQ project open in Unreal Editor 5.x with the bridge listening on
  `127.0.0.1:6766` (`UA_BRIDGE_PORT` overrides supported).
- Internet access during the run (pip installs `requirements.txt`).
- Port `8765` free (the certified backend port; collision ⇒ `PORT_COLLISION`).

## 4. The 20 steps

`validate_package` → `create_env` → `install_dependencies` →
`validate_runtime` → `detect_unreal` → `verify_unreal_version` →
`start_backend` → `backend_health` → `discover_bridge` →
`project_identity` → `active_map` → `ui_http` → `doctor` → `mission` →
`mission_result` → `evidence_fresh` → `no_stale_evidence` → `restart` →
`report` → `cleanup`.

## 5. Failure classification

Every failure record carries **stage, code, reason, remediation**. Codes:
`UNREAL_NOT_INSTALLED`, `UNSUPPORTED_UNREAL_VERSION`,
`PYTHON_RUNTIME_FAILURE`, `DEPENDENCY_INSTALL_FAILURE`, `PORT_COLLISION`,
`BACKEND_START_FAILURE`, `BRIDGE_UNAVAILABLE`, `WRONG_UNREAL_PROJECT`,
`WRONG_ACTIVE_MAP`, `UI_UNAVAILABLE`, `DOCTOR_FAILURE`, `MISSION_TIMEOUT`,
`MISSION_FAILURE`, `STALE_EVIDENCE`, `SCREENSHOT_INVALID`,
`RESTART_FAILURE`, `PACKAGE_INTEGRITY_FAILURE` (plus
`ARGUMENT_VALIDATION`/`INTERNAL_ERROR` for runner-level guards).

## 6. Safety properties (enforced)

- No git commands that mutate anything (no reset/clean/checkout).
- Only the runner's own temp dirs and processes are cleaned; every process
  kill is preceded by a command-line identity check (a recycled/foreign PID
  is never killed).
- The read-only mission writes only `Saved/UnrealAgent/viewport_latest.png`
  (transient proof) — no actor spawns, no level save, no AividoHQ mutation.
- Backend port 8765 is fixed by the certified product; an occupied port is
  reported as `PORT_COLLISION` instead of silently moving the product.
- Logs are preserved on failure in `reports\second_system\<run_id>\`.

## 7. Known limitations

- The backend port (8765) is not relocatable — this is the certified product
  contract. Alternate ports are honored for the bridge (`-BridgePort`,
  `UA_BRIDGE_PORT`).
- The runner expects a package with `requirements.txt`, `version.json`,
  `app/served.py`, `ui/` resources, and at least one launcher
  (`install-aivido.ps1` / `install-aivido.cmd` / `start-aivido.ps1` /
  `product_launcher.py`) — i.e. the `scripts/build_v1_package.py` layout.
  A product-shell-only package (`product_launcher.py` without `app/served.py`)
  is rejected by `PACKAGE_INTEGRITY_FAILURE` (documented in
  `docs/SECOND_SYSTEM_INSTALL.md`).
- The mission requires the editor viewport to be visible; minimized/occluded
  editors produce `SCREENSHOT_INVALID`/`STALE_EVIDENCE` by design.
- The doctor step prefers the package's `scripts/aivido_doctor.py` and falls
  back to this checkout's doctor.

## 8. Tests

Run (hermetic, no live Unreal):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\acceptance\tests\run_second_system_tests.ps1
```

Coverage (155 assertions): PowerShell syntax (AST parse), checker python
compile, dot-source guard, argument validation, mocked success path,
all 17 failure scenarios (mock), package-integrity failure (real fixture),
JSON output schema conformance to the template, cleanup logic against real
tracked/foreign processes, port collision, missing dependency, missing
Unreal, and bridge-down cascade dedupe.

**Current result: 155 passed, 0 failed.**

## 9. Exact expected output

Success (mock-verified; identical shape on a real machine):

```
==============================================
 AIVIDO V2 SECOND-SYSTEM ACCEPTANCE PASS
 run_id   : run_20260907-...
 machine  : <HOSTNAME>
 package  : <version> (<checksum prefix>...)
 report   : <OutputPath or reports\second_system\<run_id>\acceptance.json>
 steps    : 20 run, 0 failed
  [OK  ] 01 validate_package: files OK; version=...; checksum=...
  ... (steps 02-18 PASS)
  [OK  ] 19 report: acceptance JSON written to ...
  [OK  ] 20 cleanup: stopped processes: 0; temp: removed ...
SECOND_SYSTEM_ACCEPTANCE PASS
```

Failure prints each failure with its remediation and exits 1:

```
SECOND_SYSTEM_ACCEPTANCE FAIL
 failures :
   - detect_unreal [UNREAL_NOT_INSTALLED]: no Unreal Engine build found ...
     fix: Install Unreal Engine 5.x through the Epic Games Launcher ...
```

Exit codes: `0` PASS · `1` FAIL · `2` usage/argument error.

## 10. Verification on this lane

- Reference SHA `6772f35` confirmed at lane creation; doctor base SHA
  (`736042d`) is an ancestor of this lane.
- Runner + checker + tests all pass the hermetic suite (155/155).
- CLI entry point (auto-run guard) exercised with a mocked success run and a
  package-integrity run; the emitted JSON matches the template key-for-key.
- No live Unreal connection, no backend start, no process outside the test
  sandbox was touched during testing.