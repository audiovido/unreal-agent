# Worker 2 — PACKAGED BUILD FINAL GATE (2026-09-09)

Branch: `aivido-worker2-ui` · HEAD: `222795b` (code) → packaging-gate commit
Package: `BuildCookRun` Win64 Development, cooked+staged+packaged+archived,
`-AdditionalCookerOptions="-DisablePlugins=MovieRenderPipeline"` (editor-only
plugin's preview assets are not cookable for Windows — not part of the game).

## Config fix required for packaging
`assetlib/tests/ue/ASSET_Showcase2/Config/DefaultGame.ini`: `ProjectID` was a
hyphenated GUID, which UE 5.8's `FGuid::ImportTextItem` cannot import (it
requires exactly 32 hex digits). The cook commandlet treats any logged Error
as a cook failure. Rewritten to the same GUID in 32-hex form:
`5DD01C53C88145689E507029C9FAAB33` (value unchanged semantically).

## Environment prerequisites discovered
- The packaged build streams from the Zen store (`ue.projectstore`); the game
  hard-fails at boot if no zenserver with the matching security config listens
  on 8558. Start it with the engine's security config before launching:
  `zenserver --port 8558 --data-dir <Zen Data> --http asio --security-config-path <security-config.json>`.

## Runtime validation (packaged exe, `-AividoAutoProof`)
Deterministic sequence on the real handlers — RESULT=COMPLETE, 0 ensure /
assert / fatal lines, no duplicate state transitions (each exactly once):

```
AIVIDO_UI: main_menu vp=1 vis=1                 → boot main menu paints
AIVIDO_STATE: 0 -> 1  (Gameplay -> MainMenu)
AIVIDO_STATE: 1 -> 0  (start -> Gameplay)        menu_open=false, walk disp=1995.5
AIVIDO_STATE: 0 -> 2  (pause)                    pause_open=true, cursor=1
AIVIDO_STATE: 2 -> 0  (resume)                   paused_closed=false
AIVIDO_STATE: 0 -> 3  (Conversation, camera=1)   cursor=1, move/look locked
AIVIDO_PROOF: conv_camera_target=AividoDirector  conversation camera active
AIVIDO_STATE: 3 -> 0  (camera=0, cursor=0)       ESC closes conversation
AIVIDO_PROOF: restored_camera=AividoCharacter is_pawn=true   camera restored
```

## Evidence files (this directory)
- `01_main_menu.png` … `05_gameplay_restored.png` — OS window captures
  (1027x671 client area of the 1280x720 windowed game), one per UI state.
- `*_1080.png` — same sequence at 1920x1080 request (4/5 captured; last
  capture raced the cleanup sweep; 720p set is complete).
- `inengine_shots/HighresScreenshot*.png` — the game's own 6 in-engine
  HighResShots (2022x1264), one per proof step, from the final run.
- `packaged_proof_log.txt` — full packaged-run log (AIVIDO_PROOF/STATE/UI lines).
- `packaging_log.txt` — UAT log tail (BUILD SUCCESSFUL, ExitCode=0).
- `run_packaged_proof.sh` + `capture_window.ps1` — the validation harness.

## Validation checklist results (packaged)
- ESC gameplay→pause PASS · ESC pause→resume PASS · ESC conversation→close PASS
- E interaction opens conversation PASS (proof drives HandleInteract — same
  path as the E keybinding)
- Repeated E/ESC do not stack UI PASS (state machine guards; each transition
  logged exactly once per run)
- No movement/look while menu/conversation open PASS (IgnoreMove+IgnoreLook
  logged in every UI state; walk displacement only between 1→0)
- No stale HUD prompt / no duplicate welcome / no duplicate replies PASS
  (HUD hidden outside Gameplay; welcome only on empty transcript; reply
  delegate RemoveAll before rebind — see WORKER2_UI_CAMERA_MENU_STANDARDIZATION.md)
- Conversation camera activates + restores PASS
- No crashes, no ensures PASS
- Enter-to-send: interactive typing not exercised by the deterministic harness
  (requires OS-level key injection); the commit handler + focus return were
  verified live in the editor -game run per WORKER2_UI_CAMERA_MENU_STANDARDIZATION.md,
  and the UFUNCTION bind fix is compile-verified in this packaged build. The
  chat backend was not running, so live "reply" round-trips are excluded here.
- Quit handler = UKismetSystemLibrary::QuitGame (code-verified).

## Verdict
PACKAGED_BUILD = PASS (interaction validation + screenshots from the packaged
executable; backend-dependent live reply step noted above).

## Harness termination fix (this session)
The outer driver could hang until timeout: (a) backgrounded capture subshells
inherited the tool's stdout pipe, so a hung capture kept the pipe open after
bash exited; (b) Win32 capture calls can block indefinitely; (c) the game
process owns TWO top-level windows and Process.MainWindowHandle flips to the
stale bootstrap one. Fixes: all capture output redirected to a log file, every
capture wrapped in GNU `timeout 10`, window enumeration via EnumWindows across
all PIDs with title/visibility/size filters, break on the final proof marker
with a 60s hard deadline, stray-process sweep at exit.
