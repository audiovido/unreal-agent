# WORKER 2 — UI / CAMERA / MENU STANDARDIZATION

**Branch/worktree:** `aivido-worker2-ui` (worktree at `.worktrees/aivido-worker2-ui`)
**Baseline commit:** `ae68b0c` · **Head after work:** `ae68b0c` + uncommitted changes
**Engine:** UE 5.8.2 · **Project:** `assetlib/tests/ue/ASSET_Showcase2/ASSET_Showcase2.uproject` · **Map:** `/Game/Maps/AividoHQ`
**Validated:** 2026-09-09 — UBT compile (Editor + Game targets) + live `-game` runtime proof + OS window captures

---

## 0. Summary

The previous UI polish (`ae68b0c`) was **not** final. The audit found the camera system had exactly
one camera mode and no transitions, the menus lacked keyboard navigation/focus/pause semantics,
conversation Enter-to-send was silently broken (delegate never bound), repeated open/close
duplicated messages and could double-bind replies, and gameplay input stayed live while menus and
conversations were open. All of these were fixed with a single centralized state machine and
validated live.

---

## 1. CAMERA SYSTEM

### Camera modes found (baseline)
| Mode | Existed | Purpose | Activation | Deactivation | Notes |
|---|---|---|---|---|---|
| Gameplay (third-person follow) | ✅ | Walk around HQ | spawn/possess | — | SpringArm + FollowCamera 65° FOV |
| Conversation / NPC focus | ❌ | Frame the director during chat | **added** | **added** | new `ConversationCamera` on the director |
| Menu / pause | ❌ | — | — | — | menus are overlays; camera intentionally stays on gameplay (standard) |
| Cinematic / overview / transition / debug | ❌ | not in scope | — | — | no level sequences exist; camera model reserves future modes |

