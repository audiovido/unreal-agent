# AIVIDO V2 — SOURCE OF TRUTH

Verified live on Shadow PC: 2026-09-08 · verified by direct bridge probe + file inventory.
Re-verify after any migration: from repo root with the editor running —

```
python -c "from tools.unreal.unreal_bridge import UnrealBridge; print(UnrealBridge().get_identity())"
```

## The one production project

| Item | Value |
|---|---|
| Repo | `https://github.com/audiovido/unreal-agent.git` (origin) |
| Mission branch (this lane) | `aivido-worker4-ui` |
| V2 integration lanes | `aivido/v2-release` (39 commits ahead of origin/main), `aivido/v2-macos-package` (42), `aivido/v2-autonomous-qa`, `aivido/v2-second-system-prep`, `aivido/v2-release-blocker-fix` |
| Working-tree location | `C:\Users\Shadow\Desktop\Unreal-Agent` |
| **V2 .uproject** | `assetlib/tests/ue/ASSET_Showcase2/ASSET_Showcase2.uproject` (repo-relative) = `C:\Users\Shadow\Desktop\Unreal-Agent\assetlib\tests\ue\ASSET_Showcase2\ASSET_Showcase2.uproject` |
| **Production map** | `/Game/Maps/AividoHQ` (`Content/Maps/AividoHQ.umap`) — also `GameDefaultMap` + `EditorStartupMap` in `Config/DefaultEngine.ini` |
| Engine | UE 5.8.2 (`5.8.2-56702186+++UE5+Release-5.8`) installed at `D:\Program Files\Epic Games\UE_5.8` |
| Project modules | `AudioVidoLivingCity` runtime module (Source/), plugin `UnrealAgentBridge` (project-local, editor TCP JSON bridge) |

Proof (live bridge probe, 2026-09-08):

```
IDENTITY: {'ok': True,
 'project_path': 'C:/Users/Shadow/Desktop/Unreal-Agent/assetlib/tests/ue/ASSET_Showcase2/ASSET_Showcase2.uproject',
 'project_name': 'ASSET_Showcase2',
 'engine': '5.8.2-56702186+++UE5+Release-5.8',
 'world': '/Game/Maps/AividoHQ.AividoHQ', 'port': 6766}
```

## Rejected candidates (proven NOT the V2 project)

| Candidate | Why rejected |
|---|---|
| `C:\Users\Shadow\Desktop\app\AudioVidoLivingCity\AudioVidoLivingCity.uproject` | Separate git repo (`audiovido/AudioVidoLivingCity`), branch `ui-review`, map `AVLC_Main` — cinematic vertical slice, frozen baseline; no AividoHQ content |
| `C:\Users\Shadow\Desktop\AvaLive\AvaLive\AvaLive.uproject` | NOT a git repo at all; map `AvaLive_Main`; older experiment |
| `UnrealAgentGraduation/UA_GradAudit_*` | Graduation audit scratch project |

The Aivido HQ lane (workers 1–5: room, 8 RocketBox human agents, props, game UI) all built
inside `ASSET_Showcase2` — see `reports/hq/WORKER2_CHARACTERS_HANDOFF.md` and
`config/project_registry.json` ("Project A - ASSET_Showcase2").

## Runtime control plane (verified live 2026-09-08)

| Service | Address | State |
|---|---|---|
| Unreal Agent backend | `http://127.0.0.1:8765` | ONLINE — `{"ok":true,"version":"Adaptive API v5.2",...,"unreal":{"ok":true,"message":"UNREAL_BRIDGE_READY"}}` |
| Unreal bridge (editor plugin) | `127.0.0.1:6766` (TCP JSON; client `tools/unreal/unreal_bridge.py`) | READY — editor `UnrealEditor.exe` PID 15900 running AividoHQ |
| Bridge protocol | `{"type":"ping"\|"python"\|"identity"\|...}` — see `tools/unreal/ue_listener.py` (runs inside editor) and `tools/unreal/unreal_bridge.py` (client) | |
| High-level agent API | `POST http://127.0.0.1:8765/api/unreal-coder` (+ `/async`, `/mission/{id}`, `/resume`) | mission pipeline used by UI |

## Content inventory inside the V2 project (as of baseline)

- `/Game/AividoHQ` — 252 MB, 154 character assets (16 SkeletalMesh RocketBox avatars,
  13+ AnimSequences, materials/MICs), `Content/AividoHQ/Animations` (IK retarget rig)
- `/Game/Maps` — `AividoHQ.umap` (production), `AividoHQ_PropsStage.umap`, `ASSET_Showcase2.umap`
- `/Game/Mannequin` — UE5 third-person template set: `SK_Mannequin`, `SK_Mannequin_Female`,
  `ThirdPerson_AnimBP`, `ThirdPerson_WalkRun_1D` BlendSpace, Idle/Walk/Run/Jump AnimSequences
- 166 actors placed in AividoHQ: 86 static meshes, 39 lights, 8 `SkeletalMeshActor` workers
  (labels `SkeletalMeshActor_0..7`, meshes Business_Male_01, Male_Adult_11, Business_Female_02,
  Male_Adult_03, Female_Adult_05, Male_Adult_12, Female_Adult_01, Female_Adult_08),
  19 prop Blueprint actors, 1 PlayerStart, 1 CameraActor
- Existing UI assets: `/Game/UA_Mission/WBP_MainMenu`, `/Game/Golden/GB2_HUDWidget` (mission artifacts, not wired to any GameMode)
- No Enhanced Input assets existed at baseline (input configured fresh in this mission)

## Baseline state that this mission changed

At baseline AividoHQ was an editor-only static scene:
- WorldSettings `DefaultGameMode = None` (would fall back to DefaultEngine GameMode = empty)
- No player pawn, no PlayerController wiring, no input mapping
- Workers: 1 with ANIMATION_BLUEPRINT mode but no anim class; 7 with SINGLE_NODE mode and no sequence → would stand frozen in PIE
- No UMG added to viewport at runtime

All of the above was made playable in this mission — see `AIVIDO_V2_UNREAL_AGENT_CAPABILITIES.md`
and the mission commits.
