# WORKER 2 — Photoreal Human Agents · CHARACTER HANDOFF

Branch: `aivido/worker-human-agents` (worktree `Unreal-Agent-w2-humans`)
Engine: UE 5.8.2 — project `ASSET_Showcase2` (bridge 127.0.0.1:6766)
Generated: 2026-09-06 · Status: **WORKER2_INTEGRATION_READY = TRUE**

---

## 1. Recovery result (start-of-mission)

The previous Worker 2 lane left **uncommitted deliverables in the main checkout** (no commits
on `aivido/worker-human-agents`; no `reports/hq/` existed yet):

- `assetlib/tools/ue_hq_build.py` — builds `/Game/Maps/AividoHQ` (hub, rooms, lighting, signage)
- `assetlib/tools/ue_hq_characters.py` — RocketBox import + PBR materials + MICs + spawn
- `assetlib/source/rocketbox/` — 3 staged kits (Business_Male_01, Male_Adult_11, Business_Female_02)
  + `manifest.json` (MIT license + attribution per file)
- Live in UE: 66 assets under `/Game/AividoHQ/Characters` (3 agents imported, materials built),
  `/Game/Maps/AividoHQ` saved with 3 `AVIDO_Human_*` actors

The reported "handoff/manifest" did **not** exist — created here. The reported
"~2 remaining characters" was actually **5 remaining** to reach an 8-agent cast.

## 2. Final cast — 8 production-ready agents

| # | agent_id | Role | Mesh (path under /Game/AividoHQ/Characters) | Station (x, y, z) · yaw | Height |
|---|----------|------|----------------------------------------------|------------------------|--------|
| 1 | aivido.master_director | MASTER_DIRECTOR | Master/Business_Male_01 | (0, 700, 0) · 90 | 180.6 cm |
| 2 | aivido.creative_director | CREATIVE_DIRECTOR | Creative/Male_Adult_11 | (3800, 900, 0) · -90 | 180.3 cm |
| 3 | aivido.visual_director | VISUAL_DIRECTOR | Visual/Business_Female_02 | (-3800, 900, 0) · -90 | 172.9 cm |
| 4 | aivido.technical_director | TECHNICAL_DIRECTOR | Technical/Male_Adult_03 | (1900, 300, 0) · 180 | 180.7 cm |
| 5 | aivido.audio_director | AUDIO_DIRECTOR | Audio/Female_Adult_05 | (-1900, 300, 0) · 180 | 173.6 cm |
| 6 | aivido.animation_director | ANIMATION_DIRECTOR | Animation/Male_Adult_12 | (950, 1700, 0) · 180 | 180.7 cm |
| 7 | aivido.lighting_artist | LIGHTING_ARTIST | Lighting/Female_Adult_01 | (-950, 1700, 0) · 180 | 174.3 cm |
| 8 | aivido.vfx_artist | VFX_ARTIST | VFX/Female_Adult_08 | (0, 2000, 0) · 180 | 173.5 cm |

Actor labels in the map: `AVIDO_Human_<Agent>` (SkeletalMeshActor). Every agent is a
distinct RocketBox avatar — unique face, hair, clothing, silhouette, role identity.
No clones, no real-person likenesses (Microsoft RocketBox avatars, MIT).

Each agent has:
- body mesh + facial mesh + own skeleton (+ PhysicsAsset, embedded `*_Anim` AnimSequence)
- MICs `Aivido_Body` (parent M_Aivido_Cloth) + `Aivido_Head` (parent M_Aivido_Skin),
  wired to the avatar's own color/normal/specular maps
- accent face light `AVIDO_FaceLight_<Agent>` + front key light `AVIDO_KeyLight_Char_<Agent>`

## 3. Materials / grooming / faces

- **Materials**: 16/16 MICs verified resolving (parent + per-agent texture set).
  `M_Aivido_Skin` = MSM_SUBSURFACE with `SubsurfaceColor` (red-tinted vector) + `SubsurfaceOpacity`,
  `M_Aivido_Cloth` = DefaultLit with Spec→Roughness inversion. No plastic/mannequin material state observed;
  faces are the RocketBox avatar identities (unique per agent).
- **Hair/groom**: baked into the avatar meshes (RocketBox pipeline); no separate Groom assets.
- **Eyes/eyelids/eyebrows/hairline**: part of the distinct avatar head textures — no duplicated
  preset appearance across the cast.

## 4. Animation

- **Per-character**: every agent has a real `AnimSequence` on its **own skeleton**
  (`/Game/AividoHQ/Characters/<Agent>/<Mesh>_Anim`, imported with the avatar FBX).
  Validated live in PIE: `set_animation_mode(ANIMATION_SINGLE_NODE)` + `set_animation(...)`
  succeeded for **8/8** with no retarget errors. Note: these clips are ~1-frame reference
  captures (0.033 s), i.e. they prove the animation pipeline and hold a pose; they are not
  full motion loops.
