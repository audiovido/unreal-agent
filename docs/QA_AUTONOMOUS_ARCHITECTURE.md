# Aivido V2 — Autonomous QA Bot: Architecture Note

Status: Phase 1 discovery + design (implemented in `qa/`)
Base branch: `aivido/v2-cinematic` @ `06ccf67c949ff09da9ec792151adc078f4c369c0`

## 1. What already exists (reused, never duplicated)

Discovery over the existing codebase found a substantial verification
machinery that the QA bot reuses rather than re-implements:

| Existing system | Location | Reused for |
|---|---|---|
| Mission engine + verdict honesty (0-step PASS blocked, UNVERIFIED_REQUIREMENTS gate, read-only policy plan gate) | `core/mission.py`, `core/mission_policy.py` | Mission black-box runs are executed through the REAL pipeline; its verdicts are consumed, never fabricated |
| Universal mission API (interpret → plan → execute → validate → evidence) | `app/unreal_coder_api.py` (`POST /api/unreal-coder/async`, `GET /api/unreal-coder/mission/{id}`, `/validate`, `/resume`, `/cancel`) | The black-box mission checks drive this API like an external client |
| Code-task supervisor (durable queue, isolated worktree, evidence bundle, verdict honesty) | `app/code_tasks.py` (`/api/code/*`) | Code-task black-box checks |
| Doctor / runtime checks (PASS/WARN/FAIL over python, config, Unreal exe, bridge, ports, dirs, API boot, secrets-in-config) | `core/doctor.py`, `/api/unreal-coder/doctor` | Runtime-health group baseline |
| Proof store (session-isolated proof tree, path-traversal safe, sha256) | `core/proof_store.py` | Evidence-integrity verifier primitives (resolve/list/url) |
| Session API (sessions, projects, proof serving, cancel, restart) | `app/session_api.py` | Recovery + evidence retrieval checks |
| Project safety guard / session identity (project, editor PID, active map) | `core/project_safety.py`, `/api/unreal-coder/session` | Unreal identity checks |
| Bridge identity (`UnrealBridge.get_identity`, `list_level_actors`, `get_current_level`) | `tools/unreal/unreal_bridge.py` | Unreal state safety (actor count, cast, no WhiteH, no AVCam residue) |
| Cinematic committed artifacts (headless MRQ report, MP4, proof stills) | `reports/cinematic/` | Cinematic artifact QA (never re-renders) |
| Workboard self-test / recovery machinery, code-task watchdog | `app/workboard_selftest.py`, `app/code_tasks.py` | Recovery-group reference + duplicate-submission protection pattern |

## 2. The QA bot is a black-box client

`qa/client.py` talks to the **running backend** over HTTP
(`AIVIDO_BACKEND_URL`, default `http://127.0.0.1:8765`) exactly like an
external QA engineer. It never imports `app/api.py` execution state and
never calls into the mission engine in-process; the only direct
out-of-process probe is the **read-only** Unreal bridge (identity,
actor list, current level) for scene-preservation checks.

## 3. Core model

- `QARun` — durable run envelope: `id`, `started_at`, `finished_at`,
  `status`, `target`, `checks[]`, `defects[]`, `score`, `verdict`,
  `evidence`, `environment_snapshot`.
- `QACheck` — one check: `name`, `category`, `status` (PENDING/RUNNING/
  PASS/FAIL/BLOCKED/SKIPPED), `duration`, `expected`, `observed`,
  `verifier`, `evidence`, `severity_if_failed`.
- `QADefect` — `id`, `severity` (CRITICAL/MAJOR/MINOR/WARNING),
  `category`, `title`, `reproduction`, `expected`, `actual`, `evidence`,
  `suspected_component`, `retryable`, `blocker`.

Persistence: `memory/qa/runs/{run_id}/` with `run.json`, `checks.json`,
`defects.json`, `evidence/`. A run found in RUNNING state on load is
recovered to `FAILED` with an explicit `RECOVERED_AFTER_INTERRUPT` note
(durable + recoverable).

## 4. No-fake-PASS verifier contract

Every PASS must name a verifier. The verifier registry
(`qa/verifier.py`) implements the independence rules:

