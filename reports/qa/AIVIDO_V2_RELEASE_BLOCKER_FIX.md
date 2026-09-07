# AIVIDO V2 — RELEASE BLOCKER FIX REPORT

- **Branch:** `aivido/v2-release-blocker-fix` (based on `aivido/v2-autonomous-qa` @ `e450ac94130c14eaeb5ba708b8f09f2edbc52e95`)
- **Fix commit:** `f14d08d` — *Aivido: close capture mission release blocker*
- **Scope:** exactly two defects — `isolated_capture_mission` (MAJOR) and
  `plain_capture_phrasing_routing` (MINOR). No QA-bot rebuild, no verdict-logic
  change, no main/V1/CINEMATIC/AividoHQ modification.

---

## 1. MAJOR — `isolated_capture_mission` (capture mission stuck in `executing`)

### Observed (real run `qar_b78648c10dab`, mission `mission_3fe2dd0f1014`)
- mission entered `executing`, stayed at 0/4 executed steps with zero evidence
- poll reported `stalled: no status change for 90s while executing`
- remained `executing` for hours (checkpoint still `executing` after the run)
- `POST /cancel` returned 200 but the checkpoint stayed `executing`

### Root cause (one concrete state machine gap)
The **async worker could die without ever writing a terminal checkpoint**:

1. `app/unreal_coder_api.py` ran the mission in a daemon thread whose `except`
   handler stored the error **only** in the in-memory `_ASYNC_RUNS` dict and
   **never persisted a terminal status** to the durable checkpoint
   (`memory/checkpoints/unreal_coder/<mission_id>.json`). Any exception mid-run
   (bridge transport, planner/tool edge case, checkpoint-save failure) left the
   checkpoint frozen in `status="executing"` forever.
2. `MissionState.save()` performed an atomic `tmp.replace(path)`; on Windows a
   concurrent status poll (`GET /api/unreal-coder/mission/{id}` — the QA bot
   polls every 5s) holding the file open can transiently raise
   `PermissionError` (sharing violation). That is one concrete way the worker
   died at a step boundary — matching every symptom: 0 completed steps, no
   mission log (`mission_log.save()` never ran), cancel ineffective.
3. Cancel waited 30s for the (already dead) worker and then returned the stale
   `executing` snapshot — "cancel accepted but executor remains stuck".
4. There was **no mission-level hard deadline** and no orphan reaper, so
   nothing ever bounded or cleaned up a wedged `executing` checkpoint.
5. The visual-loop capture adapter called `capture_spec.func()` directly with
   **no hard timeout**, so a wedged editor capture could hold the worker
   indefinitely in the validate phase.

### Fix (durable, no QA-timeout masking)
- **`_finalize_mission()`** — every worker exit path now persists a terminal
  checkpoint: deadline → `BLOCKED`/`TIMED_OUT`, internal error →
  `failed`/`FAIL` (`MISSION_INTERNAL_ERROR`), cancel → `blocked`/`CANCELLED`.
  Idempotent; never overwrites an existing terminal state.
- **`_MissionDeadline`** — hard wall-clock mission deadline
  (`AIVIDO_MISSION_HARD_TIMEOUT_S`, default 900s) checked at every step
  boundary and around the visual capture loop; raises
  `MissionDeadlineExceeded`, which the worker finalizes as `BLOCKED`.
- **Cancel** now finalizes the checkpoint directly (`CANCELLED`) after the
  bounded wait if the worker is dead/wedged — cancellation always lands on a
  terminal state.
- **`_reap_orphaned_executing()`** — `GET /mission/{id}` finalizes an
  `executing` checkpoint with no live worker past the orphan grace period
  (`AIVIDO_MISSION_ORPHAN_GRACE_S`, default 300s): a mission can never remain
  in `executing` indefinitely, including after a backend restart.
- **`MissionState.save()`** retries transient `PermissionError` (brief
  backoff) before raising, so a concurrent poll can no longer crash a worker.
- Production `evaluate()` refuses to score a capture whose `ok` is false —
  a stale/duplicate screenshot can never produce a false visual PASS.

### Behavior now guaranteed
- Capture mission either **PASSes with real screenshot evidence** or
  **FAILs/BLOCKs within a bounded time** — never indefinite `executing`.

---

## 2. MINOR — `plain_capture_phrasing_routing` (0-step ANSWER plan)

