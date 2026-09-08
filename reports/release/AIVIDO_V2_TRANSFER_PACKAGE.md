# Aivido V2.0.0 transfer package

TRANSFER_PACKAGE_READY: **YES**

The Windows transfer package is independently runnable from an arbitrary extraction location. The definitive verification used `C:\AividoShip-1a2b3c`, whose path contains none of `Shadow`, `Unreal-Agent`, `Codex`, or the original repository path.

## Package

| Field | Value |
|---|---|
| Source tag | `v2.0.0` |
| Source release SHA | `eb466133f91d553c325d97b99ab93627dfd4aade` |
| Second-system tooling SHA | `9eaccee8656973e905deeb589fb65f619facae9b` |
| ZIP | `outputs/Aivido-V2.0.0-Windows.zip` |
| Size | 728567 bytes |
| SHA256 | `0888899ded45d10478d85a6519a8428c100b44fe121a0f52796cd5b4c8c63d6f` |
| Packaged files | 145 |

## Results

| Check | Result |
|---|---|
| Fresh extraction and ZIP CRC | PASS |
| Manifest and extracted-byte integrity | PASS |
| Release/tooling source provenance | PASS |
| Version 2.0.0 | PASS |
| QA, installer, requirements, UI | PASS |
| Second-system runner included | YES |
| Package-only import smoke | PASS |
| `app.served` boot and UI HTTP 200 | PASS |
| Speech portability | PASS |
| Source-repository independence | PASS |
| Development-venv independence | PASS |
| Blocking runtime paths remaining | 0 |
| Secrets | PASS |
| Junk | PASS |

The backend boot used the extracted package's own `.venv`, with system site packages disabled. The test harness blocked every Unreal bridge call; no live Unreal state was read or mutated. The certified second-system runner passed its hermetic mock acceptance path.

## Path classification

- `app/speak.py`: runtime-required. Gate/config/log paths are package-relative. Python resolves through `AIVIDO_PYTHON`, package-local `.venv`, then `sys.executable`. The gate resources do not exist in the authoritative release, so speech is optional and truthfully returns `speech_resources_missing` before any socket or subprocess activity.
- `app/api.py`: runtime-required. Project creation and visual-review approval paths use the canonical resolver.
- `app/proof.py`: fallback-only runtime. The fallback is based on the configured project root; live project discovery remains authoritative.
- `core/orchestrator.py`: runtime-required. The visual-review command and bridge port use resolved values.
- `tools/unreal/project_context.py`: fallback-only runtime. Fixed project candidates and the bridge port are portable.
- `scripts/aivido_install_check.py`: fallback-only runtime. It no longer searches an original source checkout.
- `config/settings.json`, `tools/unreal/project_manager.py`, and `tools/system/tool_runner.py`: runtime-required. The fixed engine install was removed; resolution uses an environment override or the Epic Launcher registry.
- `ui/aivido.js`, `ui/devboard.html`, and `ui/product.html`: UI display-only. Machine-specific demo text was replaced with neutral examples.
- `ui/ava.js`: the reported strings are public GitHub update URLs, not local paths. They remain unchanged.
- `qa/verifier.py:428`: test-only verifier docstring. It intentionally shows the `C:\Users\Shadow` shape that the verifier rejects and is never treated as a filesystem path.

## Focused validation

`tests/test_transfer_portability.py`, `tests/test_project_context.py`, `tests/test_backend_lifecycle.py`, and `tests/test_plan_normalization.py`: **28 passed**. Python compilation also passed for all packaged runtime modules and acceptance scripts.
