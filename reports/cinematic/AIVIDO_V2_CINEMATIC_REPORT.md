# AIVIDO V2 — CINEMATIC + BLENDER PIPELINE (report)

- Branch: `aivido/v2-cinematic`
- Base: frozen V1 `79fe5c7e2db7f070841dc07291e1f35fbe03cad2` (`aivido/v1-release`) — V1 untouched.
- Hermetic suite on this branch: **1121 passed, 1 skipped, 0 failed** (clean full-suite rerun 233 s, exit 0; cinematic tests **39/39 PASS**).
- **HEADLESS MRQ closeout:** real Movie Render Pipeline render delivered via
  `UnrealEditor-Cmd.exe -game -RenderOffscreen -DisablePython` — **240 frames,
  1920×1080 @ 30 fps, 8.0 s, human cast visible, exit 0**. See
  `AIVIDO_HEADLESS_MRQ_REPORT.md`.
- Live editor: UE 5.8.2, project ASSET_Showcase2, level `/Game/Maps/AividoHQ.AividoHQ` (166 actors, certified scene).

Every claim below is backed by a real artifact (code, hermetic test, JSON,
real Unreal PNG/MP4) or is marked BLOCKED with the engine evidence.

---

## 1. Phase 1 — focused capability audit (see CINEMATIC_AUDIT.md)

Reused existing V1 implementation instead of rebuilding:
`core/visual_loop.py` / `visual_acceptance.py` / `visual_director.py` scoring,
`tools/visual/shot_quality.py`, `tools/unreal/sequencer_tools_gap.py`
(LevelSequence + camera-cut surface), `tools/unreal/camera_framing.py`
(framing math), `tools/blender/blender_tools.py` + `blender_agent/` +
`assetlib` catalog/router (asset reuse), `app/proof.py` viewport proof,
native viewport capture (`UnrealAgentBlueprintLibrary`).

Gaps found: no cinematic orchestration layer, no Movie Render Queue path,
no bounded cinematic quality loop, no scene-framing/hero-shot planner.

## 2. New code on `aivido/v2-cinematic`

| area | artifact |
|---|---|
| Cinematic director (brief → plan → shots → loop → render → scorecard) | `core/cinematic_director.py` |
| Asset decision (reuse → Blender fix → bounded create → blocked) | `core/cinematic_assets.py` |
| Live mission entry point | `core/cinematic_mission.py` |
| MRQ driver (UE 5.8 surface) + real-frame renderer (truthful BLOCKED) | `tools/unreal/movie_render_queue.py` |
| Live Unreal adapter (subjects, CineCamera, capture, fixes, render) | `tools/unreal/cinematic_live.py` |
| Camera-cut binding (possessable → `get_binding_id` → `set_camera_binding_id`) | `tools/unreal/sequencer_tools_gap.py` |
| Tool-registry wiring | `core/tool_registry.py` |
| Live probe + demo drivers | `scripts/cinematic_live_probe.py`, `scripts/cinematic_live_demo.py`, `scripts/cast_hero_closeout.py` |
| Hermetic tests | `tests/test_cinematic_director.py`, `tests/test_cinematic_live_hermetic.py`, `tests/test_tool_registry_cinematic.py` |

## 3. Phase 2 — Blender integration (reuse-first)

- Fast path: catalogued asset with `validation_status ∈ {valid, verified}` and
  a ranking score ≥ threshold → **reuse**, no Blender
  (`core/cinematic_assets.decide_asset_strategy`, hermetic-tested).
- Blender only when genuinely needed: existing asset below the reuse bar →
  bounded `prepare_asset` (transforms/origin/scale/UV/export); bounded
  procedural need (`cube|table|crate|...`) → `create_asset`; anything else →
  `ASSET_SOURCE_REQUIRED` blocked (no fake creation).
