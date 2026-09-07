# AIVIDO — RC1.1 CLEAN-INSTALL DEFECT CLOSURE REPORT

- **Branch:** `aivido/rc1.1-clean-install-fixes`
- **Base:** `aivido/rc1-integration` @ `b079300de99715347877b21e3940c5ba19dd4413`
- **Head:** `3a80be9`
- **Date:** 2026-09-07 (UTC)
- **RC1.1_READY: YES** — both defects fixed, verified on a real clean clone, zero regressions.

## 1. Defect 1 — missing install dependency (`requests`) — FIXED

The clean clone failed with `ModuleNotFoundError: No module named 'requests'` because the documented dependency closure (`scripts/build_product_package.py`) listed only fastapi/uvicorn/pillow/numpy/pydantic while `core/orchestrator.py`, `app/api.py`, `tools/unreal/unreal_bridge.py`, `core/agent.py` (rich), and others import more.

**Fix (contract, not machine patch; no vendoring):**

1. **`requirements.txt`** created at the repo root as the **authoritative runtime dependency contract**: fastapi, uvicorn, pillow, numpy, pydantic, **requests**, **rich** (rich is a hard top-level import in `core/agent.py` — also missing from the old closure).
2. `scripts/build_product_package.py` packaging documentation now defers to `requirements.txt`.
3. `app/start.ps1` **bootstraps a missing `.venv` from `requirements.txt`** (clean-install path can no longer start with a broken import closure).
4. `core/env_doctor.py` `CORE_DEPS` now verifies requests + rich.

**Clean runtime import: PASS** — verified in an isolated clean worktree with a genuinely fresh venv installed solely from `requirements.txt` (import requests, fastapi, uvicorn, PIL, numpy, pydantic, rich all succeed).

## 2. Defect 2 — viewport capture missions built 0-step plans — FIXED

`/api/unreal-coder` with an explicit viewport capture/proof prompt produced a 0-step ANSWER plan (universal intent classified capture prompts as chat), which the **truthful zero-step guard correctly failed**. The guard was preserved; the planner was fixed.

**Fix (root cause):**

1. `core/universal_intent.py`: new `CAPTURE_PROOF_MARKERS` + `intent.capture_only` — explicit requests ("capture the current viewport", "screenshot of the current viewport as evidence", "return visual proof of the current Unreal viewport", …) now classify as **mode=execute, read_only=True**, and the read-only flag is **not** reset for capture-only intents.
2. `expand_requirements` emits exactly one `capture_evidence` requirement (never the mutating environment-polish default).
3. `core/universal_planner.py`: `capture_evidence` plans a single **READ-ONLY EVIDENCE step with the real registered `capture_unreal_viewport` tool** — no mutating steps, no spawning, no fake evidence.
4. `core/mission.py`: capture-only missions record the real captured PNG in mission evidence (`_emit_capture_evidence`, unwrapping the bridge envelope: path + bytes).

## 3. Regression tests — 20 new, hermetic

`tests/test_clean_install_contract.py`:

- runtime import contract (7 modules incl. requests) + requirements.txt completeness
- the 3 required capture prompts → `capture_unreal_viewport` EVIDENCE steps
- read-only compatibility (read_only intent; zero mutating tools in plan)
- exact clean-clone prompt → real capture step
- unrelated chat question → **no** capture step
- `capture_only` flows through `intent.to_dict()` to the policy layer
- **zero-step execute missions still FAIL truthfully** (guard intact)
- **REQUESTED_TOOL_MISSING behavior intact** (release-95 gate + helper)
- capture evidence emission records the real path/bytes from the nested bridge envelope

## 4. Full test suite

**1051 passed / 1 skipped (pre-existing) / 0 failed** (130 s). No new failures.

## 5. Live clean-clone E2E — REQUIRED PASS

- **Environment:** NEW isolated clean worktree (fresh checkout of the fixed branch) + **fresh venv installed from requirements.txt**; backend `app.served:app` on **127.0.0.1:8790**; existing live bridge 127.0.0.1:6766 (UE 5.8.2, AividoHQ).
- **Request:** exactly as specified — `POST /api/unreal-coder` with the capture prompt, `mode=execute`, `quality=standard`, `dry_run=false`.
- **Result (mission `mission_631b6f668cf8`):**

| Requirement | Result |
|---|---|
| status = complete | **complete** |
| verdict = PASS | **PASS** |
| steps_total ≥ 1 | **3** |
| steps_completed == steps_total | **3 == 3** |
| evidence_count ≥ 1 | **1** |
| real viewport evidence | **native editor viewport capture** — `Saved/UnrealAgent/viewport_latest.png`, 1,351,837 bytes, written during the mission (`OK|source=LevelViewport[1]|perspective=1|visible=1|width=1922|height=677`) |
| project not mutated | **mutation = 0** — actor scan identical before/after (173 actors, 8/8 characters, 23/23 props, 41/41 movable lights, 0 broken roots, 0 missing materials); read-only policy enforced end-to-end |

## 6. Counts & decision

- Critical: **0** · Major: **0** · Warnings: **2** (legacy mission_log writer can show `steps_total: 0` while the API truthfully reports 3/3 — counters lag `completed_work`; 1 pre-existing skipped test)
- Baseline score **95** preserved.

**RC1.1_READY: YES**
