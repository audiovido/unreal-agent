# AIVIDO — RC1 INTEGRATION REPORT

- **Branch:** `aivido/rc1-integration`
- **Date:** 2026-09-07 (UTC)
- **Decision:** **RC1_READY_WITH_WARNINGS**
- **RC1 score:** **95/100** (truthful baseline from release-95 preserved; integration introduced no regressions)

## 1. Sources

| Lane | Branch | Commit |
|---|---|---|
| Primary release | `aivido/overnight-release-95` | `77ede15155316723b0af9a77dbd4a178166d6c6c` |
| QA defects | `aivido/qa-defect-fixes` | `f95e17962a36840f3c3f6bd563dca368f3373118` (tests: `9d52422b46afee1cfefce2eb8e4e94a87b4283a8`) |

Integration: RC1 branched from release-95; QA commits **cherry-picked in order (9d52422 → f95e179) with zero conflicts** (`3c169bf`, `b16e843`).

**Both lanes preserved:** overnight runtime fixes (session 404 fail-closed, `SessionStore._ensure_loaded`, `REQUESTED_TOOL_MISSING` gate, `app.served` startup, hardening reports/tests) and QA fixes (WORKER2 manifest valid JSON, guarded localStorage, correct manifest hashes/cache-bust, duplicate REFS removal, hermetic QA suite).

## 2. Static integration check — PASS

- `git diff --check`: clean
- **48** report/config JSON files parse, 0 invalid
- `node --check ui/aivido.js`: PASS
- `ui/build-manifest.json`: **15/15 file hashes match** actual content
- Merge markers: none (one decorative `====` banner in `scripts/build_product_package.py` is not a marker)
- Secrets: none (only env-based API-key loading and a client-side optional token field)
- No temp files committed

## 3. Combined test suite — 1031 passed / 1 skipped / 0 failed

- **Full pytest:** 1031 passed, 1 skipped (pre-existing), 0 failed — 122 s
- **QA hermetic suite:** 90/90 (4 files: idle-driver, planner-evidence, release-integrity, UI-contract)
- **Session hardening regressions:** 6/6
- **Integration fix (root cause only):** `test_vehicle_profile_keeps_bounded_strategy_and_corrected_locator` depended on a **git-ignored machine-local capture** and failed on every clean checkout — verified pre-existing on BOTH base branches, not integration-induced. Made hermetic (test writes its own baseline file); production code untouched. 3/3 pass.

## 4. Live RC1 smoke — PASS

Backend `app.served:app` @ 127.0.0.1:8765 running **from this RC1 worktree**; bridge 127.0.0.1:6766, UE 5.8.2, AividoHQ.

- **Unreal:** 8/8 characters, 23/23 props, 8 screens, 6 UI boards, 0 broken roots, 0 missing materials, **41/41 lights movable → lighting rebuild warning = 0**
- **Save/reopen:** PASS (post-reopen scan stable: 173 actors, same counts)
- **E2E 3/3 terminal & truthful:**
  - A inspect/report → `done / PASS` (3.0 s)
  - B viewport proof/capture → `done / PASS` (3.1 s), 2 live proof entries with bridge identity + engine + map
  - C impossible tool → `failed` with `REQUESTED_TOOL_MISSING`: "refusing to report success for impossible work"
  - (Observation: B's first wording made the planner include `spawn_actor`, which the read-only policy **correctly rejected** — truthful policy behavior, retried with capture-only wording.)

## 5. UI smoke — PASS

360 / 390 / 430 / 1440 px: boot OK, **0 JS console syntax errors**, hero CTA stacked with zero overflow on mobile widths and untouched row at 1440, single `#homeEnterRoom` (no duplicate wiring), guarded storage OK, backend badges live ("engine linked", "bridge ready", "map AividoHQ").

## 6. Counts & decision

- Critical: **0**
- Major: **0**
- Warnings: **3** — favicon.ico 404 (cosmetic); 1 pre-existing skipped test; machine-local `config/project_registry.json` stays untracked (runtime config, consistent with prior lanes)

**Decision: RC1_READY_WITH_WARNINGS**