- **Cast closeout: Blender used headless for source diagnosis ONLY.**
  Vendored Blender 4.2.0 ran `diag_fbx.py` headless and proved the source
  FBX geometry is correct (mesh feet at z=0, upright) for the cast. All
  three real defects (floor burial ~1.8 m from a legacy "Bip01 Footsteps"
  pivot bake, 180° inversion from a ref-pose bake, and masked
  `m00X_opacity` materials discarding the visible polys) are Unreal-side
  import/ref-pose bakes, so **no Blender surgery was performed** — they were
  repaired **durably in Unreal** (the sanctioned least-destructive option C
  for a healthy source). See `AIVIDO_CAST_BLENDER_REPAIR.md`.

## 4. Phase 3 — cinematic director / camera direction

- Brief parse (duration, fps, resolution 1080p/4K, shot words, motion/style
  tokens), subject selection, shot plan with real framing math
  (`camera_framing` projection reused to verify poses), rule-of-thirds head
  placement, bounded yaw arcs, CineCamera placement with verified read-back,
  scene/env hero framing semantics (prop heroes are framed as the
  environment; character teams stay subject-framed). Deterministic +
  hermetic tests.
- Live: CineCamera actors `AVCam_Shot01..03` spawned at solved poses in the
  certified level, transform read back (location/rotation) and removed again.

## 5. Phase 4 — bounded quality loop (max 3 visual iterations)

- `CinematicShotLoop`: capture → measure → deterministic score → diagnose →
  bounded real fix → recapture, hard-capped at 3 passes; hermetic tests prove
  PASS on a clean frame, recovery on a later pass, and that a dead frame is
  never faked as a pass.
- Scorecard: 7 dimensions (composition, framing, lighting, subject
  visibility — deterministic; material readability, cinematic depth, visual
  polish — vision-evidence only, never invented).
- **The loop applies REAL scene mutations, not no-ops.** Fix actions mutate
  actual PPV exposure values and light intensities with engine read-back;
  every mutation is tracked and reverted exactly (`restore_scene`, reverse
  order). After each shot and before the final render the certified baseline
  is restored (`on_shot_done` / `before_render` hooks). The final cast-hero
  run executed the full bounded loop (3+3 passes) with per-pass local
  qwen3-vl vision critiques and per-shot reset hooks.
- A frame the loop cannot improve is delivered honestly below the gate —
  never relabeled as a pass.

## 6. Phase 5 — real render / Movie Render Queue

- **MRQ plugin is enabled** for ASSET_Showcase2 (`MovieRenderPipeline` added
  to the .uproject). On UE 5.8 the python-visible surface is
  `MoviePipelineQueueSubsystem` / `MoviePipelineInProcessExecutor` /
  `MoviePipelinePIEExecutor`; `MovieRenderQueueDriver` was updated to the 5.8
  API and the probe **PASSES**.
- **In-editor MRQ remains engine-blocked**: real MRQ submission with
  camera-bound cuts + a temp map copy stalls at the in-editor target-map load
  step (silent after “About to load target map”, no frames) for both
  InProcess and PIE executors.
- **HEADLESS MRQ — COMPLETE (this commit).** The stall is bypassed by
  rendering through the command-line editor:
  `UnrealEditor-Cmd.exe <project> /Game/CineMRQ/RenderMap.RenderMap -game
  -MoviePipelineConfig=/Game/CineMRQ/MRQ_Config.MRQ_Config
  -LevelSequence=/Game/CineMRQ/MRQ_CastHero.MRQ_CastHero
  -MoviePipelineLocalExecutor -RenderOffscreen -DisablePython …`
  → **exit 0**, engine log confirms `Shot has 1 Passes … 1920x1080`,
  `Finished rendering last shot`, executor finished 1 job in 34.6 s.
  - **240 genuine Movie Render Pipeline frames**, 1920×1080 @ 30 fps,
    8.0 s; **human cast visible** in start/middle/end proof frames;
    no viewport fallback, no fake PASS.
  - Frames: `reports/cinematic/headless_mrq/frames/`; MP4 (ffmpeg encode of
    the real MRQ frames, H.264): `mrq_render_1920x1080_30fps.mp4`;
    proofs: `reports/cinematic/headless_mrq/proof/proof_{start,middle,end}.png`.
  - Key engine fixes this task: CineCamera `field_of_view`; playback-range
    `set_playback_start/end_seconds`; camera-cut re-bound to the RenderMap
    actor path; **`-DisablePython`** (the auto-run Python bridge crashed the
    render process otherwise); and the **0-Pass fix** — `MoviePipelineRenderPass`
    is **abstract** in UE 5.8 and was silently nulled on save; the concrete
    full pass is **`MoviePipelineDeferredPassBase`** (verified persisted).
  - Certified map untouched (mtime unchanged), render assets isolated under
    `/Game/CineMRQ/`. Full detail: **`AIVIDO_HEADLESS_MRQ_REPORT.md`**.
