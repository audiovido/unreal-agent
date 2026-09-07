# AIVIDO V1 — FINAL DEFECT CLOSURE

**Branch:** `aivido/v1-final-defect-closure`
**Base:** `9811a533580c10956748772cb0b828e1698b0714` (`aivido/v1-productization`)
**Date:** 2026-09-07
**Scope:** ONLY the three verified black-box defects. No redesign, no new features,
no mutation of certified scene content, zero changes to the V1 installer/runtime/
watchdog/Tailscale surface beyond what the defect fixes require.

---

## Defects fixed

### D1 (MAJOR) — explicit verification requirements are skipped
Exact counts ("8 human agents / 23 props / 41 movable lights") and mesh/material
checks were previously not planned as real executable verification work.

**Fix:**
- `core/universal_intent.py` — new deterministic `verification` mission mode
  (read-only EXECUTE) + `parse_explicit_checks()` which extracts every explicit
  item: `map <name>`, `bridge healthy`, `exactly N human agents|props|movable
  lights`, `missing skeletal meshes`, `missing prop mesh/material references`,
  and `proof/capture`. An item that cannot be mapped to a deterministic target
  stays a truthful `generic` check — it is reported UNVERIFIED, never skipped.
- `core/universal_planner.py` — emits ONE real step per explicit check
  (`verify_scene` read-only probes + `capture_unreal_viewport` for proof), each
  tagged `covers=<check_id>`.
- `tools/unreal/scene_verification.py` (NEW) — registered `verify_scene` tool;
  each check runs a real, read-only editor query (actor scan by prefix, light
  mobility, skeletal-mesh presence, prop mesh/material slot references) and
  returns `measured` vs `expected`. Registered in the canonical registry and
  classified `READ_ONLY` in the mission policy (verified: `classify_tool`
  returns READ_ONLY; zero plan violations in READ_ONLY mode).

### D2 (MAJOR) — false PASS
Mission PASS was possible while explicit user requirements were not planned,
executed and evidenced.

**Fix:** `core/mission.py` — the verdict gate now treats verification missions
specially: PASS is IMPOSSIBLE while any explicit check is NOT_PLANNED /
NOT_EXECUTED / NOT_EVIDENCED. Verdicts are truthful:
- `FAIL` + `UNVERIFIED_REQUIREMENTS: <requirement> (NOT_PLANNED|NOT_EXECUTED|NOT_EVIDENCED)`
- `BLOCKED` + `REQUESTED_TOOL_MISSING: verify_scene ...` when the tool is not registered.

Every executed verification step emits a real evidence entry (`kind=verification`
with measured/expected/detail), so a PASS always carries per-requirement evidence.
`REQUESTED_TOOL_MISSING` (session-execution gate), capture-only prompts and
read-only policy are preserved unchanged.

### D3 (MINOR) — Mission Control evidence shows `[object Object]`
Structured evidence dicts were rendered with `String(obj)`.

**Fix:** `ui/aivido.js` — new `fmtEvidence()` renders dict evidence
human-readably (`kind · check: id · step: id · measured=N expected=N · ok · detail · path`)
and is applied to both the live mission detail and mission list. Verified with
the SHIPPED function against the REAL 8-entry verification payload in node:
zero `[object Object]`; the live UI session logged zero console errors and all
network 200.

---

## LIVE FINAL TEST — strict read-only AividoHQ verification

Prompt run verbatim through `POST /api/unreal-coder` (read-only):

> Run the exact strict read-only AividoHQ verification: map AividoHQ, bridge
> healthy, exactly 8 human agents, exactly 23 W3I props, exactly 41 movable
> lights, missing skeletal meshes, missing prop mesh/material references, fresh
> real viewport proof

**Verdict: PASS** — 10/10 steps executed; every explicit requirement planned,
executed and evidenced. Real measured values:

