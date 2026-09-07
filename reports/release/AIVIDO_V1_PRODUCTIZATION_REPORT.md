# AIVIDO V1 — PRODUCTIZATION REPORT

**Product:** Aivido V1 (Unreal Agent — one-click installer + persistent runtime + remote access)
**Branch:** `aivido/v1-productization`
**Base:** `aivido/rc1.1-clean-install-fixes` @ `736042ddafb45f34dfed88607e750be73e2877f2` (RC1.1 verified base)
**Date:** 2026-09-07

---

## 1. What was shipped

| P | Deliverable | Result |
|---|-------------|--------|
| P1 | One-click Windows installer/bootstrap | **PASS** |
| P2 | Persistent backend runtime (start/stop/restart/status, watchdog, PID/state, duplicate protection) | **PASS** |
| P3 | Local + optional Tailscale-only remote access | **PASS** |
| P4 | Real UI launch (`http://127.0.0.1:8765/app`) | **PASS** |
| P5 | V1 doctor / self-test (13 checks) | **PASS** |
| P6 | Real bounded Unreal smoke mission (`AIVIDO_V1_INSTALL_SMOKE`) | **PASS** |
| P7 | `dist/Aivido-V1/` distributable package | **PASS** |
| P8 | Report + scorecard | **PASS** |

**V1_INSTALLABLE: YES**

---

## 2. New runtime surface (this branch)

Root-level entry points (also mirrored into `dist/Aivido-V1/`):

- `install-aivido.ps1` / `install-aivido.cmd` — one-click idempotent installer
  (checks Python, creates `.venv`, installs `requirements.txt` only when
  needed, validates imports, detects Unreal Editor + project, starts the
  persistent backend, opens the UI). A second run reuses everything.
- `start-aivido.ps1` / `start-aivido.cmd` — control launcher:
  `start | stop | restart | status | ui | logs | doctor | smoke | remote`.
- `stop-aivido.cmd` — stop wrapper.
- `scripts/aivido_runtime.py` — persistent runtime manager.
- `scripts/aivido_watchdog.py` — detached crash watchdog (bounded restart).
- `scripts/aivido_doctor.py` — V1 self-test.
- `scripts/aivido_smoke.py` — bounded Unreal smoke mission.
- `scripts/aivido_install_check.py` — python-side installer checks
  (imports / editor / project); keeps the PowerShell 5.1 installer free of
  fragile inline here-strings.
- `scripts/build_v1_package.py` — assembles `dist/Aivido-V1/`.
- `tests/test_aivido_productization.py` — 11 hermetic tests for the new surface.

No changes were made to the Unreal core, the AividoHQ scene content, or the
`app.served` API surface (only new additive scripts/launchers + the existing
runtime modules are used).

---

## 3. Installer (P1)

**PowerShell 5.1 parse: PASS** (verified with
`[System.Management.Automation.Language.Parser]::ParseFile` — 0 errors on
both `install-aivido.ps1` and `start-aivido.ps1`; ASCII-only + UTF-8 BOM so
Windows PowerShell 5.1 cannot mangle non-ASCII bytes into quote characters).

**Fresh install in `dist/Aivido-V1` (no `.venv`): PASS**
- `1/8 Python`: Python 3.13 via `py`
- `2/8`: `.venv` created
- `3/8`: `requirements.txt` installed
- `4/8`: import contract OK (fastapi, uvicorn, PIL, numpy, pydantic,
  requests, rich)
- `5/8`: Unreal Editor — WARN (no Epic build registry entries on this host;
  the live editor on bridge 6766 supplies identity — non-fatal by design)
- `6/8`: project detected and pinned
  (`assetlib/tests/ue/ASSET_P1_Smoke/ASSET_P1_Smoke.uproject`)
- `7/8`: persistent backend started — RUNNING pid, `http://127.0.0.1:8765`
- `8/8`: UI reported; installer exit code 0

**Idempotent second run: PASS** — `.venv` reused, dependency probe passed
(no reinstall), backend reported "already running; reused" (single
instance), exit 0.

---

## 4. Persistent backend (P2)

Runtime facts verified live on this machine (127.0.0.1:8765):

