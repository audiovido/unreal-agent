# AIVIDO V2 — FINAL ACCEPTANCE

- **Acceptance time:** 2026-09-08 (UTC)
- **Branch:** `aivido/v2-release`
- **Source SHA:** `6772f353f99625e9d257c626995ba772861f600d`
- **Verdict:** **ACCEPTED — all blocking gates PASS**

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| **Clean install** | **PASS** | Fresh venv installed solely from `requirements.txt` (fastapi, uvicorn, pillow, numpy, pydantic, requests, rich): `IMPORT_CONTRACT_OK`. Backend boots on 127.0.0.1:8790: `/api/status` HTTP 200 `ok=true, unreal=ok` (UNREAL_BRIDGE_READY, engine 5.8.2); product UI `/` HTTP 200. |
| **Runtime** | **PASS** | Canonical backend 127.0.0.1:8765 HTTP 200, `ok=true unreal_ok=true`; quick doctor via venv interpreter: **9 PASS / 1 WARN (release_sha, pre-commit only) / 0 FAIL**; bridge 6766 live (ASSET_Showcase2, UE 5.8.2, AividoHQ). Truthfulness: unknown session 404, unknown project 404, unknown `/api/action` 400 `Unknown action: …`, invalid JSON 422, path traversal 404. |
| **UI / release identity** | **PASS** | Served release identity: `2.0.0` / build `20260907-v2release` / git_sha `6772f353f99625e9d257c626995ba772861f600d` / content_hash `ca8c0e55…`. Routes `/`, `/app`, `/dev`, `/static/*` all 200. SHA-256 parity 8/8 between committed `ui/` and served package UI (incl. aivido.css 76240B, aivido.js 96086B); build-manifest file parity PASS. |
| **Missions** | **PASS** | E2E read-only capture mission `mission_f775435673e5`: **complete / PASS**, 3/3 completed work (inspect_project, unreal_ping, capture_unreal_viewport), real viewport evidence 1,292,352 bytes. Session flow `exec_4d37b24a65`: PASS 3/3. **Truthful fail** `exec_00693e537d`: `REQUESTED_TOOL_MISSING` → mission `failed / FAIL`, no fake success. Zero-step missions fail truthfully (`0-step empty-plan PASS blocked`). |
| **Restart / persistence** | **PASS** | Clean backend killed + restarted: `/api/status` 200; session `sess_bccaf59e09` (project `proj_57956d17`, bridge 127.0.0.1:6766, unreal_pid 7052, `/Game/Maps/AividoHQ.AividoHQ`, engine 5.8.2) visible after restart; session START → READY with bridge reuse. |
| **Preservation** | **PASS** | `scripts/recert/v2_release_preservation_probe.py` (read-only, no mutation): **all_pass true**, 12/12 gates (bridge reachable, project identity, map loaded, characters 8/8, actors 166, props, screens 8/8, UI text, lights all movable, no broken roots, no missing materials, CineMRQ isolated). |
| **Package** | **PASS** | `dist/Aivido-V2` rebuilt deterministically from this SHA by `scripts/build_v1_package.py` — `TOP_LEVEL_PY_DIRS` now includes `qa/` because `app.served` imports `qa.api` at startup (package previously booted cleanly only after this fix; fresh-venv boot now verified). 163 files, `version.json` pins `aivido/v2-release@6772f35`, hygiene clean (no pyc/junk/secrets). |

## Release-blocking defect found and fixed this run

The prior `dist/Aivido-V2` package could not boot on a truly clean machine:
`ModuleNotFoundError: No module named 'qa'` at `app/served.py` startup, because the
V2 autonomous-QA API (`qa/`) is wired into the runtime but the builder's copy list
(`TOP_LEVEL_PY_DIRS`) omitted it. Fix: `scripts/build_v1_package.py` includes `qa`.
Rebuilt package now passes the full clean-install acceptance above.

## Reference (stored, not rerun)

- Final release gate: `reports/release/AIVIDO_V2_FINAL_RELEASE_GATE.md` — `FINAL_RELEASE_READY: YES`.
- Canonical QA: `qar_fc286b5a22d0` — 63/63 PASS, 0 open defects.
- Full regression: 1204 passed / 1 skipped / 0 failed.

## Post-commit doctor

Quick doctor at commit `b6ea277`: **10/10 PASS, 0 WARN, 0 FAIL** (release_sha
resolved once the UI manifests + builder fix were committed).

## Counts

- Critical: **0** · Major: **0** · Minor: **0** · Warnings: **0**

## Decision

**All blocking gates PASS → tag `v2.0.0` eligible.**