- `http_ok` — HTTP 2xx is only evidence of transport, used for API-contract
  checks that additionally assert response body semantics.
- `mission_verdict` — PASS only when the pipeline's own `status == complete`
  AND `verdict == PASS` AND ≥1 executed step AND ≥1 real evidence entry
  with a real file path.
- `evidence_file_ok` — file exists, non-zero size, type expected, mtime
  within the run window (or explicitly proven fresh), not `[object Object]`.
- `screenshot_valid` — PNG/JPEG decodable, dimensions > 0, file non-empty;
  identical-hash duplication across distinct captures is flagged as stale
  duplicate evidence.
- `actor_count_ok` / `cast_preserved` — read from the live bridge actor
  list, not from a report.
- `no_false_pass` — the injected bad case MUST fail; a check that
  "passes" a deliberately broken fixture is itself a FAIL of the
  false-pass defense group.
- `truthful_claim` — the claimed result must be present in `observed`
  with independent evidence; a claim without evidence is FAIL.

## 5. Check matrix (10 groups)

1. RUNTIME_HEALTH — backend, gateway, Unreal bridge, process identity,
   ports, latency, doctor summary.
2. API_CONTRACT — status, start mission (async), task status, evidence,
   retry, cancel, route_prompt, malformed input, unknown task id, timeout.
3. MISSION_BLACKBOX — one read-only Unreal mission, one isolated harmless
   Unreal mission, one code task, one mixed routing mission (if supported).
4. FALSE_PASS_DEFENSE — deliberately inject bad fixtures (completed-without-
   evidence, missing/invalid screenshot, stale evidence, wrong task id,
   blocked/timed-out task, bridge unavailable, impossible claim); QA MUST
   FAIL them.
5. EVIDENCE_INTEGRITY — files exist, type, non-zero size, timestamps,
   ownership to the correct task, no stale duplicates, no `[object Object]`,
   no schematic/offline proof as real Unreal, no viewport fallback as MRQ.
6. UNREAL_STATE_SAFETY — certified AividoHQ exists; actor count 166;
   8/8 cast; no WhiteH; no transient Z repair; durable orientation; no
   unexpected AVCam/test actors; `/Game/CineMRQ` isolated; live bridge
   identity matches expected editor/project. READ-ONLY ONLY.
7. CINEMATIC_ARTIFACT — headless MRQ report exists, MP4 exists,
   1920×1080 @ 30 fps, 8 s, 240-frame claim consistent, proof stills
   exist, video non-empty/playable (never re-renders).
8. UI_BLACKBOX — every production route serves HTTP success, no JS-fatal
   responses, API-backed state renders, no obvious false-PASS labels,
   evidence fields readable, task states consistent (deterministic checks).
9. RECOVERY — retry, cancel, duplicate-submission protection, stale-task
   recovery, watchdog presence.
10. RELEASE_SAFETY — secrets hygiene, junk/build artifacts, absolute local
   paths in product-facing output, dirty certified files, branch
   assumptions, doctor sanity, packaging prerequisites.

## 6. Self-heal rules (bounded)

May: retry an idempotent request once; restart a safe service through an
existing coordinator; refresh stale status; re-query evidence.
Must NOT: rewrite code areas, modify certified AividoHQ, modify cast,
modify cinematic assets, force PASS, delete evidence. Real defects are
recorded in the ledger, never concealed.

## 7. Verdict rules

RELEASE_READY requires: 0 CRITICAL open, 0 MAJOR open, core black-box
mission PASS, false-pass defense PASS, Unreal preservation PASS, evidence
integrity PASS, acceptable regression. Warnings/minors may remain but MUST
be listed.

Outputs: `reports/qa/AIVIDO_V2_QA_DEFECTS.json`,
`reports/qa/AIVIDO_V2_AUTONOMOUS_QA_REPORT.md`,
`reports/qa/AIVIDO_V2_AUTONOMOUS_QA.json`.

## 8. API

`POST /api/qa/run`, `GET /api/qa/runs/{id}`,
`GET /api/qa/runs/{id}/report`, `GET /api/qa/runs/{id}/defects`.
Runs are durable (on-disk per-run tree) and recoverable (interrupted
runs are marked, never silently lost).