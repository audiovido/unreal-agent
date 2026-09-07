# AIVIDO V2 — FOCUSED CAPABILITY AUDIT (frozen V1 = 79fe5c7)

Focused audit of the cinematic-relevant surface only, performed against the
V1 release tree (`aivido/v1-release`). Broad repo audit intentionally not done.

## What already existed at V1 (reused, not rebuilt)

| capability | status | where |
|---|---|---|
| Blender agent/tooling | EXISTS | `blender_agent/` (agent, runner, exporters, validation, materials, rigging), `tools/blender/blender_tools.py`; V1 doctor detects Blender; chain proven for FBX/GLB and tints |
| Asset search / import / reuse | EXISTS | `assetlib/catalog/assets.json`, `assetlib/tools/catalog.py` + `router.py`, `tools/unreal/import_tools.py` (import + verify + spawn), `core/asset_intelligence.py` ranking |
| CineCamera support | PARTIAL | `tools/unreal/sequencer_tools_gap.py` spawns/reuses `CineCameraActor` + camera-cut section; no focal/aperture/framing API wrapper; per-frame transform keyframes engine-closed (recorded verbatim) |
| Sequencer support | EXISTS | LevelSequence create/list/bind/track/section/range/scrub/play/readback/save (batch-5 gap tools, hermetic-tested) |
| Movie Render Queue | MISSING | no MRQ / MovieSceneCapture / video-export path anywhere in V1 |
| Viewport capture | EXISTS | native `UnrealAgentBlueprintLibrary.capture_active_viewport(_detailed)` (synchronous, reliable, actual viewport resolution) + AutomationLibrary high-res fallback (async) |
| Animation support | EXISTS | `avatar_tools.py` (spawn character, assign AnimSequence, reactions), `animation_tools_gap.py`; engine-closed keyframe insertion documented |
| Lighting tools | PARTIAL | scene has key lights/skylight; visual loop fix actions exist (`lighting_raise_key`, `exposure_reduce_highlights`...); no engine-side wrapper for exposure at V1 |
| Visual Director / scoring | EXISTS | `core/visual_director.py` (parse_intent, defect→action), `core/visual_acceptance.py` (deterministic measure/score/accepts), `core/visual_loop.py` (autonomous loop), `core/release_director.py`; `tools/visual/shot_quality.py` |
| Video/render export | MISSING | no MRQ and no encoded-video output path (only proof PNGs via `/api/proof/*`) |
| Live bridge | EXISTS | `tools/unreal/unreal_bridge.py` + per-project `ue_listener` (default 6766); read-only guard under pytest |

## Live-editor probe results (2026-09-07, bridge 6766)

- Identity: ASSET_Showcase2, UE 5.8.2; active level `/Game/Maps/AividoHQ.AividoHQ`, 166 actors.
- MRQ: plugin **enabled** for this project and the **UE 5.8 surface verified** (`MoviePipelineQueueSubsystem` /
  `MoviePipelineInProcessExecutor` / `MoviePipelinePIEExecutor`; the 5.4-era names `MovieRenderQueueSubsystem` /
  `MoviePipelineEditorExecutor` no longer exist). Real submission with camera-bound cuts + a temp map copy was
  attempted; both executors **stall at the in-editor target-map load step** (silent after “About to load target map”,
  no frames) → MRQ engine-BLOCKED, reported truthfully, no fake render.
- `CineCameraActor`, `LevelSequenceEditorSubsystem`, `LevelSequenceEditorBlueprintLibrary`: present.
- Native editor-viewport capture: reliable on a fresh editor and through the wake → viewport-kick →
  settle → capture contract (with bounded retry + a liveness probe); intermittent empty/failed captures after heavy
  session use (partial renders are recorded truthfully, never padded).
- Cast census: 8 `SkeletalMeshActor` (AVIDO_Human_* pods); pixel-diff proof that the cast
  SkeletalMeshComponents rasterize **0 pixels by default** (mesh bounds ~1.9 m below floor for Business_Male
  actors; body materials `m00X_body` etc. rasterize as fully discarded). A bounded transient in-engine repair
  (Z-lift to floor + WhiteH material override on 23 cast slots) made a standing human verifiably render in real
  frames (`reports/cinematic/cast/proof/cast_post_lift.png`); all probes/lifts/materials were reverted exactly
  afterwards. Durable body-material/pivot repair is a Blender asset-level follow-up.

## Delta implemented for V2 (additive, see AIVIDO_V2_CINEMATIC_REPORT.md)

cinematic director + bounded quality loop + scene framing + MRQ driver (5.8 surface, truthful
BLOCKED at the engine map-switch) + real-frame renderer + live adapter + asset decision
layer + registry wiring + 38 hermetic tests.
