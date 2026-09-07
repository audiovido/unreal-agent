# AIVIDO — POLISH-90 INDEPENDENT RE-CERTIFICATION

- **Date:** 2026-09-06 (overnight mission)
- **Subject:** `aivido/polish-90` @ `9fb11ef416a308e267d76ba671cd676692573c7d`
  (contains the stated polish source `3b0b4d1616da6f60158eb9669b9543ddcab82131`
  plus the closeout commit `9fb11ef` "polish-90 closeout - live re-verification and final evidence")
- **Certified baseline reference:** `aivido/final-product-certification` @ `1c082f0` (80/100)
- **Recert branch:** `aivido/polish-90-recert`

This document merges two independent live re-verification passes performed during the
overnight mission (Session A: bridge + backend + headless-Chrome-CDP verification;
Session B: committed probe-script verification with raw JSON evidence). Both reached
the same decision independently.

## Decision

## VERIFIED_90_PLUS

Independent re-certification score: **90/100** (conservative; every claim below is backed
by a live probe executed this session, not inherited from the polish report).

## Required checks — all executed live

| # | Check | Result | Evidence (A / B) |
|---|---|---|---|
| 1 | AividoHQ loads | PASS | `/Game/Maps/AividoHQ` open; reopened via `load_level` (A, B) |
| 2 | 8/8 characters | PASS | `AVIDO_Human_{Master,Creative,Visual,Technical,Audio,Animation,Lighting,VFX}`, all valid roots (A, B) |
| 3 | Idle motion truly changes transforms | PASS | PIE live: 8/8 displaced (B: planar 0.14–1.94 cm, vertical ≤2.84 cm, 918 ticks/~9 s ≈ 102 ticks/s; A: planar 1.06–2.08 cm, vertical 0.63–3.35 cm, ~110 ticks/s foreground over 10 s) |
| 4 | Idle stop restores exact transforms | PASS | position AND yaw error **0.0 on all 8** (independent before/after capture, both sessions) |
| 5 | Lighting rebuild warning remains 0 | PASS | 41/41 lights MOVABLE (0 static / 0 stationary — warning condition impossible); fresh OS window captures show lit room, no banner (A, B) |
| 6 | Room intact | PASS | 166–173 actors (counting-method delta), 0 broken roots, 0 missing materials (A, B) |
| 7 | Props intact | PASS | 23/23 `W3I_*` props (also after reopen) |
| 8 | In-world UI intact | PASS | 8 TextRender actors / `AIVIDO_UI_*` boards + 8–12 screens/panels; text world_size 32/32/30 verified live (A) |
| 9 | Web UI 360/390/430 | PASS | A: Chrome headless CDP computed styles — CTAs stacked, right edge 299<360 / 329<390 / 369<430 (no overflow); B: backend-served `/app` headless-Edge renders at all three widths, no horizontal trap |
| 10 | Map save/reopen | PASS | `save_dirty_packages` True → `load_level` identity_ok → post-reopen census stable: 8 chars / 23 props / 0 stationary lights / 8 texts (A, B) |
| 11 | Backend reachable | PASS | `GET /api/status` → 200, `unreal.ok=UNREAL_BRIDGE_READY`, ollama READY (backend was DOWN at mission start; restarted, startup verified) |
| 12 | Bridge reachable | PASS | bridge ping + identity (ASSET_Showcase2, UE 5.8.2-56702186) (A, B) |
| 13 | Planner screenshot/EVIDENCE fix present | PASS | `app/api.py` emits `EVIDENCE`-phase steps (`capture_unreal_viewport`/`capture_pie_viewport`) incl. fallback guarantee (~line 925); polish diff touches only reports+ui+idle driver (A, B) |
| 14 | No critical regression | PASS | zero critical, zero major in both passes |

## Idle-driver live motion detail (Session B probe, PIE, 8/8)

Displacement from true base at ~9 s (cm):

| Character | planar | dz |
|---|---|---|
| Master | 0.815 | -2.598 |
| Creative | 1.944 | -0.422 |
| Visual | 0.794 | -2.844 |
| Technical | 0.380 | -1.901 |
| Audio | 1.498 | -1.714 |
| Animation | 1.137 | -2.843 |
| Lighting | 0.140 | -0.991 |
| VFX | 1.051 | -2.575 |

- Per-character phase/frequency variation confirmed (no two identical).
- Duplicate `start_idle_driver()` returns `already=True` — no double registration.
- `stop_idle_driver()` restored 8/8 at exact base (max |Δ| = 0.0); stats `running=false`, callback torn down.

## New finding (Session A — documentation accuracy warning)

The UI board text color is actually **amber RGB(255,235,6)**, not the documented cyan
(6,235,255): `unreal.Color`'s constructor is (b,g,r,a), so `Color(6,235,255,255)` stored
r=255 (verified live). The functional goal — bright high-contrast text, no longer dim
red — is still met and sizes are correct. No scene changes were made during recert.

## Warnings carried forward (unchanged from polish-90, not regressions)

1. **PIE character rendering** — SkeletalMeshActors render in the editor viewport but not
   in the PIE game viewport in this engine configuration (pre-existing). Visual character
   proof = editor-viewport capture; motion proof = transform telemetry. `PIE_CHARACTER_RENDER = WARN`.
2. In-world UI remains static TextRender (no interactive UMG — UE 5.8 python surface).
3. Idle yaw drift reads as 0 in deltas (characters' rotation lock overrides yaw) — position
   motion is the dominant verified effect.
4. Sub-pixel characters in wide team shots (documented in polish-90).

## Environmental notes (not product defects)

- Backend was **down** at session start; restarted it (`uvicorn app.api:app` on 8765) — startup verified.
- A stale process from 08:35 (PID 3612) listens on the tailscale interface only (100.84.156.24:8765);
  it does not serve 127.0.0.1 and was left untouched.
- Two `app.mcp_gateway --port 8844` processes existed; one holds the port, the other lost the bind.
  Recorded for the overnight performance/duplicate-poller pass.
- `origin/aivido/polish-90` does not exist on the remote (aivido/* branches are local-only);
  verification therefore targeted the local branch at the pinned SHA above.

## Evidence

- `scripts/recert/polish90_recert_probe.py` — reproducible probe (committed on this branch)
- `reports/hq/POLISH_90_RECERT_EVIDENCE/recert_probe.json` — raw Session-B probe output (all gates)
- `reports/hq/POLISH_90_RECERT_EVIDENCE/recert_editor_window.png` — fresh editor capture (lit room, no rebuild banner)
- `reports/hq/POLISH_90_RECERT_EVIDENCE/web_ui_{360,390,430}px*.png` — backend-served UI renders
