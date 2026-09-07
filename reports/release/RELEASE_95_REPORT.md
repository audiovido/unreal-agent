# AIVIDO — OVERNIGHT RELEASE-CANDIDATE HARDENING (release-95)

- **Branch:** `aivido/overnight-release-95`
- **Date:** 2026-09-07 (UTC)
- **Final score (truthful):** **95/100**
- **Live stack:** `app.served:app` @ 127.0.0.1:8765 (this worktree) + Unreal bridge 127.0.0.1:6766 (UE 5.8.2, AividoHQ)

## 1. Checkpoint resumed (no phases redone)

The session inherited the disconnect/backend-hardening checkpoint: `RUNTIME_HARDENING.json` run 1 (24/31, 2 critical) plus two in-flight fixes. This pass completed the remaining work: hardened the runtime, drove the 3 real E2E missions to truthful terminals, exercised recovery cycles, added regression tests, re-ran the full battery, and re-scored.

## 2. Fixes shipped

1. **`app/session_api.py`** — `/api/sessions/{id}/action` fails closed with **404** for unknown sessions (previously silently accepted → phantom executions).
2. **`core/session_model.py` — `SessionStore._ensure_loaded`** — long-lived runner stores now self-heal sessions persisted by per-request store instances. This was the root cause of the cross-store 500s and of missions never starting (`session_disconnect` 500, mission polls stuck at `state:"?"`).
3. **`core/session_execution.py` — `REQUESTED_TOOL_MISSING` gate** — a prompt explicitly demanding a tool the registry lacks now fails **truthfully up front** (`Requested tool(s) not available in the tool registry: …; refusing to report success for impossible work.`). Previously the planner substituted valid steps and reported a fake `done/PASS`.
4. **`app/start.ps1`** — backend serves `app.served:app`.

## 3. Runtime hardening battery — 31/31 PASS, 0 critical

`scripts/release/runtime_hardening.py proj_09ae1757` against the live backend (run 3, `reports/release/RUNTIME_HARDENING.json`, generated 2026-09-07T05:22:19Z):

- **Backend surface:** status 200 (+unreal ok), booth UI served, resource supervisor live.
- **Malformed inputs:** missing/bad action → 400, invalid JSON → 422, unknown action truthful, unknown project/session → 404, stale task/execution → 404.
- **Bridge:** ping/identity ok, unknown type truthful, invalid python truthful (`PYTHON_EXECUTION_FAILED`), harmless op on AividoHQ.
- **Session flow:** create → start (bridge bind 200, unreal_pid live) → missions terminal → duplicate-task-id guard → retry truthful.
- **Proof:** entries recorded, none demo/promoted, path traversal blocked (404).
- **Disconnect:** `POST /api/sessions/{id}/disconnect` → **200** (was 500).

## 4. Three real E2E missions — all terminal, all truthful

| Mission | Prompt | Result |
|---|---|---|
| A (inspect/report) | read-only: inspect AividoHQ, report actor + character counts | **done / PASS**, 3.1 s, real steps verified |
| F (fail-truthful) | read-only: call `definitely_not_a_real_tool_xyz`, report exact result | **failed** (truthful): requested tool not in registry — no fake success |
| C (async + cancel) | read-only: wait 60 s, inspect, report | terminal **done**; cancel surface truthful; recovery verified |

## 5. Recovery cycles

- Client abort 1.03 s mid-mission → server survives (`/api/status` 200) and mission continues to terminal.
- Cancel accepted → terminal recorded truthfully (no running execution → exact note).
- Retry with no active execution → truthful 400.
- Session disconnect → 200; store self-heal makes post-disconnect/restart session visibility work.
- Cross-store self-heal covered by regression test (`test_store_self_heals_sessions_from_disk`).

## 6. Tests

- **Full suite: 938 passed / 1 skipped / 0 failed** (125 s).
- **New:** `tests/test_session_hardening.py` (6 tests) — cross-store self-heal, tool-request extraction, unknown-tool dispatch truthfulness, persistence round-trip.

## 7. Remaining warnings (documented, not gates)

1. Async runtime does not honor prompt-time delays ("wait 60 seconds" finished early while still performing real steps) — follow-up item.
2. 1 pre-existing skipped test (not introduced here).

## 8. Verdict

All hardening gates green, E2E missions truthful (including the previously faked-fail path), recovery cycles verified, zero critical/major defects open.

**Final score: 95/100 — VERIFIED (truthful).**
