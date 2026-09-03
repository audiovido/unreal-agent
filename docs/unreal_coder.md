# UNREAL CODER — Universal Unreal Engine Agent Platform

ONE INPUT + ONE API + ONE AGENT.

`UNREAL CODER` is the universal, project-independent layer over the existing
Unreal Agent. A user describes an Unreal task in ordinary language — however
vague — and the system determines the required work, plans it, selects
capabilities/tools/models, executes through the proven Unreal machinery,
validates in the live editor, visually inspects results, repairs failures,
collects evidence, and returns a clear result.

It is NOT an Audiovido feature, NOT a single-game feature, NOT a Cinema
feature: it is infrastructure for MANY USERS and MANY PROJECT TYPES.

---

## The single API

```
POST /api/unreal-coder
{
  "prompt": "make me a beautiful sci-fi main menu"
}
```

That is the entire required contract. The response:

```json
{
  "mission_id": "mission_1f70752b3fb6",
  "status": "complete",              // interpreting|planning|executing|validating|repairing|complete|failed|blocked
  "verdict": "PASS",                 // PASS | PARTIAL | FAIL | BLOCKED | null
  "why": "All 6 steps verified; visual score 7.60 >= floor 7.50.",
  "interpretation": { "domains": ["ui"], "primary_domain": "ui",
                      "quality": "high", "deliverables": ["menu"] },
  "plan": { "phases": [...], "selected_capabilities": [...],
            "visual_gate": {...} },
  "completed_work": { "steps_total": 8, "steps_completed": 8, "step_ids": [...] },
  "evidence": [ { "path": ".../viewport_latest.png", "ok": true } ],
  "warnings": [],
  "remaining_issues": [],
  "artifacts": [],
  "resumable": false
}
```

Internal chain-of-thought is never exposed — concise summaries only.

### Optional advanced fields (never required)

```json
{
  "prompt": "...",
  "project": "C:/path/MyGame.uproject",
  "assets": ["C:/assets/SciFiCrate.obj"],
  "quality": "cinematic",            // prototype|standard|production|high|cinematic|photoreal|performance
  "platform": "mobile",              // windows|mobile|console|vr
  "constraints": {"no_delete": true},
  "mode": "chat|plan|execute",       // override automatic routing
  "mission_id": "mission_...",       // resume an interrupted mission
  "dry_run": true                    // interpret + plan only, no execution
}
```

### Companion endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/unreal-coder/capabilities` | Capability discovery (domain, description, recovery, availability) |
| `GET /api/unreal-coder/mission/{id}` | Fetch any mission's state/result |
| `POST /api/unreal-coder/resume` | Continue from the newest checkpoint |

---

## Architecture (what runs behind the API)

```
prompt
  │
  ▼
L1 UniversalIntent          core/universal_intent.py   (deterministic)
L2 RequirementSpec          core/universal_intent.py   (safe defaults, anti-overreach)
L3 UniversalPlanner         core/universal_planner.py  (dependency-aware mission plan)
L4 CapabilityRegistry       core/capability_registry.py (discoverable, tool-bound)
   │
   ▼
MissionEngine               core/mission.py            (checkpoint/resume, loop
   │  dispatches through the EXISTING executor:      protection, error classes,
   │  app/api.py REGISTRY + step dispatcher          visual loop, evidence)
   ▼
Validation                  technical gate + visual acceptance loop
   ▼
MissionState (memory/checkpoints/unreal_coder/*.json)  → canonical response
```

Key rule: **the universal layers plan; the proven executor runs.** No parallel
Unreal implementation exists — bridge, tools, materials, sequencer, visual
director and acceptance runners are reused unchanged.

### Layer notes

- **L1 intent** classifies domains (18 specialist areas: ui, cinematics,
  gameplay, level_design, world_building, environment_art, materials,
  lighting, archviz, characters, vfx, audio, media, optimization,
  asset_pipeline, packaging, camera, general_unreal), quality mode (explicit →
  inferred → default; prototypes never get cinematic rendering), platforms,
  and needs (visual validation, Blender, assets, sequencer, UI, gameplay,
  networking, render). Mixed tasks (`"photorealistic racing game intro
  menu"`) route to several specialists at once.
- **L2 expansion** turns one vague sentence into the minimum sensible
  requirement set. `"make it prettier"` expands to environment + lighting +
  materials polish with visual validation — never to multiplayer, packaging
  or DCC work. Excluded scope is recorded, not silently dropped.
- **L3 planner** emits dependency-ordered phases (GROUND → EDIT/BUILD →
  VISUAL) with per-step stop conditions, risk flags, parallel hints, quality
  floors per mode (prototype 5.0 … photoreal/cinematic 8.0), and steps in the
  EXACT normalized schema the existing executor consumes. Tools are never
  invented: every step's tool comes from the capability's registered set.