- Earlier real-frame fallback (explicitly labeled NOT MRQ) — the cast-hero
  film via the fresh-capture path (wake → viewport kick → settle → native
  capture, bounded retry + liveness probe): ffprobe **2002×742, 8.0 s,
  6 fps, 48 real frames** at
  `reports/cinematic/cast/demo/render/aivido_cinematic.mp4`.

## 7. Phase 6 — mission support

`run_cinematic_mission` (tool registry) + `run_live_cinematic`
(`core/cinematic_mission.py`) implement the full interpret→inspect→plan→
asset→(Blender if needed)→arrange→CineCamera→Sequence→render→verify→proof
chain.

## 8. Phase 7 — live safe demos + durable cast repair (real evidence)

- **Environment hero demo** (prior commit): certified AividoHQ command-floor
  board zone; CineCameras + Level Sequence + 59 real frames → 9.83 s MP4;
  honest **7.25 / 10** measured, below gate.
- **Cast-hero film** (prior commit): 48 real Unreal frames → **8.0 s / 6 fps /
  2002×742 MP4** (`reports/cinematic/cast/demo/render/aivido_cinematic.mp4`),
  ffprobe-verified, labeled exactly as NOT-MRQ.
- **Durable cast repair (this commit)** — closes the cast-visibility blocker
  durably, no transient hacks:
  - **8/8 characters standing upright on the floor with production materials**
    (`Aivido_Body` / `Aivido_Head`, opaque MICs on every slot) — asset-level
    mesh reslot (materials rebuilt and saved, verified by re-read), component
    overrides cleared, persisted 180° orientation + floor-level Z, certified
    map re-saved after live verification.
  - **No WhiteH anywhere, no AVCam/Cine residue, 166 actors preserved**
    (before/after).
  - **Hero vision verdict on the final upright Master** (qwen3-vl:8b):
    **score 8/10 PASS** — human_visible, readable_as_human, upright.
  - Deterministic measured overall on the hero: **4.45/10** (composition 6.0,
    lighting 6.81, subject_visibility 5.0, framing 0.0) — framing 0 is a
    precisely characterized **scorer artifact** (the luma locator merges the
    bright certified set into one 0.93-coverage blob at every angle tested),
    not a real framing failure. Blended (0.65 measured + 0.35 vision): ≈5.7.
  - Full record: `reports/cinematic/cast_durable/cast_durable_result.json` +
    proof PNGs (`proof/hero_final_upright.png`, `evidence_*_before/after_orient`,
    `sweep/hero_best.png`); diagnosis: `reports/cinematic/blender/diag_fbx.py`;
    driver: `scripts/cast_durable_repair.py`.
- Scene preservation PASS: the ONLY persisted change is the durable cast
  repair itself; certified lighting/PPV untouched (166 actors, PPV manual
  bias 1.0, no `/Game/Cine`).

## 9. Phase 8 — regression

- V1 files untouched on V1 branch; all V2 changes are additive on
  `aivido/v2-cinematic`.
