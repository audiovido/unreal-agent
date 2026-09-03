# UNREAL CODER — Universal Upgrade Plan

## Repository audit (2026-09-02, base commit 2075e24)

Existing, verified and PRESERVED:

- **Public API surface** (`app/api.py` FastAPI, `app/served.py` composition root):
  `/api/chat` (chat/plan/execute routing), `/api/status`, `/api/proof/*`,
  workboard/plan/selftest routers, approval policy, events.
- **Orchestrator** (`core/orchestrator.py`): `classify_intent` (chat/plan/execute),
  model routing (fast/reasoning/coder/vision via Ollama), `create_execution_plan`,
  `guard_tool_call`, executor guard rails.
- **Executor** (`app/api.py::run_execution_until_pause`): deterministic step
  dispatch (`_deterministic_step_dispatch`), dependency-ordered normalized steps
  (`normalize_execution_plan`), no-progress stall detection, cleanup machinery,
  terminal exactly-once semantics.
- **Tool registry** (`core/tool_registry.py`): 100 `ToolSpec`s — project manager,
  bridge tools, Blueprint/UMG/chat, avatar, runtime verification, import
  (FBX/GLTF), Blender (create/convert/prepare/inspect/jobs/recover), world,
  sequencer, materials, Niagara, terrain, MetaHuman, camera framing.
- **Bridge** (`tools/unreal/unreal_bridge.py`): TCP JSON bridge, `execute_python`,
  project identity verification, save/map verification contracts, PIE control,
  native viewport capture. Live on port 6766, UE 5.8.2.
- **Visual pipeline** (`core/visual_director.py`, `core/visual_acceptance.py`,
  `core/visual_loop.py`): VisualTarget from natural language, deterministic
  image measurement, defect->bounded-action chains, completion gate.
- **Acceptance contracts** (`core/task_goal.py`): durable parent goal,
  `build_acceptance_contract`, per-step `reconcile_step`, `contract_complete`.
- **Project context** (`tools/unreal/project_context.py`): durable active-project
  resolution chain incl. live bridge identity.
- **Blender Agent** (`blender_agent/*` + `tools/blender/blender_tools.py`):
  headless job lifecycle with validation + manifests.
- **Tests**: 303 pytest tests green (unit/integration, mocked bridge).

## Gaps this upgrade closes (extension, not rebuild)

1. **L1 Universal intent** — chat/plan/execute exists; no structured multi-domain
   intent (domains, quality mode, deliverables, validation needs).
2. **L2 Requirement expansion** — vague prompts are not expanded into requirement
   specs with safe defaults.
3. **L3 Universal planner** — planning is prompt-driven with per-feature
   deterministic fragments; no dependency-aware capability-selected mission plan.
4. **L4/5/6 Capability registry + specialist routing** — tools exist but there is
   no discoverable capability layer (mutates/editor/visual/recovery metadata).
5. **L7 Asset intake** — import tools exist; no pre-import inspection/repair
   routing/provenance.
6. **Single canonical API** — must add `POST /api/unreal-coder` that composes
   L1..L7 on top of the existing executor and visual loop.
7. **Mission checkpoint/resume + loop protection + error classification** —
   partial (task_goal, stalls); formalize as a mission layer.

## Rule

Every new layer delegates execution to the EXISTING registry/executor/visual
loop. No parallel implementation. Existing APIs keep their behavior.
