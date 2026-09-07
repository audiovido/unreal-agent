# AIVIDO Cast — Durable Blender-Verified Repair Report

**Branch:** `aivido/v2-cinematic` (isolated worktree `cinematic-v2/`)
**Task:** Durable production-safe repair of the Aivido human cast so characters stand upright on the floor with their real production materials — no transient Z-lift, no WhiteH override, no runtime hacks.
**Date:** 2026-09-07

---

## Executive summary

The AividoHQ human cast (8 `AVIDO_Human_*` SkeletalMeshActors) previously needed a
**transient** repair to appear in any cinematic: an in-memory Z-lift plus a flat-white
material override, both reverted after filming. This report documents the durable fix.

**Blender used: YES — headless source diagnosis only** (vendored Blender 4.2.0,
`reports/cinematic/blender/diag_fbx.py`). The diagnosis **proved the source FBX
geometry is correct**, so no Blender surgery was performed on the source assets. All
three actual defects are Unreal-side import/ref-pose bakes and were repaired durably
in Unreal (the sanctioned least-destructive option C for a healthy source).

All **8/8 characters now stand upright on the floor with their opaque production
materials** (`Aivido_Body` / `Aivido_Head`), with no overrides, no temporary lifts,
and the certified AividoHQ map intentionally re-saved (166 actors preserved).

---

## 1. Exact root cause (three independent defects)

### 1a. Floor burial (~1.8 m) — skeleton ref-pose bake of a legacy pivot
Blender headless FBX diagnosis (`blender_agent/_diag_fbx.py`, re-run for evidence):

| Source FBX | Mesh world bounds z | Armature `Bip01` z | Mesh object z |
|---|---|---|---|
| `stage/MASTER/Business_Male_01.fbx` | [−0.001, 1.806] (feet at 0) | 0.895 | −89.518 |
| `stage/VISUAL/Business_Female_02.fbx` | [0.0, 1.729] (feet at 0) | 0.923 | −92.329 |

The Rocketbox sources use the legacy **"Bip01 Footsteps" pivot convention**: the mesh
object sits ~−89.5 cm below the armature root (pelvis at +89.5 cm). Unreal baked that
mesh-object offset into each **skeleton reference pose**, so the cast rendered ~1.8 m
below the component origin (floor z=0). The bake differs per character because the
eight characters were imported from different FBX rigs:
Master −187, Technical −187, Audio −180, Animation −184, Lighting −176, VFX −177,
Creative −72, Visual −70 cm.

### 1b. Inversion — the cast rendered HEAD-DOWN
Live viewport captures verified by the local vision model (qwen3-vl) that the cast
rendered **upside-down** (head at the bottom of the render bounds, legs at the top;
`upright: false`, high confidence, A/B frames in the proof folder). The earlier
closeout's "human visible" PASS was therefore on an *inverted* figure — recorded
honestly here. This is a second import/ref-pose bake artifact, corrected with a
durable **180° pitch** component rotation.

### 1c. Invisibility — masked FBX "opacity" material cuts the body polys
Mesh slots carry the imported FBX MICs. The `m00X_opacity` MIC
(`OpacityMapWeight = 1`, `OpacityMap = m00X_opacity_color`) is a masked Phong that
discards the polys carrying the visible silhouette, so the cast rasterized **0 px**.
The per-character production **opaque** MICs `Aivido_Body` (parent `M_Aivido_Cloth`)
and `Aivido_Head` (parent `M_Aivido_Skin`, both `BLEND_OPAQUE`) already existed but
were never assigned to the meshes.

---

## 2. Durable repair performed (no Blender surgery needed)

| # | Operation | Where | Why |
|---|---|---|---|
| 1 | Re-slot each cast `SkeletalMesh` asset to `Aivido_Body`/`Aivido_Head` (slot1 = head, others = body), **saving the mesh assets** | `/Game/AividoHQ/Characters/<char>/<mesh>` | Replaces the masked FBX MICs with the production opaque MICs at the **asset level** so every level/instance benefits. `SkeletalMesh.set_material()` is a silent no-op in python; the proven durable API is a wholesale rebuild of the `materials` property (fresh `SkeletalMaterial` list), verified by re-read. |
| 2 | Clear component `override_materials` | components | Removed the stale `M_Aivido_WhiteH` residue left on slots 1+ by the old transient repair; components now render the (fixed) mesh materials. |
| 3 | Component `relative_rotation` → pitch **180°** | components | Flips the inverted ref-pose render upright (head up). |
| 4 | Component Z lift so mesh feet rest on the floor | components | Measured per character from real render bounds after the orientation fix; persisted in the map. |
| 5 | Re-save the certified map (intentional, verified update) | map | Persists the durable component transforms. |

