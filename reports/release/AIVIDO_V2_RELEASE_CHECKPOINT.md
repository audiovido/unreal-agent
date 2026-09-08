# AIVIDO V2 RELEASE — RESUME CHECKPOINT

- **Written:** 2026-09-08 (UTC), resume-from-checkpoint run
- **Active worktree:** `C:/Users/Shadow/Desktop/Unreal-Agent/.worktrees/v2-release`
- **Branch:** `aivido/v2-release` @ `6772f35` ("Aivido: certify V2 final release ready")
- **Root worktree:** untouched. **main:** untouched.

## Completed phases (DO NOT REDO)
1. Final release gate certified: `reports/release/AIVIDO_V2_FINAL_RELEASE_GATE.{md,json}` — FINAL_RELEASE_READY: YES.
2. Canonical QA 63/63 PASS, 0 open defects; full regression 1204 passed / 1 skipped / 0 failed (stored, not rerun).
3. Cinematic MRQ evidence: committed MP4 + `frame_manifest.json` (240 frames, sha256-verified).
4. Package built: `dist/Aivido-V2` (155 files, no junk/secrets, pinned `f66c286…`).
5. UI release identity regenerated in worktree working tree: `ui/ui-version.json`, `ui/release-manifest.json`, `ui/build-manifest.json` → version 2.0.0, build_id `20260907-v2release`, git_sha `6772f353f99625e9d257c626995ba772861f600d` (NOT yet committed).

## Remaining phases
1. Clean-install acceptance (fresh venv from package `requirements.txt`, backend boots, UI served).
2. Runtime gates: `GET /api/status` 200 + unreal ok; read-only doctor PASS; malformed-input truthfulness (400/404/422).
3. UI gate: release identity 2.0.0 @ `6772f353…`, routes serve, build manifest parity.
4. Mission gates: one real read-only E2E mission to terminal PASS + truthful-fail path (unknown tool).
5. Restart gate: backend restart, sessions preserved. Preservation gate: read-only AividoHQ probe all_pass.
6. Final acceptance JSON + MD in `reports/release/` (AIVIDO_V2_ACCEPTANCE).
7. Commit intentional release artifacts only (reports + 3 UI manifest files). Delete throwaway `_probe_*`/`_run_*`/`_check_*`/`_read_*` scripts (untracked, never committed).
8. Push `aivido/v2-release`.
9. Tag `v2.0.0` + push — ONLY if all blocking gates PASS.

## Active ports / processes
- 127.0.0.1:8765 → PID 16840 (live canonical backend, do not kill; used for runtime/mission gates)
- 127.0.0.1:6766 → PID 7052 (Unreal bridge, UE 5.8.2, ASSET_Showcase2)
- 100.84.156.24:8765/6766 → PID 3588 (same stack, external interface)
- Clean-install backend will use 127.0.0.1:8790 (per RC1.1 precedent)

## Paths
- Package: `dist/Aivido-V2` (gitignored; identity in `reports/release/AIVIDO_V2_PACKAGE.json`)
- Clean-install dir: `%TEMP%/aivido_v2_clean_install` (create fresh; do not reuse old dirs)
- Acceptance outputs: `reports/release/AIVIDO_V2_ACCEPTANCE.json` + `.md`
- Checkpoint (this file): `reports/release/AIVIDO_V2_RELEASE_CHECKPOINT.md`

## Mission IDs
- Historical/canonical: `qar_fc286b5a22d0` (63/63), release-95 missions A/F/C (done/failed-truthful/done), RC1.1 clean-clone `mission_631b6f668cf8`.
- This run: to be generated during mission gates; record in acceptance JSON.

## Current blockers
- None known. UI manifest diffs uncommitted (intentional, commit in phase 7). Many untracked throwaway probe scripts in worktree root (delete before commit; never stage them).

## Exact next action
Create fresh clean-install dir from `dist/Aivido-V2`, install venv from `requirements.txt`, boot backend on 127.0.0.1:8790, verify `GET /api/status` 200 + UI served, then proceed to runtime gates.
