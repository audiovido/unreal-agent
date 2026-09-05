# Aivido UI/UX — Phase 2 Roadmap

Phase 1 delivered the full functional shell with real read-only engine wiring.
Phase 2 is where the presentation goes AAA and the remaining integrations land.

## 1. Character presentation — MetaHuman upgrade path

Phase 1 represents the crew as differentiated CSS figures (silhouettes, skin tones,
headgear, role tools). That is the best Phase-1 representation without bespoke
modeling. Phase 2 path:

1. Import MetaHumans into the engine (the live gateway already advertises a
   `metahuman` domain and a `characters` domain — 28 capabilities available).
2. Build 7 ready-made human presets mapped to the worker roles:
   Mason (Environment), Patina (Materials), Reel (Cinematics), Volt (Blueprint),
   Ember (VFX), Veil (Metahuman), Stride (Animation).
3. Western wardrobe: denim, leather, vests, hats — via Metahuman clothing options
   or Marketplace western packs (prefer ready-made; no bespoke modeling).
4. Use the existing `/api/unreal/frame-and-proof` pipeline to capture **real**
   character renders for the crew strip, choice cards and room backplate.
5. If in-scene MetaHumans prove heavy for the Booth UI, fall back to pre-rendered
   portrait sprites + the CSS room, and reserve live MetaHumans for the Agent Room
   deep-dive view.

## 2. ClickUp sync (external integration blocker)

Phase 1 could not reach ClickUp: no API/MCP credentials exist in this environment.
Phase 2 requires one of:

- A ClickUp API token (env `CLICKUP_API_TOKEN`) + list id for the Aivido queue, or
- A gateway MCP tool that wraps ClickUp (add tool, then the Booth can post progress).

Once available: map the Phase-1 18-item queue to ClickUp tasks, POST progress on
each completion, and surface the queue in Mission Control's live lane.

## 3. Live dispatch from Mission Control

Phase 1 Mission Control is read-only for live tasks (no fake success states).
Phase 2: add dispatch via the existing engine endpoints

- `/api/unreal-coder/async` for Unreal missions
- `/api/code/tasks` POST for code tasks

with the crew state machine bound to real task lifecycle events instead of the
demo timeline. Keep the demo lane for offline play.

## 4. Quests / Finance / Profile backend

These screens are local product data in Phase 1. Phase 2: persist to the repo's
memory store or a small user-state file, and derive Finance ledger entries from
real cloud-credit consumption (overnight/leases API) rather than seeded rows.

## 5. Audio

Phase 1 ships synthesized WebAudio feedback (click/hover/confirm/error/success,
mute toggle). Phase 2: curated ambient loop for the Agent Room (dusk room tone,
lantern crackle), Foreman voice lines (TTS via the gateway's speak tool or a
voice pack), and per-state worker audio cues.

## 6. Productization

- Serve `aivido.html` from the product backend as the primary route (additive
  route only) so the Booth is reachable without the dev server.
- Optional: drop the Google Fonts <link> for a fully-offline bundle.
- Device-size pass for the room (currently desktop-first).

## Acceptance for Phase 2

- MetaHuman crew visible in the Booth or verified pre-render pipeline
- ClickUp progress posting green with real credentials
- One live mission dispatched end-to-end from the Booth UI
- Zero demo-data mislabeled as live anywhere in the UI