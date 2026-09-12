# AIVIDO Release Candidate 1 Acceptance Specification

## Overview

This document defines the acceptance criteria for AIVIDO Release Candidate 1 (RC1).
The RC1 gate is a **read-only** verification system that validates 18 release criteria
without mutating Unreal Editor state or runtime systems.

## Gate Execution

```bash
# Run full gate (machine-readable JSON to stdout + file)
python tools/rc1/aivido_rc1_gate.py --json-out /path/rc1_gate.json

# Generate human-readable report
python tools/rc1/aivido_rc1_report.py /path/rc1_gate.json --out /path/rc1_report.md

# Run single check for debugging
python tools/rc1/aivido_rc1_gate.py --check 3
```

**Exit codes:**
- `0` = All checks PASS (RC1 ready)
- `42` = One or more checks FAIL (RC1 blocked)
- `2` = Usage error

## 18 Acceptance Criteria

### 1. Repository / Release State (`REPO_RELEASE_STATE`)
**Verifies:** `AIVIDO_RELEASE_STATUS.md` exists and records all four stages graduated.
- Stage A: Graduated
- Stage B: Graduated
- Stage C: Graduated
- Stage D: Graduated

### 2. Backend Health Contract (`BACKEND_HEALTH`)
**Verifies:** Backend API at `127.0.0.1:8765/api/status` responds with:
- `"ok": true`
- `"unreal": {"ok": true}`

### 3. Unreal Bridge Health Contract (`BRIDGE_HEALTH`)
**Verifies:** Unreal bridge at `127.0.0.1:6766`:
- Accepts TCP connection
- Returns `{"ok": true, "message": "UNREAL_BRIDGE_READY", ...}`
- Provides identity payload (project, listener version, port)

### 4. Correct Expected Map Contract (`EXPECTED_MAP`)
**Verifies:** Live Unreal Editor is on `/Game/AIVIDO_Showcase` (or configured map).
- Read-only probe via bridge (never mutates scene)
- Uses `EditorActorSubsystem.get_all_level_actors()` (UE 5.7 API)
- Actor count must meet minimum threshold

### 5. Command Runtime Health (`COMMAND_RUNTIME`)
**Verifies:** `runtime/command_state.json` exists and worker is alive.
- State file is valid JSON
- Job counts reported
- No corruption detected

### 6. No Active Stuck Job (`NO_STUCK_JOB`)
**Verifies:** No job in `"running"` state for > 5 minutes.
- Stalled jobs are a graduation blocker
- Recovery marks restarted-run jobs as failed

### 7. One-Click Launcher Presence (`ONE_CLICK_LAUNCHER`)
**Verifies:** `scripts/avalive_gate.py` exists and is invokable.
- `avalive_gate.json` config present
- `status` command executes without crash
- Supports: `launch`, `status`, `return`, `chat`, `speak`

### 8. Evidence Packager Presence (`EVIDENCE_PACKAGER`)
**Verifies:** `scripts/aivido_evidence.py` exists and is invokable.
- Usage error (exit 2) when invoked without arguments
- Packs: fresh frame, SceneDiff, capture metadata, vision gate

### 9. Fresh-Evidence Requirements (`FRESH_EVIDENCE_REQUIREMENTS`)
**Verifies:** Evidence packager enforces fresh-frame contract:
- SHA256 + size match in `capture_metadata.json`
- `captured_at_epoch` within `--max-age` (default 900s)
- Map matches expected map
- Hand-placed PNGs rejected (no provenance = stale)

### 10. Empty SceneDiff Cannot Graduate (`EMPTY_SCENEDIFF_CANNOT_GRADUATE`)
**Verifies:** Both production pipeline and evidence packager reject empty SceneDiff:
- `core/production_v2.py`: `scene_diff_is_meaningful()` gate in `graduation_gates()`
- `scripts/aivido_evidence.py`: `EMPTY_SCENEDIFF` = FAIL
- SceneDiff tracks: actors added/removed/modified, transforms, assets, materials, lights, cameras

### 11. Executor Success Alone Cannot Graduate (`EXECUTOR_SUCCESS_ALONE_CANNOT_GRADUATE`)
**Verifies:** Executor success is **necessary but not sufficient** for PASS:
- `production_v2.py`: "executor success is NOT mission PASS" — only opens `execution_gate`
- `aivido_evidence.py`: "EXECUTOR SUCCESS ALONE IS NOT A PASS" — recorded as metadata only
- All graduation gates must pass: scene_diff, evidence, visual, contract, technical Unreal

### 12. Stale/Missing Screenshot Cannot Graduate (`STALE_MISSING_SCREENSHOT_CANNOT_GRADUATE`)
**Verifies:** Stale or missing screenshot blocks graduation:
- `aivido_evidence.py`: `check_frame_freshness()` — stale/missing = FAIL
- `production_v2.py`: `screenshot_fresh()` gate — captured after snapshot_after
- Wall-clock recency alone insufficient; must be provably post-execution capture

