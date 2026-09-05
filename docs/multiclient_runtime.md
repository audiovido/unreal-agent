# Aivido Multi-Client + Multi-Project Runtime

**Goal.** Turn Aivido into a true multi-client, multi-project Unreal automation
server running on one Shadow PC: Mac/PC browsers hit the same Aivido backend,
each drives its own Unreal project concurrently, and nothing is shared or
corrupted — editor instance, active project, active map, execution state,
proofs, Visual Director state, task queue, project files.

**Constraint honored throughout.** The canonical execution system was NOT
redesigned. `app/api.py`'s executor, `core/mission.py`'s MissionEngine, the
UniversalPlanner, `core/mission_policy.py` (Planner Safety / READ_ONLY) and
`core/project_safety.py` are all reused verbatim. The multi-client layer is a
session-scoped *dispatch envelope* around the existing machinery, plus new
additive REST endpoints and a browser Sessions screen. Single-project
behavior is unchanged (the legacy surface still works with no session).

---

## 1. Architecture

```
browser client A ─┐                        ┌─ session A → bridge 127.0.0.1:6766 → UnrealEditor A (ASSET_Showcase2)
browser client B ─┼─ /app (Sessions screen)┤
                  └─ /api/sessions/*       └─ session B → bridge 127.0.0.1:6767 → UnrealEditor B (ASSET_P1_Smoke)

Aivido backend (same process as the canonical runtime)
├─ core/session_model.py      session records + persistent SessionStore
├─ core/project_registry.py   persistent project registry (validated paths only)
├─ core/bridge_allocator.py   collision-safe per-project bridge port allocation
├─ core/resource_supervisor.py CPU/RAM/GPU sampling + SAFE_PARALLEL / GPU_HEAVY policy
├─ core/proof_store.py        isolated proof tree + proof manifests
├─ core/session_execution.py  session runner: identity guard, READ_ONLY boundary,
│                             project mutation guard, per-project leases,
│                             resource gate, proof recording, crash detection
├─ app/session_api.py         /api/sessions + /api/projects + /api/resources
└─ core/mission*.py (canonical) planner / policy / engine — unchanged
```

**Canonical relationship (Phase 4):**

```
client → session → project → execution → Unreal bridge → proof
```

Every task carries an execution id that belongs to exactly one session; every
session owns one bridge endpoint and one project. The session runner refuses
to dispatch when the live editor identity (project path, editor PID) does not
match the session record — fail closed on ambiguous identity.

## 2. Files changed

**New modules (core layer):**

| File | Responsibility |
|---|---|
| `core/session_model.py` | `ProjectSession` dataclass (all Phase-1 fields), `SessionTask`, `SessionStore` (thread-safe, one JSON per session under `memory/sessions/`; disk is the source of truth). Statuses: STARTING, READY, BUSY, VALIDATING, BLOCKED, OFFLINE, CRASHED. |
| `core/project_registry.py` | Persistent registry (`config/project_registry.json`): project_id, display_name, .uproject path, preferred engine, bridge config, last map, proof directory, project health. `list/register/connect/disconnect/inspect/start-project-session`. Registration requires an explicit, existing, parseable `.uproject` path — no arbitrary filesystem search is exposed. |
| `core/bridge_allocator.py` | Per-project port allocation in range 6766–6799 (`UA_BRIDGE_PORT_MIN/MAX`). A port is only handed out when not already live (socket probe) and never to two projects; bindings are stable per project (reconnect keeps the endpoint); `force=True` binds a preferred port after identity verification (reuse path). |
| `core/resource_supervisor.py` | Background sampler (tasklist + nvidia-smi; psutil optional): CPU, RAM, GPU memory/utilization, active UnrealEditor PIDs, active heavy tasks. `classify_prompt/tools` → SAFE_PARALLEL | GPU_HEAVY. `gate()` → RUNNING | QUEUED_RESOURCE | THROTTLED. SAFE_PARALLEL always runs; GPU_HEAVY is limited by a heavy-task budget and VRAM headroom. |
| `core/proof_store.py` | Proof root `assetlib/proof/product/{session_id}/{execution_id}/` with `proof.json` recording session_id, project_id, execution_id, unreal_pid, bridge identity, engine, active map, timestamp, per-file sha256. List/resolve are session-bound and path-traversal safe. |
| `core/session_execution.py` | `SessionRunner`: `start_project` (reuse live editor first, else per-session launch), `restart_project`, `disconnect`, `check_health` (crash detection), `run_prompt` (canonical plan → policy gate → leases → dispatch chain → validation → proof). Dispatch chain outermost→innermost: **READ_ONLY policy boundary → resource gate → project mutation guard → session identity guard → production dispatch**. Per-project mutation lease via `core/editor_lease.LeaseRegistry` (mutating exclusive per project; read-only watchers concurrent). |
| `app/session_api.py` | REST surface below. |

**Modified files:**

