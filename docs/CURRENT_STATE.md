# AIVIDO — CURRENT STATE (durable project record)

Updated: 2026-09-05 · Branch: `unreal-coder-universal` · Engine: UE 5.8.2 (live bridge 6766 = ASSET_Showcase2)

This record is refreshed from VERIFIED evidence only (test runs, live bridge
probes, persisted reports). Old status docs are not trusted without a re-run;
each gate below names what was re-verified for this entry.

---

## 1. VERIFIED BASELINE (re-run for this record)

| check | result |
|---|---|
| Full pytest suite | **928 passed, 0 failed** (124s; was 898 before this batch) |
| Packaging task-path closure | 8/8 PASS |
| Live bridge 6766 | `UNREAL_BRIDGE_READY`, UE 5.8.2, project ASSET_Showcase2 |
| Backend 8765 | ONLINE, bridge READY |
| Live creative/asset contract | PASS (preflight computed live, correct ranking + duplicates) |
| Live mission with new code | PASS — visual plan carried creative (premium/sci_fi) + asset ranking (black_suv 0.156, real 6-entry catalog); read-only diagnostic mission executed inspect_project + unreal_ping + unreal_coder_doctor through bridge 6766 to PASS |
| Read-only discipline | missions tested pass with `read only:` prompts; guard blocks recorded |

## 2. SYSTEM INVENTORY (verified present + green)

- **Public API** — `/api/unreal-coder` (mission), `/api/action`, `/api/chat`, `/api/status`, proof endpoints, sessions API, code-task gateway, ClickUp MCP.
- **Universal layers** — `core/universal_intent.py` (L1/L2), `core/universal_planner.py` (L3), `core/capability_registry.py` (L4).
- **Mission engine** — `core/mission.py`: checkpoint/resume, loop protection, error classification, visual gate, recovery dispatch.
- **Supervisor** — `core/supervisor.py`, `supervisor/` multi-agent layer, resource gate, READ_ONLY policy enforcement.
- **Sessions** — `core/session_model.py` / `session_execution.py`: multi-client, multi-project, per-project bridges, project registry.
- **Executor** — `app/api.py` deterministic step dispatch, terminal exactly-once, plan normalization.
- **Tool registry** — 100 ToolSpecs; 8 live gap batches (67 primitives) validated through the 6766 bridge; engine-closed gaps recorded verbatim (no fakes).
- **Visual Director** — `core/visual_director.py`, `core/visual_acceptance.py` (frozen scorer), `core/visual_loop.py`, `core/release_director.py`. Release path graduated at **8.66** with 0 defects, both scenarios, no human corrections (step6 report).
- **Creative Director** — `core/creative_director.py` **NEW this batch**: structured creative intent (mood, visual language, composition, lighting, camera, palette, storytelling priorities, consistency rules) from vague requests; consistency drift detection. Hermetic tests + live preflight proof.
- **Asset Intelligence** — `core/asset_intelligence.py` **NEW this batch**: relevance scoring with field breakdowns, synonym expansion, duplicate detection (strict), LOD recommendation (never claims unavailable LODs), evidence-first catalog loading. Hermetic tests + live ranking proof.
- **Asset catalog** — `assetlib/catalog/assets.json` (truck, black SUV, CesiumMan, Fox, Lantern + Buildings via Kenney CC0); assetlib tools (catalog.py, router.py, importers, Blender chain).
- **Blender** — 4.2.0 verified GUI/CLI/bpy; P1/P2 chains; FBX/GLB round-trips; BlackSUV tint chain.
- **UI** — Director's Booth (`ui/aivido.html/css/js`) Phase 1-2, live dispatch + mission inspector, Release 1.0.0 (20260905-232841); Ava chat/widget embeddable.
- **Productization** — `scripts/build_product_package.py` + packaging smoke 8/8; doctor, first-run, env validation, launch health checks.
- **Recovery** — recovery torture 8/8 PASS (backend/bridge/editor restarts, malformed output, missing asset, interrupted resume).

## 3. MISSION SCOREBOARD (from verified evidence above)

