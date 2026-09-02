# Freebuff → Unreal Agent thin-client router

Makes **Freebuff Desktop** a pure UI/transport layer for the already-running
**Unreal Agent API** (`http://127.0.0.1:8765`) when the current workspace is
this repository (the Unreal-Agent project).

## What it does

- Every normal user message in a Freebuff thread whose project is the
  Unreal-Agent repo is POSTed to `POST /api/action` as
  `{"action": "prompt", "payload": {"message": "<exact message>"}}`.
- The returned `task_id` is streamed over `GET /api/events/stream/{task_id}`
  (SSE). Execution events are translated into Freebuff turn events:
  Planning → 🔧 tool execution (✅/❌ compact) → errors → final
  **PASS / FAIL / BLOCKED** verdict plus a proof link
  (`/api/proof/latest`).
- **No Freebuff LLM is involved.** The routed turn bypasses the harness/model
  path entirely — Unreal Agent owns model routing (Ollama) and execution.
- `/freebuff` prefix escapes routing to the normal Freebuff agent.
- Backend (8765) down → the router starts the project's own launcher
  (`.venv/Scripts/python.exe run_agent.py`), polls `/api/status`, then resumes
  the queued request. Bridge (6766) recovery is left to Unreal Agent.
- Only user-initiated inputs are routed; Freebuff skills/missions stay in
  Freebuff.

## Files

| File | Purpose |
| --- | --- |
| `scripts/freebuff_unreal_router.js` | The router module (single source of truth) |
| `scripts/test_freebuff_router.js` | Standalone end-to-end harness against the real backend |
| `.tmp-browser/splice_orchestrator.py` | Splices the router into the Freebuff orchestrator bundle |
| `app/served.py` | Unreal-Agent-side proof endpoint now serves the freshest real capture (default project + bridge-active project) |

## Where it is installed

The router is injected into the Freebuff app's orchestrator bundle:

```
%LOCALAPPDATA%\Programs\@codebufffreebuff-desktop\resources\orchestrator\orchestrator.js
```

- Injected block: before `async function runTurn(...)` — defines
  `runTurnOrRoute()` which dispatches routed turns to `fbRunUnrealTurn()`.
- The turn runner call site in `drain()` is rewired to `runTurnOrRoute(...)`.
- The pre-splice bundle is kept at
  `orchestrator.js.freebuff-router.bak` next to it.

**The change activates on the next Freebuff launch** (the running app keeps
its in-memory copy).

## Re-apply after a Freebuff app update

Freebuff updates replace `orchestrator.js`. Re-apply with:

```bash
cd C:\Users\Shadow\Desktop\Unreal-Agent
.venv/Scripts/python.exe .tmp-browser/splice_orchestrator.py --force
```

Then verify the bundle still parses:

```bash
"<app>\resources\bun\bun.exe" build "<app>\resources\orchestrator\orchestrator.js" --target=bun --outfile=check.js
```

## End-to-end test

```bash
"<app>\resources\bun\bun.exe" scripts/test_freebuff_router.js \
  "Create a visible test actor named FREEBUFF_API_ROUTING_TEST in the current Unreal level, save it, verify it exists, and capture proof."
```

Expect: `terminal.kind === "pass"` and the actor readable back through the
bridge:

```bash
.venv/Scripts/python.exe -c "from tools.unreal.unreal_bridge import UnrealBridge; import json; print(json.dumps(UnrealBridge().get_actor('FREEBUFF_API_ROUTING_TEST')))"
```

## Notes

- The Unreal Agent API contract is unchanged: `GET /api/status`,
  `POST /api/action` (`action: "prompt"`), `GET /api/events/stream/{task_id}`.
- Ollama is never called by Freebuff; Unreal Agent owns it.