No skeleton asset was re-imported, so **skeleton compatibility and animation
compatibility are preserved by construction** (same skeleton assets, same GUIDs;
Master's AnimBlueprint untouched; no retargeting, no bone renames).

---

## 3. Results — 8/8 (post-repair read-back)

| Character | Mesh feet z | Height (head) | Upright | Material slot 0 | Overrides |
|---|---|---|---|---|---|
| AVIDO_Human_Master | 0.0 | 187.7 cm | ✔ | Aivido_Body | none |
| AVIDO_Human_Creative | 0.0 | 185.0 cm | ✔ | Aivido_Body | none |
| AVIDO_Human_Visual | 0.0 | 176.7 cm | ✔ | Aivido_Body | none |
| AVIDO_Human_Technical | 0.0 | 186.3 cm | ✔ | Aivido_Body | none |
| AVIDO_Human_Audio | 0.0 | 180.0 cm | ✔ | Aivido_Body | none |
| AVIDO_Human_Animation | 0.0 | 187.0 cm | ✔ | Aivido_Body | none |
| AVIDO_Human_Lighting | 0.0 | 174.3 cm | ✔ | Aivido_Body | none |
| AVIDO_Human_VFX | 0.0 | 175.8 cm | ✔ | Aivido_Body | none |

All `m00X_head`/`m00X_opacity`/`f00X_*` slots replaced; every slot now opaque
(`Aivido_Body` or `Aivido_Head`); **no WhiteH anywhere**; 8/8 zmin == 0.

---

## 4. Real visual proof

- `reports/cinematic/cast_durable/cast_durable_result.json` — full before/after record
  (component Z, rotations, slot materials, overrides, zmin/zmax per character).
- `reports/cinematic/cast_durable/proof/hero_final_upright.png` — final upright hero
  (Master, real native viewport capture, production materials).
- `reports/cinematic/cast_durable/proof/evidence_inverted_before_orient.png` +
  `evidence_upright_after_orient.png` — A/B frames proving the orientation defect and
  its fix (vision: `upright:false` → `upright:true`, high confidence).
- `reports/cinematic/cast_durable/proof/gate_hero.png` — Master standing after the
  full durable repair (vision: human_visible true).

**Local vision verdict on the final upright hero** (`qwen3-vl:8b-instruct`):
`score 8/10, pass true, human_visible true, readable_as_human true, upright true`
— "A standing human character is clearly visible, upright, and readable as a human
in a futuristic setting."

**Honest visual score (no faking):**
- Vision dimension: **8/10** (premium-readable upright human).
- Deterministic cinematic overall: **4.45/10** (composition 6.0, lighting 6.81,
  subject_visibility 5.0, framing 0.0). Framing = 0 is a **scorer artifact**, not a
  real framing failure: the luma-based subject locator merges the bright certified
  set into one blob (subject_coverage pinned at 0.93 for a dark-clad hero on the
  bright set at every camera angle tested), so it can never credit the human subject.
- Blended (0.65 measured + 0.35 vision): **≈5.7/10**.
- The 8.0 deterministic gate therefore still stands open **only** because the
  deterministic locator cannot separate a dark hero from the bright certified set —
  a scorer limitation, now precisely characterized.

---

## 5. Scene preservation

- Certified AividoHQ: **166 actors** before and after (no actors added/removed).
- No `AVCam_*`, no `/Game/Cine` shell, no temp actors, no `/Game/Cine/DurableRepair`
  residue (captures used the stable level-viewport camera path; no sequences built).
- Certified lighting/PPV untouched (manual exposure bias 1.0, key light 5.4 values
  unchanged from certification).
- The only intentional persisted change is the durable cast repair itself (standing,
  upright, production materials) — the map was re-saved only after live verification.
- Full before-state is recorded in `cast_durable_result.json` for exact recovery.

---

## 6. Remaining blockers / notes

- **Deterministic cinematic scoring of dark heroes:** the luma locator merges the
  bright certified set (coverage 0.93 at every angle) → subject framing cannot pass
  8.0 deterministically until the scorer or the character's on-set contrast changes.
- **Editor viewport captures include transform-widget overlays** (axis gizmos) that
  are absent from real (non-viewport) renders; they clutter native proof frames.
- **MRQ** remains engine-blocked at the in-editor map-switch step (from the prior
  closeout; not reopened in this task).

## 7. Artifacts
- Repair driver: `cinematic-v2/scripts/cast_durable_repair.py` (reproducible; master
  gate then `--all --save`), pose sweep: `scripts/hero_pose_sweep.py`.
- Blender diagnosis: `reports/cinematic/blender/diag_fbx.py` (headless, vendored
  Blender 4.2.0).

## 8. Final status (2026-09-07)

- **CAST_DURABLE_READY: YES.** Durable, persisted, production-safe cast repair;
  reproducible driver; full before/after record; verified 8/8.
- **Hero vision score: 8/10 PASS** (qwen3-vl:8b-instruct — human_visible,
  readable_as_human, upright on the final upright hero frame).
- **Cinematic tests: 39/39 PASS** (test_cinematic_director +
  test_cinematic_live_hermetic + test_tool_registry_cinematic).
- **Full hermetic suite: 1121 passed / 1 skipped / 0 failed** (clean rerun,
  233 s, exit 0; `reports/cinematic/cast_durable/regression.log`).
- Scene preservation: 166 actors before/after, no AVCam/Cine residue.
- Not reopened this task: MRQ (engine-blocked at in-editor map switch),
  deterministic scorer limitation (framing 0 artifact for dark heroes on the
  bright set).
