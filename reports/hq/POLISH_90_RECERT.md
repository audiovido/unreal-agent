# AIVIDO — POLISH-90 INDEPENDENT RE-CERTIFICATION

- **Date:** 2026-09-06
- **Baseline:** 80/100 @ `1c082f0` (`aivido/final-product-certification`)
- **Polish source:** `aivido/polish-90` (claimed commit `3b0b4d1`, verified tip `9fb11ef`), claimed 90/100
- **Recert branch:** `aivido/polish-90-recert`
- **Independent verified score:** **90/100**
- **Decision:** **VERIFIED_90_PLUS**

All gates below were run live this session by the recertifier through the editor bridge (127.0.0.1:6766), the live backend (:8765), and headless Chrome CDP — not copied from Freebuff's evidence.

## 1. Unreal gates — PASS

- **Map:** `/Game/Maps/AividoHQ` loads (verified live; also re-opened via `load_level` during save/reopen gate).
- **Characters:** **8/8** (`AVIDO_Human_Master/Creative/Visual/Technical/Audio/Animation/Lighting/VFX`).
- **Save/reopen:** `save_dirty_packages` True → `load_level` OK → post-reopen scan stable (173 actors).
- **Actor state:** 0 content actors with broken root; 0 static-mesh components missing a material; no critical broken references.
- **Props/screens/boards:** 23/23 `W3I_*` props, 8/8 screens, 6/6 `AIVIDO_UI_*` boards preserved; text world_size verified live at **32/32/30**.
- **Lighting rebuild warning: RESOLVED** — 41/41 lights MOVABLE (0 STATIC, 0 STATIONARY, root cause remains removed after reopen); fresh OS window capture of the reopened editor shows a lit room and **no rebuild banner**.

## 2. Character motion — PASS

Independent before/during/after cycle (recertifier captured base transforms itself):

- Driver starts OK; **8/8 actors receive real transform motion** (max displacement measured **2.68 cm**; live sample planar 1.06–2.08 cm, vertical 0.63–3.35 cm — matches the documented 2–4 cm bob / 1–2 cm sway design; bounded and subtle).
- **Stop restores exact base transforms:** position AND yaw error **0.0** on all 8 (independent comparison, not driver-reported).
- **No fake visual-motion claim:** the polish report honestly documents the PIE-render limitation; motion is proven by transform telemetry, not fabricated frames.

## 3. Performance — PASS

- Method: slate post-tick call delta over 10 s via bridge, `r.ThrottleCPUWhenNotForeground 0`, editor brought to foreground.
- **Measured: ~110 ticks/s foreground** (1100 calls / 10 s) vs the old throttled ~3 FPS (unfocused) → materially higher. Backgrounded reference: ~6.2 ticks/s.

## 4. Web UI (360/390/430) — PASS

- Method: Chrome headless CDP against the live backend `/app`; `getComputedStyle` + `getBoundingClientRect`.
- 360 px: CTAs stacked, right edge 299 < 360 — no overflow.
- 390 px: stacked, right edge 329 < 390; screenshot visually confirms clean stacked buttons — **CTA clipping regression is GONE**.
- 430 px: stacked, right edge 369 < 430.
- No redesign performed (as instructed).

## 5. Visual proof — inspected, usable

Existing polish evidence reviewed (`final_reopen_warning_check.png`, `shot4b_room_lighting.png`, `shot1_hq_wide.png`, `shot6_inworld_ui.png`): lit room, dynamic lighting visible, no warning banner. No new cinematic set created (as instructed). Carried warnings: PIE character rendering (pre-existing), sub-pixel characters in wide shots.

## 6. Previously certified product path — NO REGRESSION

- **Backend:** reachable (`GET /api/status` 200; `unreal: ok UNREAL_BRIDGE_READY`, engine 5.8.2).
- **Bridge:** reachable (every gate this session ran through it).
- **Planner EVIDENCE-step fix:** still present (`app/api.py` EVIDENCE phase handling intact; the polish diff touches only reports + ui + the idle driver).
- Critical/major regressions: **none**.

## 7. New finding (warning — documentation accuracy)

The UI board text color is actually **amber RGB(255,235,6)**, not the documented cyan (6,235,255): `unreal.Color`'s constructor is (b,g,r,a), so `Color(6,235,255,255)` stored r=255 (verified live). The functional goal — bright high-contrast text, no longer dim red — is still met and sizes are correct. No scene changes were made during recert.

## 8. Verdict

Freebuff's claimed 90 is **truthful and independently reproduced**: all five polish items verified live, zero regressions to the certified 80-path.

- Critical errors: **0**
- Major errors: **0**
- Warnings: **4** (1 new doc-accuracy finding; 3 carried from the polish report)

**Decision: VERIFIED_90_PLUS**
