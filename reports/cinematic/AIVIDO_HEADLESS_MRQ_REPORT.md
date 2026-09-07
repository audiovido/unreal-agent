# AIVIDO — HEADLESS MRQ CINEMATIC RENDER (closeout report)

- Branch: `aivido/v2-cinematic`
- Base (this task's checkpoint): `cd254454a784613cf483dab4b79a2223e92d1be2`
- Engine: UE **5.8.2** (`5.8.2-56702186+++UE5+Release-5.8`)
- Project: `ASSET_Showcase2`
- Date: 2026-09-07

**HEADLESS_MRQ: PASS** — a REAL Movie Render Pipeline render was produced
headlessly via `UnrealEditor-Cmd.exe` with zero in-editor MRQ execution and
zero viewport-capture fallback. 240 genuine MRQ frames, 1920×1080 @ 30 fps,
8.0 s, human cast visible.

---

## 1. Goal

Bypass the in-editor MRQ stall (both executors silently stopped at the
target-map load step inside the interactive editor) by rendering through the
**command-line / headless editor path** instead.

## 2. Exact Unreal command used (final successful run)

```
"D:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
  "C:/Users/Shadow/Desktop/Unreal-Agent/assetlib/tests/ue/ASSET_Showcase2/ASSET_Showcase2.uproject"
  /Game/CineMRQ/RenderMap.RenderMap
  -game
  -MoviePipelineConfig=/Game/CineMRQ/MRQ_Config.MRQ_Config
  -LevelSequence=/Game/CineMRQ/MRQ_CastHero.MRQ_CastHero
  -MoviePipelineLocalExecutor
  -RenderOffscreen
  -DisablePython
  -unattended -NoP4 -NoXIM -NoSound -NoTextureStreaming -NoAsyncLoadingTimeLimit
```

- **Executor / path used:** `MoviePipelineLocalExecutor` (default
  `MoviePipelineInProcessExecutor`) driven by the MRQ command-line flags
  inside a headless `UnrealEditor-Cmd.exe` `-game` session with
  `-RenderOffscreen` (real GPU RHI, no `-NullRHI`, no viewport window).
- **Unreal exit code: 0** (clean; no crash).
- **MSYS note:** `/Game/...` paths must be protected from Git-Bash path
  conversion (`MSYS2_ARG_CONV_EXCL='*'`), otherwise the map argument becomes
  `C:/Program Files/Git/Game/...` and the engine reports "map not found".
- **`-DisablePython` is load-bearing:** without it, the render process
  auto-runs the project's Python start-up scripts (bridge listener +
  idle driver) and a Python-initiated call chain crashed the engine mid-render
  (`EXCEPTION_ACCESS_VIOLATION` in `Engine.dll ← EditorScriptingUtilities ←
  PythonScriptPlugin ← python`). MRQ itself is native C++ and needs no Python.

## 3. Why the in-editor MRQ path was blocked (evidence)

Interactive-editor runs (both `MoviePipelineInProcessExecutor` and
`MoviePipelinePIEExecutor`) stalled silently after `About to load target map
/Game/CineMRQ/RenderMap` — no frames, no error, job never completes. The
headless `-game` path does not perform the interactive map-switch at all: the
map is passed on the command line and MRQ renders it in-process.

## 4. Isolated render assets (built this task, all under `/Game/CineMRQ/`)

| asset | purpose |
|---|---|
| `RenderMap.umap` | Save-As copy of the certified AividoHQ (166 actors, durable 8/8 cast) + `CineCameraActor_0` (MRQ_Cam) |
| `MRQ_CastHero.uasset` | real Level Sequence, 0.0–8.0 s @ 30 fps = 240 frames, CameraCut bound to `RenderMap.RenderMap:PersistentLevel.CineCameraActor_0` |
| `MRQ_Config.uasset` | `MoviePipelinePrimaryConfig`: OutputSetting 1920×1080 PNG → `reports/cinematic/headless_mrq/frames`, `MoviePipelineImageSequenceOutput_PNG`, **`MoviePipelineDeferredPassBase`** render pass |

- Certified `/Game/Maps/AividoHQ` was **never modified**: `AividoHQ.umap`
  on-disk mtime unchanged at `Sep 7 10:35` (the durable cast-repair save from
  the prior task). The RenderMap is an isolated duplicate.
- Fixes required for UE 5.8 (all verified in the engine, each with a bounded
  re-run): CineCamera FOV property `field_of_view`;
  `set_playback_start_seconds` / `set_playback_end_seconds`; camera-cut
  possessable re-bound to the RenderMap-level actor path; `-DisablePython`;
  and the critical "0 Passes" fix — the pass setting previously added
  (`MoviePipelineRenderPass`) is **abstract** in UE 5.8 and was silently
  nulled on save; the concrete full pass is **`MoviePipelineDeferredPassBase`**
  (verified persisted: 3 settings, 0 nulls).

## 5. Render result (engine log evidence)

