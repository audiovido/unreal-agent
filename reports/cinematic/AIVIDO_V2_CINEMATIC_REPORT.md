# AIVIDO V2 — CINEMATIC + BLENDER PIPELINE (report)

- Branch: `aivido/v2-cinematic`
- Base: frozen V1 `79fe5c7e2db7f070841dc07291e1f35fbe03cad2` (`aivido/v1-release`) — V1 untouched.
- Hermetic suite on this branch: **1119 passed, 1 skipped** (includes 37 new cinematic tests).
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
| MRQ driver + real-frame renderer (truthful BLOCKED) | `tools/unreal/movie_render_queue.py` |
| Live Unreal adapter (subjects, CineCamera, capture, fixes, render) | `tools/unreal/cinematic_live.py` |
| Tool-registry wiring (`probe_movie_render_queue`, `run_cinematic_mission`, `read_cine_camera`) | `core/tool_registry.py` |
| Live probe + demo drivers | `scripts/cinematic_live_probe.py`, `scripts/cinematic_live_demo.py` |
| Hermetic tests (37) | `tests/test_cinematic_director.py`, `tests/test_cinematic_live_hermetic.py`, `tests/test_tool_registry_cinematic.py` |

## 3. Phase 2 — Blender integration (reuse-first)

- Fast path: catalogued asset with `validation_status ∈ {valid, verified}` and
  a ranking score ≥ threshold → **reuse**, no Blender
  (`core/cinematic_assets.decide_asset_strategy`, hermetic-tested).
- Blender only when genuinely needed: existing asset below the reuse bar →
  bounded `prepare_asset` (transforms/origin/scale/UV/export); bounded
  procedural need (`cube|table|crate|...`) → `create_asset`; anything else →
  `ASSET_SOURCE_REQUIRED` blocked (no fake creation).
- V1 `blender_agent`, `blender_tools` and the `assetlib` chain are reused
  unchanged; the decision layer only routes to them.
- **Live demo result: PASS** (existing AividoHQ content reused on the fast
  path; Blender not invoked because no asset genuinely needed creation).

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
  is restored (`on_shot_done` / `before_render` hooks) so fixes are per-shot
  evidence and never accumulate into the film. The final live run recorded
  real mutations (restore counts 1/2/0 across shots) plus local qwen3-vl
  vision critiques on every pass.
- A frame the loop cannot improve is delivered honestly below the gate —
  never relabeled as a pass.

## 6. Phase 5 — real render / Movie Render Queue

- `MovieRenderQueueDriver.probe()` returns structured evidence. Live probe:
  `MovieRenderQueueSubsystem` **absent** (MovieRenderPipeline plugin not
  enabled in this project) → `render_sequence` returns truthful
  **BLOCKED (movie_render_queue)**, never a fake render (hermetic test).
- Real-frame fallback (explicitly labeled NOT MRQ): the final demo captured
  **59 REAL Unreal frames** through the same proven fresh-capture path used
  by the quality loop (wake → viewport kick → settle → native capture with
  bounded retry) along a deterministic camera pose path; delivered as an MP4
  (ffmpeg/libx264 of the real frames). ffprobe: 2002×742, **9.83 s**, 6 fps,
  59 unique frames, no duplicated frames (one transient frame-7 capture
  failure was recorded and the encode is contiguous from the 59 real frames).
- Deliverables live:
  - video: `reports/cinematic/demo/render/aivido_cinematic.mp4`
  - frames dir: `reports/cinematic/demo/render/frames/` (59 real frames)
  - proof stills: `reports/cinematic/proof/` (proof_shot1/2 + render stills)
  - full record: `reports/cinematic/demo/cinematic_result.json`

## 7. Phase 6 — mission support

`run_cinematic_mission` (tool registry) + `run_live_cinematic`
(`core/cinematic_mission.py`) implement the full interpret→inspect→plan→
asset→(Blender if needed)→arrange→CineCamera→Sequence→render→verify→proof
chain. Prompt example used live: *“Create a 10-second premium hero cinematic
of the AividoHQ command floor with cinematic lighting and smooth camera
movement.”*