- **start / status / stop / restart**: clean cycles; after each cycle exactly
  one loopback listener on 8765; no zombie duplicates.
- **Duplicate-start protection**: a second `start` while running reuses the
  live instance and never spawns a second listener. A *foreign* owner on
  8765 is refused with a clear error (never killed).
- **Orphan adoption**: a healthy backend running our exact command from the
  same checkout but with a stale/absent pid file is adopted, not duplicated.
- **PID/state tracking**: `config/runtime/aivido_v1.pid` + `aivido_v1.json`
  (state, pid, spawn root, watchdog pid, started_at, restarts, events,
  error, log paths).
- **Logs retained**: `config/logs/aivido_v1.out.log` / `.err.log` /
  `.watchdog.log`.
- **Crash detection / bounded restart**: killing the backend was detected by
  the detached watchdog, which restarted it (`restarts: 1`, new pid, healthy)
  without killing the watchdog.
- **FAIL visibility**: if the backend dies and cannot be recovered, `status`
  prints `state FAIL` + the error + the exact log path and exits non-zero.
- **Never touches the bridge/gateway**: bridge 6766 (UnrealEditor) and MCP
  gateway 8844 stayed alive and untouched through every cycle.

**Terminal-close / launcher-exit survival: PASS**
- The backend is spawned detached (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
  | CREATE_NO_WINDOW`) and survives its launcher process exiting.
- Verified across multiple independent process/invocation boundaries: the
  launcher (PowerShell → runtime `start`) returned/exited and the backend
  remained healthy with its watchdog alive. Also verified from the packaged
  install: the installer-exited backend (pid 18320) and later the
  doctor-spawned backend (pid 8636) remained RUNNING across later tool
  invocations.
- Note: some sandboxed shells kill descendant process trees on exit; the
  product spawn survives real desktop launches (Explorer/PowerShell), which
  was demonstrated when a backend launched through Explorer persisted
  independently of any agent session.

---

## 5. Local + Tailscale remote access (P3)

- Local default remains secure: backend binds `127.0.0.1:8765`.
- Tailscale detected: state `up`, IPv4 `100.84.156.24`,
  DNS `shadow-6kckcfdq.tail5f3ac6.ts.net`.
- Exposure uses **Tailscale-only** `tailscale serve` (TLS, tailnet-only; no
  public-interface binding, no firewall change, no admin rights).
- Remote URL reported: **`https://shadow-6kckcfdq.tail5f3ac6.ts.net`**
  (UI: `/app`). Remote health probe `GET .../api/status` -> HTTP 200.
- Local `http://127.0.0.1:8765/app` kept working throughout; a remote
  failure cannot break local Aivido (remote state is advisory only).
- Pre-existing, unrelated: Windows `svchost` (PID 3660) already held
  portproxy listeners on the Tailscale IPv4 for 6766/8765 before this work.
  V1 neither created nor kills those; it uses `tailscale serve` instead.

---

## 6. UI launch (P4)

Live browser verification of `http://127.0.0.1:8765/app` (Director's Booth):

- Status badges rendered: **engine linked**, **bridge ready**,
  **map AividoHQ**, **proof fresh**, no execution.
- Mission dispatch lane present ("START A MISSION", "ENTER THE AGENT ROOM").
- Console: zero JS errors. All network requests returned 200
  (`/api/status`, `/api/unreal-coder/session`, `/api/proof/status`,
  `/api/proof/latest`, `/api/workboard/state`, `/api/multiclient/status`,
  `/api/code/tasks`, `/api/workspace`, `/api/action`).
- Backend endpoints: `/api/unreal-coder/doctor` overall PASS;
  `/api/unreal-coder/session` created against ASSET_Showcase2.

---

## 7. Bridge / Unreal session

- Bridge 6766 ping: `UNREAL_BRIDGE_READY`, engine
  `5.8.2-56702186+++UE5+Release-5.8`.
- Session identity: `ASSET_Showcase2.uproject`.
- Active map: `/Game/Maps/AividoHQ.AividoHQ` (AividoHQ).
- Bridge PID 2220 (UnrealEditor) untouched by all runtime cycles.

---

## 8. Real bounded smoke mission (P6)

`scripts/aivido_smoke.py` executed ONE real mission on the live editor
through bridge 6766. All 14 steps PASS:

1. `session_identity` — ASSET_Showcase2, UE 5.8.2
2. `active_map` — /Game/Maps/AividoHQ
3. `actor_absent_before` — not present
4. `baseline_captured` — 166 actors
5. `spawn_point_in_view` — cube target computed 400 units in front of camera
6. `spawn_cube` — StaticMeshActor `AIVIDO_V1_INSTALL_SMOKE`, mesh loaded
7. `actor_exists` — StaticMeshActor verified
8. `viewport_aimed` — camera aimed at the cube (MathLibrary look-at)
9. `viewport_capture` — real native capture, 1,226,745 bytes
10. `proof_saved` — evidence PNG copied
11. `only_smoke_actor_added` — exactly our actor appeared
12. `actor_deleted` — only the disposable actor destroyed
13. `actor_absent_after` — verified gone
14. `level_restored` — 166 actors == baseline; **no save performed**
    (certified scene content untouched on disk)

**Proof:** `reports/release/AIVIDO_V1_SMOKE_EVIDENCE/AIVIDO_V1_INSTALL_SMOKE_proof.png`
(+ `mission.json`). Visual inspection of the proof confirms a large white
cube centered in the AividoHQ viewport with a ground shadow.

**Cleanup:** verified — actor removed, actor list back to baseline, level
not saved. Truly a bounded disposable smoke.

---

## 9. Self-test (P5)

Full doctor run against the packaged runtime (`dist/Aivido-V1`):
**overall PASS — 13 pass / 0 warn / 0 fail**:

release_sha (base ancestor), python_runtime (3.13 venv), requirements/imports,
backend_health (`/api/status` 200, unreal ok), ui_http (`/app` 200),
bridge_health (6766 ping), unreal_identity (ASSET_Showcase2),
active_map (AividoHQ), proof_endpoint (fresh capture present),
duplicate_start (single listener), stop_start_cycle (stop released port,
start healthy), persistence (launcher exited rc=0, backend pid still
healthy), foreign_protection (bridge + gateway untouched and alive).

Doctor works both in a git checkout (HEAD/base check) and in the shipped
package (no `.git` -> validates against `version.json`).

---

## 10. Tests

- Full safe suite on the productization branch: **1062 passed / 1 skipped /
  0 failed** (RC1.1 baseline 1051 + 11 new hermetic V1 tests).
- All tests hermetic (no live Unreal/ports/backend required).

---

## 11. Packaging (P7) and QA

`dist/Aivido-V1/` (2.5 MB, 130 files) contains: install/start/stop
launchers, `requirements.txt`, `app/ core/ tools/ ui/ blender_agent/`,
runtime scripts, `config/settings.json` (no secrets), `version.json`,
`README-QUICKSTART.md`.

- **D1 (junk scan): PASS** — no `__pycache__`, `*.pyc`, `*.zip`, `*.log`,
  backups, `*.broken-*`, `.venv`, or editor content in the package.
- **D2 (dependency contract): PASS** — the package runtime closure imports
  exactly the `requirements.txt` contract (verified by a fresh pip install +
  import validation + backend boot). `app/mcp_gateway.py` (standalone MCP
  server needing the external `mcp` SDK) is excluded; nothing in the shipped
  runtime references it.
- Quickstart: 3 user actions (install -> start -> open UI).

---

## 12. Warnings

- Installer step 5/8 WARN: no Epic build registry entries found on this
  host; the live bridge editor supplies project identity. Non-fatal.
- Installer step 6/8: project scan selects the first alphabetical
  `.uproject` on Desktop as the "recent" pin; runtime proof/identity follows
  the live bridge project.
- Pre-existing `svchost` portproxy listeners on the Tailscale IPv4
  (6766/8765) are not owned by Aivido V1 and are left untouched; V1 remote
  uses `tailscale serve`.
- Watchdog restarts are bounded (max 3 per 15 min) and stop on foreign port
  owners, by design.
- The smoke mission intentionally does not save the level; the editor's
  transient dirty flag after spawn/delete is expected and not persisted.

**Critical:** none. **Major:** none.