| File | Change |
|---|---|
| `app/served.py` | Registers the session router; adds `UA_DISABLE_WORKBOARD_AUTOPILOT=1` so a second backend instance never fights the primary over the workboard (multi-instance safety). |
| `app/api.py` | `/api/action` accepts optional `context.session_id`/`payload.session_id` and routes prompt-like actions through the session runner (fail closed on unknown session); `/api/execution/{id}` resolves session executions with their session/project context. |
| `tools/unreal/ue_listener.py` | Bridge port from `UA_BRIDGE_PORT` env (default 6766 — legacy behavior unchanged) so each editor instance can own a unique endpoint. |
| `scripts/build_product_package.py` | Packages `core/mission_policy.py` (pre-existing import hole; fixed so the packaged product closure imports). |
| `ui/aivido.html`, `ui/aivido.css`, `ui/aivido.js` | New **Sessions** screen on `/app`: project selector + register, session cards (status/bridge/PID), session detail (identity cells, prompt composer, task history, proof thumbnails, resource strip), restart/disconnect/cancel, auto-refresh while busy. |
| `tests/test_multiclient_runtime.py` | 21 hermetic tests (Phase 11 matrix + API surface + resource policy). |

## 3. Session model (Phase 1)

Each `ProjectSession` carries: `session_id`, `client_id`, `project_id`,
`project_path`, `unreal_pid`, `bridge_host/port`, `active_map`,
`engine_version`, `task_queue`, `current_execution_id`,
`visual_director_state`, `proof_root`, `created_at`, `last_seen`, `status`,
`resource_state`. No global active-project assumption leaks: sessions are
created per project, keyed by unique id, persisted per file, and the runner
only ever talks to the bridge recorded in the session. Two sessions on the
SAME project intentionally share one editor/bridge endpoint (project-scoped
locking serializes their mutations); unrelated projects always get separate
endpoints.

## 4. Project registry (Phase 2)

API (also over HTTP):

- `list projects` — `GET /api/projects`
- `register project` — `POST /api/projects/register` `{uproject_path}` (validates existence + parse + engine association; no FS traversal)
- `inspect project` — `POST /api/projects/{id}/inspect` (registry record + live bridge probe when a session is connected)
- `connect project` — `POST /api/projects/{id}/connect` (creates + starts a session)
- `disconnect project` — `POST /api/projects/{id}/disconnect`
- `start Unreal project session` — `POST /api/projects/{id}/start`

## 5. Bridge allocation model (Phase 3)

Project A → 6766, Project B → 6767, Project C → 6768 (range 6766–6799).
Allocation is safe by construction: live sockets are probed at allocation
time, a port is never shared between two projects, and a project's binding is
stable across reconnect. When a session starts for a project whose editor is
already live (e.g. the canonical editor on 6766), the runner verifies the
bridge identity and **reuses** it — no second editor, no port churn. When the
project has no editor, the runner launches UnrealEditor with a generated
per-session bootstrap (`-ExecutePythonScript`) that starts the bridge
listener on the session's port (`UA_BRIDGE_PORT`). Never is a task dispatched
to a bridge whose project/PID identity does not match the session.

## 6. Resource supervisor (Phase 6)

- Tracks CPU %, RAM, GPU used/total/utilization, active UnrealEditor PIDs, active heavy tasks.
- `SAFE_PARALLEL` (inspection, file/code work, read-only queries, lightweight editor ops) runs concurrently across sessions — projects never block each other on safe work.
- `GPU_HEAVY` (rendering, capture loops, shader compilation, heavy import, cinematic) is gated: queued when the heavy-task budget (`UA_MAX_GPU_HEAVY_TASKS`, default 1) is exhausted → `QUEUED_RESOURCE`; throttled when VRAM headroom drops below the floor → `THROTTLED`. Prevents two sessions exhausting VRAM and crashing Unreal.

## 7. Concurrency rules (Phase 7)

- Mutations on the SAME project serialize through a per-project mutation lease (owner = session, keyed by project path). A second mutating task on the same project gets a structured `PROJECT_BUSY` and is queued.
- Different projects never contend (different lease keys) — project A's lock cannot block project B.
- READ_ONLY tasks take the concurrent watcher lease and run alongside anything.
- Planner Safety is preserved: READ_ONLY is resolved by the canonical policy (`resolve_mission_mode`), enforced at the canonical plan gate (`PLAN_REJECTED`, zero steps) AND at the canonical execution boundary (`policy_guarded_dispatch`). A read-only mission can never invoke a MUTATING or UNKNOWN tool.

## 8. Proof isolation (Phase 8)

Proofs are copied into `assetlib/proof/product/{session_id}/{execution_id}/`
with a manifest recording session_id, project_id, execution_id, unreal_pid,
bridge endpoint, engine, active map, timestamp and sha256. The proof API is
session-bound: listing/resolving with another session's id returns nothing
(verified by tests and live). Project A's proof can never satisfy execution B.

## 9. Crash / restart recovery (Phase 9)

