# Aivido UI/UX Phase 2 — Report

Branch: `aivido-uiux-phase1` (worktree `C:/Users/Shadow/Desktop/Unreal-Agent-uiux-phase1`)
Phase-1 commit: `bfc6700` (untouched). Production branch untouched. Nothing pushed.

## Completed features

### 1. MetaHuman / character cast contract
- Cast & Assets panel on Workspaces (7 slots, one per worker identity from Phase 1).
- Each slot: role, MetaHuman slot id (`mason.environment` …), truthful status
  `ASSET MISSING · CSS FALLBACK`, and the **real import contract** — the actual
  character tools discovered from the live tool registry (`discover_character_assets`,
  `inspect_character_asset`, `install_character_assets`, `spawn_character`,
  `verify_character_visible`, `assign_animation`, `blender_prepare_character`).
- Worker dossier modal in the Agent Room (click any worker): state, foreman line,
  MetaHuman slot contract, Phase-2 import path.
- Nothing fabricated: slots are real integration points, availability is honestly
  `ASSET MISSING` until assets exist.

### 2. Live mission dispatch (canonical execution path)
- Mission Control → **Dispatch Lane**: two modes.
  - **Code task** (safe, deterministic): POST `/api/code/tasks` — runs in the
    product's isolated git worktree on its own branch; never touches the live
    checkout or the editor. Full lifecycle QUEUED → RUNNING → COMPLETE/FAILED/BLOCKED.
  - **Unreal mission**: POST `/api/unreal-coder/async` (the exact async path the
    ClickUp MCP gateway uses) with an explicit risk warning + confirm dialog
    (live-editor missions can spawn/change actors) and a **Preview plan (dry-run)**
    button that calls POST `/api/unreal-coder {dry_run:true}` and shows the real
    planner output (status/phases/capabilities/visual gate) before anything runs.
- No second execution system: the Booth calls the product's canonical endpoints only.
- UI renders backend state verbatim — it never synthesizes DONE.

### 3. Mission Inspector + Visual Director evidence
- Lifecycle chips mapped from real backend statuses (interpreting→QUEUED,
  planning→PLANNING, executing→RUNNING, validating→VALIDATING, repairing→FIXING,
  complete→COMPLETE, failed→FAILED, blocked→BLOCKED, CANCELLED).
- Renders verbatim from the canonical checkpoint (`GET /api/unreal-coder/mission/{id}`
  and `GET /api/code/tasks/{id}`): verdict, why, plan phases, steps completed/total,
  evidence, warnings, remaining issues, artifacts, mission_log path.
- Visual Director data comes from the backend: measured visual score, required
  floor, PASS/FAILED/BLOCKED verdict, proof freshness, proof preview, environment
  requirement — all as reported by the pipeline (verified live, see below). No
  frontend scoring anywhere.
- Real controls: Cancel (async, backend finalizes as CANCELLED never SUCCESS),
  Run validation, Resume, Retry/Cancel for code tasks.

### 4. ClickUp integration
- Detection: the Booth probes the live registry (`POST /api/action tools_list`).
- Result: **BLOCKED, truthfully** — 109 tools registered, none ClickUp; no
  credentials exist in this environment. Settings shows the exact credential
  contract (`CLICKUP_API_TOKEN` + `CLICKUP_LIST_ID` or a gateway ClickUp tool)
  with no secrets and no fabricated sync success.

### 5. Workspace / project connect
- Live workspace card: real project, branch, commit, engine version, active map.
- System strip (top of every screen): engine linked/busy/offline, bridge ready/
  no session/unavailable, active map, proof fresh/STALE, execution active/none —
  all truthful states from real endpoints.

### 6. Quests backend abstraction
- Durable local store (`aivido_quests_v1`, versioned, labeled LOCAL) replacing
  throwaway demo ticks. Quest steps tick from **real events** (proof captures,
  crew dispatches, engine dispatches). The "live proof ≥ 8.5" step stays pending
  until a LIVE proof with a real score ≥ 8.5 exists — no fabricated completion.

### 7. Finance backend contract
- Ledger now separates **LOCAL (real actions this session)** from **DEMO seed**,
  each row labeled. Real actions (proof captures, dispatches, demo rewards) are
  recorded with timestamps in a durable store (`aivido_ledger_v1`). Billing is
  explicitly labeled FUTURE — not wired; credits are session-local. No fake
  transactions.

### 8. Product audio
- Curated WebAudio hooks: navigation, confirm/error/success, proof capture,
  mission dispatch. HUD ♪ + Settings mute, persisted, non-intrusive (short,
  quiet, synthesized).