- **Locomotion baseline**: `/Game/Mannequin` is installed (proven avatar-toolchain path):
  `ThirdPersonIdle`, `ThirdPersonWalk`, `ThirdPersonRun`, `ThirdPerson_WalkRun_1D`,
  `ThirdPerson_IdleRun_2D`, `ThirdPerson_AnimBP`. These are real, verified sequences for the
  mannequin skeleton — the project's walk/idle/turn-ready assets for any Manny-compatible character.
- **RocketBox gesture library** (idle variants, look-around, talk/listen, sit — staged at
  `assetlib/source/rocketbox/animations/`): import is **BLOCKED_BY_IMPORT_PIPELINE** —
  animation-only `.max.fbx` import returns no assets (2 bounded attempts; the FbxImportUI options
  path also silently aborts imports in this engine build, so the body imports use auto-detect).
- **Micro-behavior** (breathing/gaze/weight-shift): not added as runtime logic by design —
  no Tick loops or wandering (mission constraint). The mannequin `ThirdPerson_AnimBP` +
  IdleRun/WalkRun blends are the recommended idle/locomotion system for Worker 5.

## 5. Staging map validation (live)

Staging map: **`/Game/Maps/AividoHQ`** (unchanged in structure; the final HQ map this lane stages into).

| Check | Result |
|-------|--------|
| All 8 characters load | PASS (8/8 actors) |
| Meshes + skeletons resolve | PASS (8/8, per-agent skeleton) |
| All materials resolve | PASS (8/8 meshes, 16/16 MICs) |
| Blueprints compile | N/A — level-placed SkeletalMeshActor (no BP class required) |
| Animations resolve | PASS — 8/8 embedded sequences + mannequin baseline present |
| Believable scale | PASS — 173–181 cm, recommended_scale 1.0 |
| Floor contact | PASS — feet at world Z 0.0 ±0.5 cm |
| Clipping | No inter-penetration observed at stations (spacing ≥ 700 cm) |
| Map saves | PASS — save_level verified (package_exists=true, dirty_after=false) |
| Map reopens | PASS — reopened with 8/8 actors resolving, zero errors |

## 6. Live Unreal proof (evidence)

Game-viewport captures (engine-verified `source=GameViewport`):

- `assetlib/proof/worker2_cast_final.png` (877 KB) — cast overview, post key-light pass
- `assetlib/proof/worker2_cast_game_viewport.png` (1.0 MB) — overview with agents + accent lights
- `assetlib/proof/worker2_master_front.png` (442 KB) — Master close-up (figure confirmed in frame)
- `assetlib/proof/worker2_cast_overview.png` (681 KB) — earlier overview

Live Unreal verification: **YES** (all validation in section 5 performed against the live session).

## 7. Performance notes

- LODs: 1 imported LOD per mesh. Auto-LOD generation (`SkeletalMeshEditorSubsystem.RegenerateLOD`)
  is blocked by the UE 5.8 Python binding (`regenerate_even_if_imported` conversion failure).
  Mitigation: the repo's Blender decimate pipeline (`assetlib/tests/blender/p2_out/decimate_optional`)
  is available for building LODs outside the engine binding.
- Groom cost: baked into mesh (no separate groom assets to budget).
- Textures: 2K-class TGA maps per agent (color/normal/specular for body + head).
- Skeletal complexity: standard RocketBox avatar skeleton + facial skeleton; physics assets imported.

## 8. Remaining blockers (truthful)

1. **RocketBox custom animation import** — BLOCKED_BY_IMPORT_PIPELINE (staged, ready for a
   future toolchain that accepts animation-only FBX).
2. **Auto-LOD generation** — blocked by engine Python binding.
3. **IK retarget to custom skeletons** — engine/C++-closed in UE 5.8 Python
   (recorded in `docs/CURRENT_STATE.md`).
4. **Per-agent Blueprint classes** — not required for staging; agents are level actors.

## 9. Worker 5 integration contract (no guessing)

- Staging map: `/Game/Maps/AividoHQ`; spawn by actor label `AVIDO_Human_<Agent>` or by mesh path.
- Asset root: `/Game/AividoHQ/Characters/<Agent>/<Mesh>` (per-agent list in manifest JSON).
- Roles + recommended zones + standing/seated + scale: see `WORKER2_CHARACTERS_MANIFEST.json`.
- Materials: `/Game/AividoHQ/Characters/M_Aivido_Skin`, `M_Aivido_Cloth` + per-agent MICs.
- Locomotion: `/Game/Mannequin/Animations/*` (mannequin skeleton) for walk/idle/run needs.
- Do not move/delete: `AVIDO_Human_*`, `AVIDO_FaceLight_*`, `AVIDO_KeyLight_Char_*`,
  `AVIDO_Exposure` (auto-exposure bias tuned to 1.0 for the cast).

**WORKER2_INTEGRATION_READY = TRUE** — all 8 agents are built, wired, saved, reopened, and
live-validated; the only animation gaps are the documented import/retarget engine limitations.