- **L4 registry** describes 27 capabilities with metadata (mutates project,
  needs editor/PIE/build/visual validation, recovery strategy) and resolves
  availability against the live tool registry — a missing tool marks the
  capability unavailable and the planner skips it explicitly.
- **Mission engine** adds what step execution lacks: durable checkpoints
  (resume never re-runs completed validated work), loop protection (identical
  work signature > 2 → structured BLOCKED; 3 failures with no progress →
  stop), error classification (18 classes with targeted bounded recovery),
  and the bounded visual loop (capture → evaluate → repair → re-capture, max
  3 iterations, stagnation detection).

### Visual quality gate

Scores are evidence-based (deterministic image measurement first, vision
model second) and thresholds follow the requested quality mode. A mission
with a visual gate returns PARTIAL — never fake PASS — when the score floor
is not reached within the repair budget, listing remaining defects.

---

## Asset & Blender workflow

`tools/unreal/asset_intake.py` inspects files BEFORE import (never mutates
the original): kind, size, hash; OBJ parsing gives vertices/faces/UVs/
normals/bounding box → scale & orientation assessment. Weak or suspect
assets route to repair:

- `repair_route = "unreal_settings"` — fixable at import time
- `repair_route = "blender"` — scale normalization, UV generation, mesh
  cleanup via the existing headless Blender Agent tools
- `repair_route = "none"` — import directly

Provenance chains (`original → operations → output → import destination`)
are produced for every intake; user originals are never destroyed.

---

## Project routing & safety

- The active project is resolved through the existing durable context chain
  (explicit path → persisted context → live bridge identity → bounded search)
  and the bridge verifies `expected_project` on every execution.
- Destructive requests are flagged at intent level; the plan inserts a
  checkpoint step and provenance requirements before any destructive tool.
- Multi-project safety: bridge sessions are keyed to project identity; wrong
  project is a structured WRONG_PROJECT blocker, not a silent mutation.

---

## Resume / checkpoint behavior

Every state transition persists to
`memory/checkpoints/unreal_coder/<mission_id>.json`. If a process dies
mid-mission, `POST /api/unreal-coder/resume` (or `mission_id` on a new
request) continues from the latest valid checkpoint: completed validated
steps are never re-executed.

---

## Worked examples

| User says | Routing | What happens |
|---|---|---|
| "make me a beautiful sci-fi main menu" | ui (+materials/lighting for `high`) | UMG widget authored via existing widget tools, visual gate ≥ 7.0 |
| "block out a combat arena" | level_design, prototype | Fast blockout, visual floor 5.0 — no cinematic rendering |
| "make it prettier" | vague → env+lighting+materials | Minimum polish set, visually validated |
| "make a photoreal cinematic" | cinematics, photoreal | Sequencer/camera specialists + quality gate ≥ 8.0 |
| "this asset looks bad fix it" | asset_pipeline (+Blender route) | Intake analysis → repair → import → verify |
| "What is a GameMode?" | chat | Direct answer; zero environment mutation |

Personas: **UI creator** (UI-only missions never launch Blender or build
worlds), **game developer** (gameplay smoke via PIE), **cinematic creator**
(Sequencer + camera + visual gate), **architect** (archviz quality floors,
no game systems), **environment artist** (composition + materials +
lighting), **non-technical beginner** (one sentence, safe defaults).

---

## Testing & live verification

- `tests/test_universal_intent.py` — router + expander
- `tests/test_universal_planner.py` — capability binding, dependency order, no invented tools
- `tests/test_mission_engine.py` — checkpoints, resume, loop protection, visual loop, error classes
- `tests/test_unreal_coder_api.py` — the canonical endpoint (boot, envelopes, chat mode, 404s, legacy routes)
- `tests/test_cross_domain_missions.py` — 24-case generalization matrix + vague prompts
- `assetlib/reports/unreal_coder_live_acceptance.py` — LIVE runner: one real
  mission through the real capability registry and UE 5.8.2 bridge with
  independent in-editor read-back (verdict PASS recorded in
  `unreal_coder_live_acceptance.json`).

## Troubleshooting

| Symptom | Meaning / fix |
|---|---|
| `verdict: BLOCKED` with LOOP_PROTECTION | The same step kept repeating; inspect `step_results` + `loop_events` in the mission checkpoint, fix the underlying tool, then resume. |
| `verdict: PARTIAL` with VISUAL defects | Technical work verified; visuals below the quality floor after 3 bounded repairs. Defects are listed in `remaining_issues`. |
| `WRONG_PROJECT` in remaining_issues | Another project's editor owns the bridge; open the target project or pass `project`. |
| `recovery budget exhausted` | The error class's policy was spent; the checkpoint holds the exact failing step for continuation. |
