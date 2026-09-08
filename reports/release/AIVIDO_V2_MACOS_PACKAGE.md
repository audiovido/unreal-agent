# Aivido V2.0.0 macOS Package Report

## Identity

- Source branch: `aivido/v2-transfer-package`
- Source SHA: `3ce4a86d41756c670255f9e6cd1d21d914e339f8`
- Product version: `2.0.0`
- Package branch: `aivido/v2-macos-package`
- Tag `v2.0.0`: not modified or retagged

## Artifact

- ZIP: `reports/release/Aivido-V2.0.0-macOS.zip` (727,725 bytes)
- SHA file: `reports/release/Aivido-V2.0.0-macOS.sha256.txt`
- SHA-256: `d9073cae0b07deab47bacb602d19cf0c430a663b6a5c986ed85670b4ccb4ee12`
- Packaged file count: `143`

## Implemented

- Portable `install-aivido.sh` and `start-aivido.sh` with `start`, `stop`, `restart`, `status`, `doctor`, and `ui` controls.
- Package-local `.venv/bin/python` contract on macOS; idempotent `requirements.txt` installation.
- Platform-aware process ownership, detached runtime, PID/state/log handling, and cleanup that refuses foreign processes.
- Unreal detection from `/Users/Shared/Epic Games/`, `/Applications/Epic Games/`, and explicit `UNREAL_AGENT_ENGINE_DIR` / `--unreal-exe` overrides.
- UE major-version gate requiring Unreal Engine 5 or newer.
- POSIX second-system runner with the 20 acceptance phases, one read-only mission, evidence freshness/stale-evidence checks, restart, JSON report, and owned-process cleanup.
- Hermetic acceptance-runner self-test covering success plus 16 expected failure scenarios.

## Verification

- ZIP integrity and extraction: PASS.
- Python syntax: PASS.
- Package-local import smoke including `app.served`: PASS.
- Fresh extraction installer: PASS.
- Backend boot and `/api/status`: PASS.
- UI HTTP 200: PASS.
- Status/restart/stop lifecycle: PASS.
- Doctor quick: PASS (10/10 on the available local bridge; read-only probes only).
- Acceptance runner mock matrix: PASS (17/17).
- No live Unreal mutation during package-prep validation: PASS.
- Source-repository independence: PASS.
- Developer-venv independence: PASS.
- ZIP names contain no Shadow/Codex/Unreal-Agent paths and no Windows launcher artifacts: PASS.
- Optional speech remains truthful when unavailable: PASS by contract.

## Hygiene

The ZIP contains no credentials, private keys, generated logs, PID files, bytecode, or junk artifacts. Source text that mentions secret environment-variable names or forbidden-path examples is policy/verifier documentation, not a secret or runtime dependency.

## Blockers

None for the portable macOS package and hermetic acceptance runner. A real second-system live acceptance still requires a separate Mac with UE 5.x, the Aivido bridge, the expected project/map, and a renderable viewport; package-prep tests intentionally do not mutate the live Unreal scene.