### 13. Actor Identity Regression Protections (`ACTOR_IDENTITY_REGRESSION`)
**Verifies:** Graduation gate audits mission brief against live actor labels:
- `tools/aivido_graduation_gate.py`: `audit_mission_labels()` scans for `AIVIDO_*` tokens
- Unknown tokens → `MISSION_LABEL_UNKNOWN` → gate FAIL
- `tests/test_actor_identity.py` exists for regression testing

### 14. Explicit Production Brief Path (`EXPLICIT_PRODUCTION_BRIEF`)
**Verifies:** Production missions can declare explicit brief/evidence path:
- `aivido_graduation_gate.py`: `--mission-file` argument
- `aivido_verified_mission.py`: `package_evidence()` assembles evidence directory
- Evidence dir contains: `FINAL.png`, `scenediff.json`, `capture_metadata.json`, `verdict.json`, `verdict.md`

### 15. Negated Instructions Cannot Trigger Forbidden Tools (`NEGATED_INSTRUCTIONS_PROTECTION`)
**Verifies:** Production lane classification rejects negated instructions:
- `production_v2.py`: `NEGATION_CUES` = ("no ", "not ", "don't ", "without ", ...)
- Any negation cue → `classify_lane()` returns `"production"` (never `"atomic"`)
- `atomic_fast_path_allowed()` returns `False` for negated cube commands
- Negative wording ("do not use cubes") can never trigger cube fast-path

### 16. Required Regression Suites Invokable (`REGRESSION_SUITES_INVOKABLE`)
**Verifies:** Key regression tests exist and pytest can collect them:
- `tests/test_actor_identity.py`
- `tests/test_aivido_evidence.py`
- `tests/test_production_v2.py`
- `tests/test_visual_acceptance.py`
- `tests/test_compile_stall_regression.py`

### 17. No Stale Windows/Shadow-PC Production Path (`NO_STALE_WINDOWS_PATH`)
**Verifies:** No hardcoded Windows/Shadow-PC paths in graduation-critical files:
- Checked: `aivido_graduation_gate.py`, `aivido_verified_mission.py`,
  `aivido_evidence.py`, `production_v2.py`
- Forbidden: `Shadow`, `C:\Users\Shadow`, `C:/Users/Shadow`,
  `AvaLive`, `avalive_uproject`, `unreal_editor_exe`
- Mac implementation is authoritative; Shadow history on archive branch only

### 18. Release Output Format (`RELEASE_OUTPUT_FORMAT`)
**Verifies:** Gates produce both machine-readable JSON and human report:
- `aivido_graduation_gate.py`: `--json-out` writes JSON; prints JSON to stdout
- `aivido_evidence.py`: writes `verdict.json` + `verdict.md` to evidence dir
- Both use `json.dumps()` with structured schemas

## Architecture Principles

### Read-Only by Default
- Gate **never** mutates Unreal scene, editor state, or runtime files
- All probes are read-only (bridge ping, scene enumeration, state file reads)
- No subprocess launches of Unreal/editor during validation

### Deterministic & Hermetic Tests
- Static analysis checks require no external services
- Runtime behavior tests mock all external dependencies (socket, HTTP, filesystem)
- Tests run in < 5 seconds total

### Low-Conflict Integration
- All new code in `tools/rc1/` and `tests/rc1/`
- No modifications to existing production logic
- Calls existing modules/contracts where appropriate
- Ready for cherry-pick to main

## Related Contracts

- `AIVIDO_UNREAL_GRADUATION_CONTRACT.md` — Graduation requirements
- `AIVIDO_RELEASE_STATUS.md` — Current release status
- `tools/aivido_graduation_gate.py` — One-click graduation gate
- `tools/aivido_verified_mission.py` — Verified mission runner
- `scripts/aivido_evidence.py` — Evidence packager
- `scripts/aivido_preflight.py` — Preflight checks
- `core/production_v2.py` — Production pipeline V2 (lane classification, SceneDiff, gates)

## Files Created

```
tools/rc1/
├── aivido_rc1_gate.py      # Main acceptance gate (18 checks)
└── aivido_rc1_report.py    # Human-readable report generator

tests/rc1/
└── test_rc1_gate.py        # Hermetic unit + static analysis tests

docs/
└── AIVIDO_RC1_ACCEPTANCE.md  # This document
```

## Running the Test Suite

```bash
# Run all RC1 tests
python -m pytest tests/rc1/test_rc1_gate.py -v

# Run with coverage
python -m pytest tests/rc1/test_rc1_gate.py --cov=tools.rc1 -v
```

## Integration Notes

The RC1 gate is designed for **independent verification** — it can run on any machine
with access to the repository and (optionally) live Unreal/bridge/backend.
The 10 static checks (1, 7-18) require only the repository.
The 8 runtime checks (2-6) require live services.

For CI/CD: run static checks on every PR; run full gate on release branches.