The health sweep and per-dispatch identity guard probe each session's bridge.
A dead editor / PID change / identity mismatch marks ONLY that session
CRASHED; other sessions keep working. `POST /api/sessions/{id}/restart`
reconnects a live bridge or relaunches that project's editor on its (re-)
allocated port. No global reset exists.

## 10. Remote access (Phase 10)

The backend already runs behind the Tailscale interface on this Shadow host
(100.84.156.24:8765). Clients use `http://<shadow-tailscale-ip>:8765/app`
(or the secure product endpoint). Backend host remains configurable via
`UA_HOST` / product config; the sessions surface requires only a browser.

## 11. Test results (Phase 11)

`tests/test_multiclient_runtime.py` — 21 hermetic tests, all passing (fake
bridges, fake registry, tmp stores; no editor/model touched):

| # | Scenario | Result |
|---|---|---|
| 1 | Two sessions / two projects isolated (ids, ports, paths, clients) | ✅ |
| 2 | Task A routes only to bridge A (B records zero calls) | ✅ |
| 3 | Task B routes only to bridge B | ✅ |
| 4 | Proof A cannot satisfy execution B (list + resolve + HTTP) | ✅ |
| 5 | Project A mutation lock does not block unrelated project B | ✅ |
| 6 | Same-project conflicting mutations serialize (PROJECT_BUSY) | ✅ |
| 7 | READ_ONLY policy enforced per session (PLAN_REJECTED, zero tools run; boundary still guarded) | ✅ |
| 8 | Crashed session does not kill other session; restart recovers only it | ✅ |
| 9 | Dynamic bridge allocation: distinct ports, stable re-binds, live-port skip | ✅ |
| 10 | Browser client state session-isolated (tasks, executions, proofs) | ✅ |
| + | HTTP surface: register→session→start→action→tasks→proof→resources; async poll; plan-rejection via HTTP; proof file serving 404 across sessions | ✅ |

Full suite: **875 passed, 0 failed** (includes 21 new tests; pre-existing
packaging hole in `build_product_package.py` fixed).

## 12. Live two-project verification (Phase 12) — completed

Performed on the actual Shadow host with real Unreal 5.8 editors:

| Check | Result |
|---|---|
| Project A session (ASSET_Showcase2) | READY — **reused** the live editor: bridge 127.0.0.1:6766, PID 14224, map `/Game/ShowcaseMap.ShowcaseMap`, engine 5.8.2 |
| Project B session (ASSET_P1_Smoke) | READY — **launched** a second editor: bridge 127.0.0.1:6767, PID 13724 (unique endpoint; bridge bound via per-session bootstrap) |
| Client A read-only inspect | PASS (2 steps verified, only bridge A touched) |
| Client B read-only inspect | PASS (2 steps verified, only bridge B touched) |
| Identity separation | A: Showcase2/6766/14224 · B: P1Smoke/6767/13724 — correct and distinct |
| Proof isolation | A's manifests carry session/project/execution/PID/bridge/sha256; B's proof endpoint returns none of A's |
| Cross-routing | Spawned `MultiClient_Cube` on A (PASS, spawn+verify). `get_actor(MultiClient_Cube)` → **exists on bridge A, "Actor not found" on bridge B** → ISOLATED |
| Mutation while B runs | Mutating task on A PASS; B stayed READY and passed another inspect afterwards |
| Crash isolation (live) | During bootstrap debugging, failed launches left ONLY the B session CRASHED while session A kept serving read-only inspects (also covered hermetically by test 8) |
| Persistence | Both sessions recovered READY after a backend restart (identity re-verified; allocator bindings re-hydrated) |

Note: Project B's bare editor has no native viewport-capture plugin, so its
headless capture produced no image (a project capability gap, not an
isolation gap — the proof pipeline correctly refused to record a missing
file; hermetic tests prove capture→isolated-proof recording).

## 13. Browser-only workflow (Phase 13)

`/app` → **Sessions** rail → register a project (paste a `.uproject` path) →
**＋ New Session** (starts/reuses the editor + bridge) → type a prompt →
watch status/tasks/proofs → done. No terminal, no Codex/Freebuff, no local
tools on the client machine.

## 14. Remaining blockers

- **Second-editor captures**: a bare Unreal project without the
  `UnrealAgentBridge` plugin falls back to EditorAutomation capture, which
  needs a visible/rendering viewport. Projects created with the canonical
  `create_project` tool carry the plugin and capture fine. Recommended: keep
  the bridge plugin enabled for every project you want to prove visually.
- **Two backends**: running a second backend instance for validation required
  `UA_DISABLE_WORKBOARD_AUTOPILOT=1` (implemented); the production backend
  remains the single owner of the workboard queue.
- **GPU budget**: default heavy-task budget is 1; raise via
  `UA_MAX_GPU_HEAVY_TASKS` on machines with more VRAM headroom than the A4500.

## 15. Commit / push status

- Commit: the HEAD commit of this work (see `git log -1`).
- Push status: **NOT pushed** (per instruction). Validated locally; the
  production backend on :8765 needs a restart to serve the new
  `/api/sessions*` surface (sessions persist on disk and re-verify on boot).