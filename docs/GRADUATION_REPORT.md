# Unreal Agent — Full Product Graduation Report

Date: 2026-08-31 · Engine: UE 5.8.2 · Machine-readable matrix: `memory/graduation_matrix.json`

---

## UNREAL AGENT GRADUATION: PASS

## OVERALL
- tests passed: **105** (0 failed) — full pytest suite, 31s
- tests failed: **0**
- live tests passed: **7/7 probes** (blueprint chain, actor chain, save/map, capture/proof, new-project E2E, product build, self-repair, supervisor) — 8 live probes actually, all PASS
- live tests failed: **0**
- timeouts: **0** (per-test wall-clock guards; no hangs)

## GATES

| gate | status |
|---|---|
| PROJECT LIFECYCLE | PASS |
| PROJECT CONTEXT | PASS |
| BRIDGE | PASS |
| TOOL REGISTRY | PASS (48 tools) |
| BLUEPRINT | PASS (17 live checks) |
| LEVEL/ACTORS | PASS (20 live checks) |
| SAVE/MAPS | PASS |
| EXECUTION ENGINE | PASS |
| SELF-REPAIR | PASS |
| LONG-TASK | PASS |
| OLLAMA | PASS (local-only routing) |
| API | PASS |
| SCREENSHOT/PROOF | PASS |
| SUPERVISOR | PASS |
| UI | PASS |
| RESTART RECOVERY | PASS |
| NEW PROJECT E2E | PASS |
| MULTI-SYSTEM BUILD | PASS |

## BUGS FOUND / FIXED (7)

1. **STATE BUG** — `reconcile_step` required `ok` nested inside `result`; successful tasks stalled at `PENDING_ACCEPTANCE_CRITERIA`. Fixed + 2 regression tests.
2. **PROJECT-SPECIFIC ISSUE** — `save_level` Save-As defaulted to hardcoded AvaLive map. Now derived from the live project. Fixed.
3. **TEST BUG** — `backup/` checkpoint dir shadowed the real `tools.unreal` module (sys.path pollution) and legacy root probes broke collection. Fixed in `pytest.ini`; no blanket skips.
4. **PLANNER BUG** — `deliverable:reopen` had no satisfiable step. Added `open_map` (UE 5.8 `LevelEditorSubsystem.load_level` — `editor_load_map` no longer exists) + planner reopen step + reconcile mapping.
5. **PLANNER BUG** — new-project flow omitted requested light spawn and proof capture, leaving `light:exists`/`viewport:captured` unsatisfiable. Fixed.
6. **STATE BUG** — `deliverable:environment/lighting/camera` had no evidence mapping; long scene builds stalled after all steps succeeded. Fixed via typed-actor spawn mapping.
7. **PLANNER BUG** — hardcoded `GOAL_TEST_LIGHT` label collided across tasks in one map (deterministic ambiguous-label failure). Now unique per task. Also fixed `asset_path=None` variable steps and a "proof" substring match inside project names.

## REGRESSION TESTS ADDED
10 new unit tests (see `memory/graduation_matrix.json` for the list) plus 8 reusable live probes under `scripts/live_*.py` and a test-classification document (`docs/test_classification.md`).

## LIVE VERIFICATION HIGHLIGHTS
- New project E2E (x2 runs): one request → create project → open → bridge → default level → actors+light → save → verify → reopen map → proof → COMPLETE; real editor kill → reopen → no-path context recovery → verify persisted actors → COMPLETE.
- Multi-system build (x2 runs): one request → floor + light + camera + Blueprint actor (String variable READY verified) + UMG widget (created + verified) + saved map + final screenshot → COMPLETE.
- Self-repair (x2 runs): real WRONG_VALUE → validation mismatch → corrective FIX → retry → COMPLETE → disposable cleanup verified.
- Supervisor: one genuine task through the real API pipeline, persisted, restart-safe, artifact verified.
- Backend restarted 5× during the audit; terminal verdicts never duplicated; SSE streams; proof endpoint serves fresh project-scoped PNG.

## GIT
- branch: `main`
- commit: `6b65c8579dcdf2bcc3f3d58397685850b8539cd2`
- push: `ce73d74..6b65c85 main -> main` (no force)
- remote verification: `git ls-remote origin refs/heads/main` == local HEAD ✔

## REMAINING BLOCKERS
**NONE**

## NOTES
- AvaLive was restored after the audit: bridge up, identity `AvaLive`, `open_project` verified (its first boot after project switching is slow — ~10 min — but completes).
- Disposable graduation projects remain under `C:\Users\Shadow\Desktop\UnrealAgentGraduation\` as evidence; no AvaLive content was modified or destroyed.

---

## RELEASE STATUS UPDATE (2026-09-04) — FINAL COMMITTED BASELINE

Supersedes the branch/commit/numbers above. The committed release baseline
(`unreal-coder-universal`, HEAD `74c6b75` at the time of writing) is
release-consistent from a fresh checkout:

- **Final release audit: PASS** — fresh-checkout imports 35/35, focused
  release tests 338/338, full supported regression 528/528 (0 failures),
  package build + source-repo isolation PASS, committed blockers NONE,
  release-ready to push YES. Pushed at `a3123b3` (fast-forward, no force).
- **Task-aware visual acceptance** (`9b64e50`): non-UI actor tasks no longer
  require UI categories; real UI tasks keep the strict 8.5 gate. Packaged
  real task terminal **COMPLETE / SUCCESS / 9.56**; UI-required negative
  case still fails honestly at 7.64. Global thresholds unchanged.
- **Structural UI detection** (`74c6b75`): crisp structured panels detected;
  washed/random dark geometry and time-of-day skies rejected; UI strictness
  preserved.
- **Recovery torture: 8/8 PASS** (`da34dbd`) — backend restart, bridge
  interruption, editor restart, model timeout, malformed response, missing
  asset (truthful mesh_loaded=false fix), interrupted-task resume,
  application restart. Zero collaborator content damage (ShowcaseMap 107
  actors preserved).
- **Live-Unreal isolation** (`a3123b3`): no committed test can dispatch
  through a live bridge/editor; probe scripts are `__main__`-guarded;
  pytest.ini ignores live-UE files.
- **Gap-closure tool coverage**: Blueprint graphs, world/actors, materials,
  MetaHuman, Niagara/VFX, Sequencer/cameras, terrain/foliage/PCG,
  animation — all committed with hermetic regression tests (truthful-error
  passthrough + code-emission + result-parsing contracts).
- **Desktop package**: `dist/unreal-agent-0.1.0` — runtime closure PASS,
  source-repo isolation PASS, smoke suite PASS (version/doctor/selfcheck/
  backend/duplicate-protection/UI/clean-stop).

Test counts are recorded in `assetlib/proof/` (supported-suite baseline
JSONs) and the pytest.ini in this repository.