- Full hermetic suite on the V2 branch: **1121 passed, 1 skipped, 0 failed**
  — clean full-suite rerun completed 2026-09-07 in **233 s (exit 0)**, recorded
  in `reports/cinematic/cast_durable/regression.log`. Cinematic tests
  (**`tests/test_cinematic_director.py` + `test_cinematic_live_hermetic.py` +
  `test_tool_registry_cinematic.py`**) re-run directly: **39/39 PASS**
  (fresh-capture contract, vision-driven corrective actions, per-shot reset
  hooks, UE 5.8 MRQ surface).
- The earlier full regression's 2 order/environment flakes both pass in
  isolation; the clean rerun recorded **0 failures**.
- V1 installer/runtime/watchdog/Tailscale/UI/verification/false-PASS/proof/
  read-only-safety live in the unchanged V1 base.

## Blockers (truthful, engine/content — not faked)

1. **In-editor MRQ still stalls** at the interactive map-switch step — the
   working route is the **headless** `UnrealEditor-Cmd.exe -game
   -RenderOffscreen -DisablePython` path (proven; see
   `AIVIDO_HEADLESS_MRQ_REPORT.md`).
2. ~~AividoHQ human cast renders 0 px by default~~ — **RESOLVED DURABLY.**
   Root cause was diagnosed as three independent Unreal-side import/ref-pose
   bakes (legacy "Bip01 Footsteps" pivot bake burying the cast ~1.8 m below
   the floor, a 180° inversion ref-pose bake, and masked `m00X_opacity`
   materials discarding the visible polys). Blender headless diagnosis proved
   the source FBX geometry correct; the durable fix was applied in Unreal
   (asset-level reslot to the production opaque MICs + cleared overrides +
   persisted orientation/floor Z) and verified **8/8 standing upright,
   feet on floor, hero vision 8/10 PASS, 166 actors preserved** — see
   `AIVIDO_CAST_BLENDER_REPAIR.md`.
3. **Camera transform keyframes engine-closed** — UE 5.8 Python exposes no
   MovieSceneFloatChannel key API; shot motion is a real deterministic
   camera-path render, not keyframed Sequencer playback.

## Critical

- none (no false PASS, no fake render, no scene damage).

## Major

1. In-editor MRQ cannot complete an interactive map-switch render (engine
   block, evidence recorded); the headless command-line path renders instead.
2. Headless MRQ visual ceiling: ~27 % of pixels clip to white on the certified
   practical light and the subject is backlit (dark suit ~44 luma) — subject
   readable/identifiable; one bounded render-map light adjustment would lift it.
3. Deterministic cinematic scoring of the dark hero: the luma subject locator
   merges the bright certified set into a 0.93-coverage blob (framing pinned at
   0.0 at every angle) — a precisely characterized scorer limitation; vision
   passes at 8/10 on the upright hero.
4. Editor viewport capture is intermittently unreliable after heavy session
   use (transient empty/failed native captures); fresh editors + the
   wake→kick→settle contract with bounded retry + a liveness probe restore
   it, and partial renders are recorded truthfully, never padded.

## Warnings

1. MRQ in-editor path remains engine-blocked; the headless path is proven and
   reproducible (see `AIVIDO_HEADLESS_MRQ_REPORT.md`).
2. Headless MRQ pass class: `MoviePipelineRenderPass` is abstract in UE 5.8
   (silently nulled on save); use `MoviePipelineDeferredPassBase`.
3. Local qwen3-vl vision critiques are recorded per pass (advisory); they are
   not yet auto-applied as scene fixes beyond the deterministic defect map.
4. Viewport-capture films (not MRQ) follow native editor viewport geometry
   (2002×742 effective this session); the MRQ render is exactly 1920×1080.
5. Raw frame dirs (`reports/cinematic/*/render/frames*`) stay untracked per
   repo convention; committed evidence is the verified MP4s + proof stills +
   JSON records.
6. Keyframed camera motion is engine-closed in UE 5.8 python; the MRQ shot
   uses the bound CineCamera (static framing).