| area | % | evidence |
|---|---|---|
| CORE ORCHESTRATION | 90 | supervisor + sessions + mission engine + task graph + policy + recovery 8/8 |
| UNREAL TOOL COVERAGE | 85 | 100 tools + 67 live primitives in 8 batches; engine-closed gaps recorded |
| VISUAL DIRECTOR | 82 | release path 8.66, 0 defects, live loop; human-eye acceptance still pending on showcase |
| CREATIVE DIRECTOR | 68 | implemented + hermetic tests + live preflight proof + mission-plan contract + replan drift guard wired |
| ASSET INTELLIGENCE | 66 | implemented + hermetic tests + live ranking/dup proof + mission-plan reuse candidates via engine catalog |
| AUTONOMOUS LOOP | 75 | mission engine, loop protection, self-repair live; bounded autonomy in place |
| PERFORMANCE | 50 | parallel discovery + caching in pipeline; step7 bench 32.6s; no end-to-end latency profile yet |
| UI/UX | 70 | Director's Booth Phase 1-2 + live wiring + Release 1.0.0; Phase H "no wall of buttons" not complete |
| RECOVERY | 85 | torture 8/8 + resume tests green |
| QA | 82 | 926 green + classification doc + packaging closure; live-UE suite is probe-based |
| PRODUCTIZATION | 75 | packaging smoke 8/8, doctor, first-run, release checklist |
| AAA SHOWCASE | 65 | ASSET_Showcase2 + ShowcaseMap + real assets + VD IT-12 (8.05 proposed, human-eye pending) |
| **OVERALL** | **~73** | weighted; no inflated numbers — every % traces to a verified artifact |

## 4. THIS BATCH (2026-09-05) — what changed and proof

Second pass (same day):

| change | files | proof |
|---|---|---|
| Mission-plan creative contract | `core/mission.py plan()` | `test_mission_plan_carries_creative_direction` pinned |
| Replan art-direction drift guard | `core/mission.py` (consistency_report) | `test_replan_with_drifted_creative_direction_warns` pinned |
| Mission asset reuse (catalog) | `MissionEngine(catalog=...)`, `app/unreal_coder_api.py` engine builder + process-cached catalog loader | `test_mission_plan_carries_asset_reuse_candidates` pinned; live plan ranked black_suv first |
| Live full-loop proof | in-process mission against bridge 6766 | read-only mission PASS with 3 real steps; visual plan carried Phase D/E contract |

## 5. FIRST PASS (same day) — what changed and proof

| change | files | proof |
|---|---|---|
| Creative Director (Phase D) | `core/creative_director.py`, wiring in `core/production_pipeline.py`, `core/mission.py` | 14 new hermetic tests; live preflight on 6766 (premium/sci_fi, layered depth, cool-cyan palette, 5 consistency rules) |
| Asset Intelligence (Phase E) | `core/asset_intelligence.py`, `assets=` param in `production_preflight` | 14 new hermetic tests; live ranking `black_suv > truck > lantern` + 1 duplicate group |
| Visual gate broadened | `production_pipeline.is_visual_task` | vague "make X look like Y" + lobby/vehicle/showcase now visual; negative gates re-verified |
| Mission plan carries creative intent | `core/mission.py plan()` | `test_mission_plan_carries_creative_direction` pinned |
| Packaging closure fixed | `scripts/build_product_package.py` | packaging smoke 8/8; mission→preflight closure packaged |
| Duplicate-similarity bug | fixed precedence bug in `_similarity` | regression test `test_duplicate_detection_leaves_distinct_assets_alone` |

## 6. KNOWN LIMITATIONS / HONEST GAPS (not faked)

- Creative Director and Asset Intelligence are **not yet wired into the mission execution loop's correction path** — they inform the plan (preflight) but don't yet gate iterations.
- Showcase (ASSET_Showcase2) final human-eye acceptance pending (VD IT-12 proposed 8.05).
- MetaHuman identity authoring, Niagara emitter authoring, IK Rig/Retarget, per-node compile errors, pin disconnect are engine/C++-closed in UE 5.8 Python; recorded verbatim, not faked.
- Asset catalog is small (6 entries); more verified CC0 assets would raise Asset Intelligence's live value.
- No end-to-end latency profile of a full mission yet (step7 bench profiles the visual loop only).

## 7. NEXT STEPS (priority order)

1. Turn ranked catalog candidates into concrete reuse steps in mission execution (import+place the best existing asset before generating).
2. Performance profile of a full mission; add targeted caching (Phase G).
3. Live full-mission run on ASSET_Showcase2 with creative direction + asset selection, capture + Visual Director verdict.
4. Continue UI Phase H simplification (goal-first UX).
5. Showcase human-eye acceptance (external; needs the user's eyes on the frame).