## 8. Phase 7 — live safe demo (real evidence)

- Only AividoHQ content used (certified UI command boards, key-light pods,
  presentation zone — no primitive test scene). Hero subject: the
  `AIVIDO_UI_Agents_Panel` environment anchor (the only fully renderable
  certified hero in this editor state; the human cast is content-blocked —
  see Blockers).
- Level Sequence created (camera-cut sections) under `/Game/Cine/AividoV2`,
  CineCameras placed/read-back, 59 real frames rendered, all demo-created
  actors/assets **removed afterwards**; level never saved by the demo.
- Scene preservation verified after the run: 166 actors, no `AVCam_*` actors,
  PPV exposure and key light values at their certified baselines (manual
  AEM, bias 1.0; AVIDO_Key_Face 45000, AVIDO_Light_Master 26000); the empty
  demo asset folder shell was removed and the certified map re-saved clean.
- **Final measured visual score: 7.25 / 10** (honest measured dimensions;
  lighting 9.49, subject visibility 7.0, composition 6.5, framing 6.0).
  Below the 8.0 premium acceptance gate → status `DELIVERED_BELOW_GATE`,
  **no fake PASS claimed**.

## 9. Phase 8 — regression

- V1 files untouched on V1 branch; all V2 changes are additive on
  `aivido/v2-cinematic`.
- Full hermetic suite on the V2 branch: **1119 passed, 1 skipped** (37 new
  cinematic tests incl. fresh-capture contract, vision-driven corrective
  actions, and per-shot reset hooks).
- V1 installer/runtime/watchdog/Tailscale/UI/verification/false-PASS/proof/
  read-only-safety live in the unchanged V1 base; nothing in this branch
  breaks them (additive tool rows only + new modules).

## Blockers (truthful, engine/content — not faked)

1. **MRQ unavailable** — MovieRenderQueueSubsystem absent (plugin not enabled
   in ASSET_Showcase2); real Movie Render Queue render BLOCKED. Real-frame
   evidence delivered instead, labeled exactly as such.
2. **AividoHQ human cast does not render in this editor session** — proven by
   pixel-diff: toggling the hero SkeletalMesh components' visibility changes
   0 rendered pixels from any angle; bounds put four Business_Male meshes
   ~1.9 m below the floor (a per-asset pivot/state regression, matching a
   pre-existing certification warning). Lifted + forced-visible → still 0
   pixels (then reverted exactly). Team-member hero shots are therefore
   blocked at content level, not by the pipeline.
3. **Camera transform keyframes engine-closed** — UE 5.8 Python exposes no
   MovieSceneFloatChannel key API (recorded verbatim in V1); the shot motion
   in the live demo is a real deterministic camera-path render, not a
   keyframed Sequencer playback.

## Critical

- none (no false PASS, no fake render, no scene damage).

## Major

1. Team-member (human) hero content not filmable in the current editor state
   → hero demo delivered on the AividoHQ environment.
2. Final environment shots sit below the 8.0 premium gate (7.25 measured) —
   honest scorecard; the bounded loop applied real light/exposure fixes that
   did not beat the certified baseline, so fixes were reverted per-shot and
   the final film renders from the certified configuration.
3. Editor viewport capture is intermittently unreliable after heavy session
   use (transient empty/failed native captures; one render frame lost this
   run). Fresh editors and the wake→kick→settle capture contract restore it;
   partial renders are recorded truthfully, never padded.

## Warnings

1. MRQ plugin not enabled; a full 30 fps 1080p MRQ render was never claimed.
2. Local qwen3-vl vision critiques are recorded per pass (advisory); they are
   not yet auto-applied as scene fixes beyond the deterministic defect map.
3. Editor viewport capture is at native geometry (2002×742 effective this
   session), not a user-set render resolution; MRQ remains the path to exact
   1920×1080.
4. `/Game/Cine/AividoV2` sequence asset was created, verified, then removed
   in cleanup — intentional isolation, nothing persisted (an empty asset
   folder shell can briefly survive editor autosave and is removed at the
   next clean save).