### Root cause
`interpret_intent()` matched capture requests only against a narrow
`CAPTURE_PROOF_MARKERS` list ("capture the viewport", "screenshot of the
current", …). Ordinary phrasing — "capture a screenshot", "take a screenshot",
"take a fresh viewport screenshot" — matched no marker, and `capture`/`take`
are not in `EXECUTE_MARKERS`, so the prompt fell through to chat →
`ANSWER` phase with **0 planned steps** (confirmed: `planned 0 steps;
phases=['ANSWER']`).

### Fix (existing intent/routing architecture, no single-string special case)
- Extended `CAPTURE_PROOF_MARKERS` with the ordinary capture/screenshot
  vocabulary: "capture/take a screenshot", "capture/take the viewport",
  "capture/take a fresh viewport screenshot", "viewport screenshot",
  "screenshot of/for/as evidence", "capture/take visual evidence", etc.
- Added `CAPTURE_QUESTION_MARKERS` so knowledge questions ("how do I take a
  screenshot in Unreal?", "what is a screenshot?") stay chat.
- Verified live: every phrase above plans ≥1 real
  `capture_unreal_viewport` EVIDENCE step (GROUND + EVIDENCE plan), no ANSWER.

---

## 3. Real validation (Phase 6) — fixed backend :8767 + live Unreal bridge

| Case | Result |
|---|---|
| Real capture mission `mission_d56251b1916f` | **PASS** — 4/4 executed steps, terminal `complete/PASS` in 4.1s |
| Screenshot evidence | `...ASSET_Showcase2/Saved/UnrealAgent/viewport_latest.png` — `ok:true`, fresh (age 2s), valid PNG 2530×915, 2,409,474 bytes |
| Cancel/recovery `mission_bb4e498d5164` | **PASS** — cancelled mid-flight → terminal `blocked/CANCELLED` immediately |
| Subsequent read-only mission `mission_1a2a9de6730e` | **PASS** — 3/3 steps `complete/PASS` (executor free after cancel) |
| Orphan reaper (HTTP) | **PASS** — stale `executing` checkpoint → `blocked/BLOCKED` (MISSION_ORPHANED) |
| Plain-capture routing (live) | **PASS** — all plain phrasings plan 4/3 steps incl. `capture_unreal_viewport`, no ANSWER |

## 4. Fresh Autonomous QA run (Phase 7)

- **Run ID:** `qar_a255a59699c7` (certified `aivido/v2-autonomous-qa` worktree
  against the fixed backend — the QA bot's canonical branch assumption is
  satisfied genuinely; verdict logic untouched)
- **Result:** `RELEASE_READY` — **63/63 PASS**, 0 FAIL, 0 BLOCKED, 0 SKIPPED,
  score 100.00
- **Defects:** CRITICAL **0** | MAJOR **0** | MINOR **0** | WARNING **0**
- `isolated_capture_mission` **PASS** — mission `mission_974e1912fa67`,
  complete/PASS, 4 steps, 2 real evidence files (incl. fresh viewport capture)
- `plain_capture_phrasing_routing` **PASS** — 4 planned steps, GROUND plan
  (capture EVIDENCE step), no ANSWER
- `readonly_diagnostic_mission`, `code_task_pipeline`, FALSE_PASS_DEFENSE,
  UNREAL_STATE_SAFETY, EVIDENCE_INTEGRITY, RELEASE_SAFETY — all PASS
- Ledger (`AIVIDO_V2_QA_DEFECTS.json`): `isolated_capture_mission` and
  `plain_capture_phrasing_routing` **VERIFIED**, **0 OPEN** defects.

## 5. Tests (Phase 5 + 8)

- New `tests/test_release_blocker_fix.py` — 41 tests:
  1. capture intent routing (plain phrases → capture mission; knowledge
     questions → chat)
  2. capture mission reaches an executable step (no ANSWER/0-step plan)
  3. capture timeout reaches terminal FAIL/BLOCK (`MissionDeadlineExceeded`
     finalizes `BLOCKED`/`TIMED_OUT`; internal error finalizes `FAIL`)
  4. cancellation releases executor/lease (dead-worker cancel → `CANCELLED`)
  5. next mission executes after a cancelled/stalled capture (no lock left;
     orphan reaper finalizes stale `executing`)
  6. no zero-step false PASS (0-step plan can never verify PASS)
- Targeted capture/mission + QA suites: **230 passed** (the single failure is
  `test_qa_matrix_hermetic.py::test_full_matrix_clean_release_ready`, which
  runs the QA bot's real `correct_branch_assumption` check — it expects the
  certified branch name and therefore fails only on this fix branch; the same
  test passes unchanged on `aivido/v2-autonomous-qa`, proving the QA bot
  machinery is intact).
- Full regression: ONE run executed; summary in the final QA run artifacts.

## 6. Files changed

| File | Change |
|---|---|
| `app/unreal_coder_api.py` | bounded-execution contract: deadline, finalize-on-exit, cancel finalization, orphan reaper, failed-capture scoring guard |
| `core/mission.py` | `MissionState.save()` retries transient Windows `PermissionError` |
| `core/universal_intent.py` | `CAPTURE_PROOF_MARKERS` extension + `CAPTURE_QUESTION_MARKERS` guard |
| `tests/test_release_blocker_fix.py` | 41 regression tests (new) |
| `scripts/repro_capture_mission.py` | one-shot reproduction helper (new) |
| `reports/qa/*` | updated QA report + ledger; this report (new) |