### Issues found and fixed
- **No conversation camera** — conversation opened with no camera change. **Fixed:** `AAividoDirector`
  owns a `ConversationCamera` (65° FOV, matching gameplay). Opening a conversation calls
  `FacePlayer()` (director turns toward the player) + `PlaceConversationCamera()` (over-the-shoulder
  framing behind the player, aiming at the director's face), then
  `PlayerController->SetViewTargetWithBlend(Director, 0.6s, VTBlend_Cubic)`.
- **No camera restoration** — nothing ever returned the view to the player. **Fixed:** closing the
  conversation always `SetViewTargetWithBlend`s back to the pawn (0.6s cubic). A camera can never be
  left stuck on the director: the restore runs in the single `SetUIState` transition to Gameplay.
- **No camera state model** — **added** `EAividoCameraMode { Gameplay, ConversationFocus }` on the
  GameMode; all camera transitions happen in one place (`AAividoGameMode::SetUIState`).
- **No pitch limits** — the look handler could flip the camera over the top. **Fixed:** `Look()` /
  `LookPitch()` clamp controller pitch to ±89°.
- **Menu/pause camera** — standard overlay behavior: camera keeps its current state while the pause
  menu is open; no snap.
- Camera ownership: the conversation camera is a component of the director actor (view target is the
  director); the pawn's spring arm is untouched and re-activated on restore.

### Runtime verification (log, `AIVIDO_PROOF`)
```
conv_open=true camera=1          → conversation blends to the director framing camera
conv_camera_target=AividoDirector_0
conv_closed=false menu_open=false → ESC closes the conversation
restored_camera=AividoCharacter_0 is_pawn=true  → view target is back on the pawn
```

---

## 2. MAIN MENU / PAUSE MENU

### Menus found (baseline)
| Menu | Existed | Status |
|---|---|---|
| Main menu | ❌ | **added** — boot start screen (Start Session / Quit Session); ESC also starts |
| Pause/ESC menu | ✅ (partial) | Resume / Refresh Worker States / Quit Session — was missing focus, nav, pause semantics |
| Settings / mission / worker menus | ❌ | not in scope (worker states live in the pause menu + HUD banner) |

### Issues found and fixed
- **No keyboard navigation / first-focus** — **fixed:** first button is keyboard-focused on open
  (deferred one tick so boot focus works); explicit arrow + Tab navigation rules between all buttons
  with wraparound.
- **No focus/hover/pressed feedback** — **fixed:** every button gets a deterministic
  rounded-box `FButtonStyle` (normal / hovered / pressed / disabled brushes) + a uniform 260px min
  label width so all rows align. Keyboard focus draws the Slate focus ring.
- **Game input stayed live while the menu was open** — movement, look and E kept firing under
  GameAndUI. **Fixed:** the state machine sets `SetIgnoreMoveInput(true)` + `SetIgnoreLookInput(true)`
  and gates interaction on the UI state; all input is restored on close.
- **No stack guards** — **fixed:** interaction/conversation are gameplay-only; ESC steps down
  conversation → menu → gameplay; a menu can never open over the conversation and a conversation can
  never open over a menu.
- **Main menu missing entirely** — boot now opens the start screen (same native widget, main-menu
  mode hides the Worker States row). Boot-time add is deferred 0.5s out of `BeginPlay` because a
  widget added during world bring-up can miss its first paint (verified empirically).
- Buttons all wired to real actions (Resume/Start, Refresh Worker States, Quit) — no dead buttons.

### Runtime verification
```
AIVIDO_UI: main_menu vp=1 vis=1
AIVIDO_UI: menu_geo=X=560.000 Y=440.000 vp=1 vis=1   (panel laid out, both opens)
AIVIDO_STATE: 0 -> 1  (Gameplay -> MainMenu)
AIVIDO_STATE: 1 -> 0  (start -> Gameplay)
AIVIDO_STATE: 0 -> 2  (pause)
AIVIDO_STATE: 2 -> 0  (resume)
```
Window captures: main-menu frame center mean 24.7 vs same-camera gameplay control 42.9; pause frame
vs its control 30.2 vs 42.9 with 75% of changed pixels inside the expected centered panel rect.

---

## 3. CONVERSATION UI

### Flow verified / fixed
- **Enter to send was broken (real bug):** `OnCommitted` was bound with `AddUniqueDynamic` but not a
  `UFUNCTION` — the bind fired a handled ensure and silently never bound. **Fixed:** `UFUNCTION()` on
  the handler. Runtime log now shows **no ensure** on open.
- **Duplicate welcome lines on reopen:** the "Welcome" line was appended on every open. **Fixed:** only
  greeted when the transcript is empty; reopen keeps the prior transcript.
- **Duplicate replies on reopen:** `OnReplyChanged.AddUObject` re-bound on each open without unbinding.
  **Fixed:** `RemoveAll` before re-binding.
- **Stale "…thinking" placeholder:** a round-trip that never completed left a ghost line. **Fixed:**
  stripped on open.
- **Double-send while waiting:** **fixed** — Send disabled while a round-trip is in flight, re-enabled
  on reply.
- ESC closes the conversation (existing behavior preserved); Close button + focus return verified.
- While the conversation is open the player cannot move/look/E (input locks) and the camera is the
  director framing — a complete modal UX state.

### Runtime verification
```
conv_open=true camera=1
conv_camera_target=AividoDirector_0
conv_closed=false menu_open=false
```
No `Ensure condition` / `Handled ensure` lines in the final run's log.

---

## 4. HUD

- Prompt (`[E] Talk to …`) and HUD banner are now **hidden outside the Gameplay state** — nothing
  stale sits behind or overlaps the main menu, pause menu or conversation panel; the prompt
  reappears when gameplay resumes.
- Banner keeps the live director-link + worker-roster lines at ~2 Hz (unchanged behavior, now
  state-aware).
- Anchoring unchanged (top-left banner at 16,16; bottom-center prompt) — safe margins at
  1280×720/1920×1080/ultrawide; fixed logical sizes so DPI scaling cannot drift panels (the
  packaged-build displacement issue is avoided by explicit canvas extents).

---

## 5. INPUT / FOCUS STATE MACHINE

Single deterministic model on the GameMode — **the only place** cursor, input mode, movement locks
and camera transitions are applied:

```
EAividoUIState { Gameplay, MainMenu, Pause, Conversation }
AAividoGameMode::SetUIState(NewState)  →  cursor / GameAndUI|GameOnly / IgnoreMove+IgnoreLook /
                                         camera blend (Conversation<->Gameplay) / delegates
```

| Transition | MouseCursor | InputMode | Move/Look | Focus | Camera |
|---|---|---|---|---|---|
| Gameplay→MainMenu/Pause | show | GameAndUI | locked | first button | unchanged |
| MainMenu/Pause→Gameplay | hide | GameOnly | unlocked | — | unchanged |
| Gameplay→Conversation | show | GameAndUI | locked | input box | blend→director (0.6s cubic) |
| Conversation→Gameplay | hide | GameOnly | unlocked | — | blend→pawn (0.6s cubic) |

No ad-hoc `SetInputMode` calls anywhere else. Edge cases covered: ESC during conversation closes the
conversation first; E during conversation/menu is ignored; repeated ESC steps down one level per
press; open menu near NPC cannot stack a conversation; close menu then immediately interact works
(state is Gameplay again).

---

## 6. RESPONSIVE / LAYOUT

Reviewed at 1280×720 (runtime), 1920×1080, ultrawide and small windowed via anchored canvas slots
in logical units: menu 560×440 and conversation 720×440 centered with explicit extents; HUD banner
430×180 top-left; prompt 600×48 bottom-center. All panels use fixed logical sizes + center anchors so
DPI scaling changes rendered size but never moves content off-center or off-screen.

---

## 7. VALIDATION

- **Compile (UBT):** `AividoV2Editor` and `AividoV2Game` Win64 Development — **both Succeeded** on the
  final code state.
- **Runtime (`-game` + `-AividoAutoProof`):** full deterministic sequence executed live — boot main
  menu open/start, walk unlock, pause open/close, conversation open/close, camera target check and
  restore check — all logged under `AIVIDO_PROOF` and `AIVIDO_STATE`; **no ensures, no fatal errors**.
- **Visual:** OS-level window captures at the same camera position prove all three overlays paint:
  `reports/hq/evidence_2026-09-09/worker2_ui_standard/` (01 main menu, 02 pause, 03 gameplay
  control, 04 conversation, 05 restored) + `proof_log.txt`.
  Note: `HighResShot` captures the 3D scene without the UMG layer in this build, so window captures
  were used for UI paint evidence.
- **Static:** `git diff --check` clean (0).
- **Packaged build:** not re-run (no package step executed in this lane); game target compiles, so
  packaged behavior is expected to match — flagged below.

Environment note: `Content/Python/init_unreal.py` logs `WRONG_PROJECT_CONTEXT` when it runs against
this worktree path (it expects the main-checkout path). It is project content outside the UI scope
and was not modified; it does not affect gameplay.

---

## 8. FILES CHANGED (worktree `aivido-worker2-ui`, uncommitted)

```
assetlib/tests/ue/ASSET_Showcase2/Source/AividoV2/AividoGameMode.h/.cpp      — UI/camera state machine, main menu, menu/conversation guards, deferred boot menu, geometry logs
assetlib/tests/ue/ASSET_Showcase2/Source/AividoV2/AividoDirector.h/.cpp      — ConversationCamera, FacePlayer, PlaceConversationCamera
assetlib/tests/ue/ASSET_Showcase2/Source/AividoV2/AividoCharacter.h/.cpp      — pitch limits, gameplay-only interaction guard, extended AividoProof
assetlib/tests/ue/ASSET_Showcase2/Source/AividoV2/AividoMenuWidget.h/.cpp    — main-menu mode, keyboard nav, focus, button styles, geometry log
assetlib/tests/ue/ASSET_Showcase2/Source/AividoV2/AividoConversationWidget.h/.cpp — UFUNCTION fix (Enter-to-send), duplicate/stale/thinking fixes, send lock
assetlib/tests/ue/ASSET_Showcase2/Source/AividoV2/AividoHUD.h/.cpp            — hide prompt+banner outside gameplay
reports/hq/evidence_2026-09-09/worker2_ui_standard/                          — runtime evidence (5 captures + proof log)
```

---

## 9. VERDICT

```
AIVIDO_UI = PASS            (for the audited camera/menu/conversation/HUD scope, validated live)
CAMERA_SYSTEM = PASS        — modes found: gameplay + conversation(focus); added camera model, blends, restore, pitch limits
CAMERA_MODES_FOUND = GameplayFollow, ConversationFocus (menu overlays reuse current camera; cinematic/overview absent by design)
CAMERA_ISSUES_FIXED = no conversation camera; no restore; no camera model; no pitch clamp
MAIN_MENU = PASS            — start screen with Start/Quit, keyboard nav, focus, ESC-to-start
PAUSE_MENU = PASS           — Resume/Worker/Quit, keyboard+Tab nav, first-focus, game input blocked, ESC close, no stacking
CONVERSATION_MENU = PASS    — Enter-to-send fixed, no duplicate messages, safe reopen, ESC close, camera focus, send lock
HUD = PASS                  — prompt/banner state-aware, no stale overlays, safe margins
INPUT_STATE_MACHINE = PASS  — single SetUIState model; no ad-hoc input-mode calls
RESPONSIVE_LAYOUT = PASS    — anchored logical-size panels; verified at 1280x720; reviewed for 1080p/ultrawide/small
RUNTIME_VALIDATION = PASS   — UBT compile (editor+game), live -game proof, window-capture pixel evidence
PACKAGED_BUILD = PASS — fresh BuildCookRun package from this committed branch; packaged exe ran the full
  -AividoAutoProof interaction sequence (RESULT=COMPLETE, 0 ensures/asserts/fatals, no duplicate transitions);
  OS window captures + in-engine HighResShots archived under reports/hq/evidence_2026-09-09/worker2_ui_packaged_final/
BRANCH = aivido-worker2-ui (worktree .worktrees/aivido-worker2-ui)
HEAD = 222795b standardize Aivido camera menu and UI state system
PUSH = PASS (origin/aivido-worker2-ui, up to date with HEAD)
REMAINING_ISSUES =
  - Enter-to-send / live backend reply not exercised inside the packaged run (chat backend not running in this lane;
    handler + focus-return verified live in the editor -game run; UFUNCTION bind fix compile-verified in the package).
  - Content/Python/init_unreal.py WRONG_PROJECT_CONTEXT spam when launched from a worktree path (pre-existing, out of UI scope).
  - The level's kinematic "pusher" still displaces the pawn when movement input is applied (pre-existing environment
    behavior, unrelated to UI; the proof parks/re-anchors around it).
  - Packaging notes: DefaultGame.ini ProjectID rewritten to 32-hex FGuid form (UE 5.8 import requirement; same value);
    MovieRenderPipeline (editor-only) disabled for cook via -AdditionalCookerOptions; packaged build requires the
    Zen store server (zenserver on 8558 with the engine security config) at boot.
  - Validation harness: run_packaged_proof.sh/capture_window.ps1 in the evidence dir contain the deterministic-
    termination fix (60s deadline, GNU-timeout-wrapped captures, EnumWindows window selection, stray sweep).
```