### 9. Product route serving
- **Additive `GET /app`** in the product backend (`app/api.py`) serving the Booth;
  static assets resolve through the existing `/static` mount; all `/api/*` calls
  are same-origin. Dev server mirrors `/app` for development. Verified: `/app`
  returns the Booth HTML; `py_compile` passes on both files.

### 10. Error / offline / recovery UX
- Truthful states everywhere: engine offline (dispatch blocked + toast), bridge
  unavailable, no editor session, proof STALE, task blocked/failed/retrying,
  integration unavailable (ClickUp BLOCKED), empty workspace/board — all shown
  with their real backend values; none converted to fake success.

### 11. Responsive / desktop polish
- Mission Inspector + Proof Vault remain usable at narrower desktop widths
  (column layouts at ≤1250px and ≤900px), dispatch modes stack, system strip
  wraps. Visual identity unchanged.

### 12. Demo vs live truthfulness
- Every UI data source is labeled LIVE / DEMO / BLOCKED / FUTURE. Demo lane,
  demo workspace cards, demo proof frames, demo ledger rows, LOCAL quests are all
  explicitly tagged. No demo data presented as live; no live data demoted.

## Live integrations working (read-only + canonical dispatch)

`/api/status` · `/api/unreal-coder/session` · `/api/workspace` · `/api/code/tasks`
(+ `/evidence`, `/retry`, `/cancel`) · `/api/workboard/state` · `/api/unreal-coder/async`
+ `/mission/{id}` (+ `/validate`, `/resume`, `/cancel`) · `/api/unreal-coder`
(dry-run plan) · `/api/action tools_list` (registry) · `/api/proof/status` +
`/api/proof/latest` · `/api/unreal/frame-and-proof` · product route `GET /app`.

## Blocked external dependencies

- **ClickUp**: no credentials/tool anywhere in this environment — BLOCKED state +
  credential contract provided. Not blocking Phase 2.

## Real mission-dispatch verification (controlled, safe)

1. Dispatched **code task ct0005 through the Booth UI** (Dispatch Lane → Code task):
   `POST /api/code/tasks` → QUEUED → RUNNING → **COMPLETE / PASS**, real commit
   `5c99b5fce35f` on branch `aivido/code-task/ct0005`, 2 checks, 2 acceptance
   conditions, 2 evidence files — all rendered by the Mission Inspector.
2. Unreal-lane contract verified against the canonical async path: mission
   `mission_01e545b5598f` accepted, planned, executed, validated, and reached a
   real terminal state — **complete | PASS | "All 6 steps verified; visual score
   6.12 >= floor 6.00"** (Visual Director measured score vs required floor from
   the pipeline). Cancel/validate/resume endpoints contract-checked.
   - Note: the universal planner did not honor a "READ ONLY" prompt and planned
     three spawn steps. The Booth therefore defaults to the safe code lane and
     gates the Unreal lane behind the dry-run preview + explicit confirm + cancel.
   - The three spawned actors were removed surgically via the bridge
     `delete_actor` tool (by unique internal name), absence verified, level never
     saved. Editor scene restored to its pre-probe state (ASSET_Showcase2,
     ShowcaseMap).

## Demo / fallback areas remaining (labeled)

Demo mission lane · demo workspace cards · demo proof capture (engine offline) ·
CSS-figure crew until MetaHuman assets land (ASSET MISSING, contract shown) ·
session-local credits (billing FUTURE) · LOCAL quests.

## Validation

- `node --check ui/aivido.js` — PASS (after every edit batch)
- HTML↔JS ID/reference cross-check — PASS (no missing ids)
- `git diff --check` — PASS
- `py_compile` on `app/api.py` + `scripts/aivido_dev_server.py` — PASS
- Browser console during full route walk — zero errors
- Routes walked: Home, Workspaces (cast grid), Mission Control (dispatch lane,
  inspector), Agent Room (dossier), Proof Vault (age chip), Quests (LOCAL ticks),
  Finance (real/demo ledger), Profile, Settings (ClickUp contract + integrations)

## Screenshots / evidence

Captured in the Freebuff thread Preview tab: `#/mission` (dispatch lane + live
lane with ct0005 COMPLETE/PASS), `#/workspaces` (cast & assets), `#/room`
(dossier), `#/proof` (LIVE FRAME + freshness), `#/settings` (ClickUp BLOCKED
contract).

## Remaining product gaps (Phase 3+)

- MetaHuman asset install + wardrobe pass (real asset work, not UI)
- ClickUp posting with real credentials
- Billing/credits backend (FUTURE label until it exists)
- Quest/ledger remote store (currently durable local, clearly labeled)
- WebSocket event stream for push updates (Inspector currently polls)

## Verdict

Phase 2 complete. The Booth dispatches through the canonical backend, renders
real lifecycle/Visual Director evidence verbatim, labels every data source
truthfully, and ships an additive `/app` product route. Safe for push review.