- `LogMovieRenderPipeline: Successfully detected and loaded required movie arguments. Rendering will begin once the map is loaded.`
- `Shot has 1 Passes. Total resolution: (1920x1080) Individual tile resolution: (1920x1080). Tile count: (1x1)`
- `Finished processing Camera Cut [1/1]` → `Finished rendering last shot. Moving to Finalize to finish writing items to disk.`
- `MoviePipelineLinearExecutorBase finished 1 jobs in +00:00:34.638`
- No `Fatal` / `EXCEPTION` in the render session (project log
  `ASSET_Showcase2_2.log`, session 19.08.26–19.09.01).

## 6. Output verification (ffprobe / PIL)

| metric | value | check |
|---|---|---|
| resolution | **1920×1080** | PIL on 240/240 frames |
| fps | **30** | ffprobe `r_frame_rate=30/1` |
| duration | **8.000 s** | ffprobe |
| frame count | **240** | files `frame_0000.png`…`frame_0239.png` |
| non-identical frames | yes | 50/50 unique hashes in first 50 frames |
| black/empty render | no | mean luma ≈132, max 255; 1.6% near-black pixels |
| viewport chrome/gizmos | none | visual inspection of proof frames |

- **MRQ frames path:** `reports/cinematic/headless_mrq/frames/` (240 PNG,
  produced by Movie Render Pipeline)
- **Video path:** `reports/cinematic/headless_mrq/mrq_render_1920x1080_30fps.mp4`
  (H.264, yuv420p, CRF 18 — **ffmpeg encoding of the real MRQ frames**, done
  only after MRQ finished; clearly distinguished from MRQ rendering)
- **Proof frames:** `reports/cinematic/headless_mrq/proof/proof_start.png` (0000),
  `proof_middle.png` (0120), `proof_end.png` (0239)

## 7. Human visible — PASS

Start, middle, and end frames all show the cast hero (AVIDO_Human_Master) in
the frame: black suit, white shirt, red tie, brown hair, side profile facing
right, composed against the HQ set. Human is identifiable as a person in all
three proof frames. (Verified by visual inspection of the rendered frames;
no viewport chrome or editor overlays present.)

## 8. Visual quality (honest)

- Subject is clearly visible and identifiable in every frame; composition is
  deliberate (subject right-of-center, practical light upper-center, paneled
  HQ wall + cyan counter foreground).
- **Exposure limitation:** ~27 % of pixels clip to white (the large practical
  light fixture in the certified set is hotter than the render's exposure),
  and the subject is backlit (dark suit region mean luma ≈44). The subject
  remains readable; the clipping is a real, bounded quality note.
- **Model detail:** the character's head reads low-poly/blocky at this
  framing — consistent with the cast asset's base mesh detail, not a render
  artifact.
- **Score (vision-assessed, not a deterministic scorer):** ≈**7/10** — a real,
  clean, playable render of the cast hero; points off for the clipped light
  and backlit subject. Per the task's single-correction rule, no re-render was
  performed: the hard targets (resolution, fps, duration, frames, human
  visible, real MRQ) are all met, and the exposure is scene-content
  (certified lighting), not a camera-cut or framing failure.

## 9. Scene preservation — PASS

- Certified `/Game/Maps/AividoHQ` intact: `AividoHQ.umap` mtime unchanged
  (`Sep 7 10:35`); live bridge probe reports the certified level open with
  **166 actors and all 8 cast members** (`AVIDO_Human_Animation/Audio/
  Creative/Lighting/Master/Technical/VFX/Visual`).
- Durable 8/8 cast repair preserved (standing upright, production materials,
  no WhiteH — untouched this task; no temp Z hacks, no AVCam residue added).
- Render assets isolated under `/Game/CineMRQ/` (intentional, kept for
  re-render); no changes to the certified map, lighting, or PPV.
- Interactive backend/bridge untouched (the bridge listener was never in the
  render process: `-DisablePython`).

## 10. Tests

- Cinematic suite re-run directly: **39/39 PASS**
  (`test_cinematic_director.py` 24 + `test_cinematic_live_hermetic.py` 12 +
  `test_tool_registry_cinematic.py` 3).
- One full hermetic regression (this task added engine-side scripts + reports,
  no test-covered code changed): **1120 passed, 1 skipped, 1 flake**
  (`test_step9_integration.py::test_task_holds_lease_then_releases_on_complete`
  — failed in the full run, **passed in isolation 1.93 s**, the known
  order/environment flake; effective 1121 passed / 1 skipped / 0 failed).
- No MRQ/headless pytest modules exist in the repo (engine-side scripts only).

## 11. Remaining blockers / notes

1. In-editor MRQ (interactive editor map-switch) still stalls — the headless
   path is the working route.
2. Exposure/clipping of the certified practical light (~27 % clip) and the
   backlit subject are the honest visual-quality ceiling of this render; a
   future pass could adjust the render-map light intensities (one bounded
   change) or use the built-in `MoviePipelineMP4EncoderOutput`.
3. `MoviePipelineDeferredPassBase` is the UE 5.8 concrete full pass;
   `MoviePipelineRenderPass` is abstract there and must not be used.
4. Re-render path is trivial: same command re-runs with `-DisablePython`;
   frames land in `reports/cinematic/headless_mrq/frames/`.

**CINEMATIC_V1_READY: YES** (real MRQ frames + playable MP4 delivered).