| requirement | measured | expected | evidence |
|---|---|---|---|
| bridge healthy | UNREAL_BRIDGE_READY | healthy | verification entry |
| map AividoHQ | `/Game/Maps/AividoHQ.AividoHQ` | AividoHQ | verification entry |
| exactly 8 human agents | 8 (`AVIDO_Human` prefix) | 8 | verification entry |
| exactly 23 props | 23 (`W3I_` prefix) | 23 | verification entry |
| exactly 41 movable lights | 41 (static 0, stationary 0) | 41 | verification entry |
| missing skeletal meshes | 0 missing among 8 checked | 0 | verification entry |
| missing prop mesh/material references | 0 null among 23 checked | 0 | verification entry |
| fresh real viewport proof | fresh PNG (1.2 MB) | capture | viewport_capture entry |

**False-PASS gate proven live:** the first execution attempt (before the count
tool alias was corrected) truthfully returned
`FAIL — UNVERIFIED_REQUIREMENTS: exactly 8 human agents (NOT_EXECUTED); exactly 23 props (NOT_EXECUTED)`
with 6/8 checks evidenced — a PASS was impossible while 2 checks had not
executed. No fabricated success at any point.

---

## LIVE FINAL TEST — one real Create → Modify → Verify → Capture → Cleanup E2E mission

`scripts/aivido_smoke.py` (bounded disposable actor `AIVIDO_V1_INSTALL_SMOKE`,
now including a Modify phase) — **SMOKE OVERALL: PASS, 17/17 steps**:

- Create: `spawn_cube` PASS (StaticMeshActor, mesh loaded)
- Modify: `actor_moved` PASS (readback matches target), `actor_scaled` PASS
  (3.0,3.0,3.0), `modify_readback` PASS (independent `get_actor` confirms
  location + scale)
- Verify: `actor_exists` PASS, `only_smoke_actor_added` PASS (only the
  disposable actor was added)
- Capture: `viewport_aimed` PASS (engine look-at), `viewport_capture` PASS
  (fresh 1.2 MB viewport PNG), `proof_saved` PASS
- Cleanup: `actor_deleted` PASS, `actor_absent_after` PASS (polled until gone),
  `level_restored` PASS (166 actors == baseline 166), `no_save_performed` PASS
  (certified scene content untouched on disk)

Proof: `reports/release/AIVIDO_V1_SMOKE_EVIDENCE/AIVIDO_V1_INSTALL_SMOKE_proof.png`
+ `mission.json` (all 17 step records).

---

## Tests

Full safe suite on the final branch state:
**1082 passed / 1 skipped / 0 failed** (1062 V1 baseline + 20 new hermetic
defect-closure tests in `tests/test_verification_mission.py` — intent parsing,
per-check planning, read-only policy, the false-PASS gate (all four truthful
outcomes), verify_scene measured results, and evidence payload shape).

## Regression

- V1 installer/runtime/watchdog/Tailscale: untouched by the defect fixes.
- Capture-only prompts (`capture_only`) and diagnostics: behavior preserved
  (verification detection is additive and narrowly triggered).
- `REQUESTED_TOOL_MISSING` (session-execution): preserved; the new tool-missing
  path uses the same truthful vocabulary at the mission gate.
- Read-only verification: zero mutation — the strict verification mission uses
  only READ_ONLY tools (`inspect_project`, `unreal_ping`, `verify_scene`,
  `capture_unreal_viewport`); actor scan before/after the E2E is identical
  (166 actors).

## Warnings

- Sandbox artifact (not product defect): in-session spawned backends in this
  agent workspace are reaped after tool-call boundaries; the V1 persistent
  runtime's terminal-close survival and crash-restart were certified in the
  prior V1 run via scheduled-task spawn (launcher-exit survival PASS,
  crash-restart PASS). Product runtime behavior is unchanged.
- The UI preview attach was limited for the scheduled-task-spawned process; D3
  was verified at the shipped-function + real-payload level (node, zero
  `[object Object]`) plus a live UI session with zero console errors.
- Smoke `dirty_flag=true` is the transient in-editor state from spawning the
  disposable actor; the level is deliberately NOT saved, so nothing is
  persisted.

## Summary

- critical: 0
- major: 0 (D1, D2 fixed and live-verified)
- minor: 1 (D3 fixed and verified)
- **FINAL_V1_READY: YES**