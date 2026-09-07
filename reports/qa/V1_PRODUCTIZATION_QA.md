# V1 Productization — Release QA Report

- **Lane:** TEST/QA only (`aivido/v1-productization-qa`)
- **Base:** `aivido/rc1.1-clean-install-fixes` @ `736042ddafb45f34dfed88607e750be73e2877f2`
- **Validates:** upcoming `aivido/v1-productization` branch
- **Date:** 2026-09-07
- **Host:** Windows / Python 3.13.15 / pytest 9.1.1 (repo .venv)
- **Safety:** hermetic-first. No Unreal, no live ports 6766/8765/8844. The launcher
  lifecycle smoke runs the real `app.product_app` backend on an **ephemeral** port only.
- **Rule honored:** no production code was modified in this lane. Defects are reported
  for Freebuff / `aivido/v1-productization`.

## Result summary

| Suite | Result |
|---|---|
| `tests/test_v1_productization_contract.py` (25 contracts, 27 tests) | **25 passed, 1 failed, 1 skipped (opt-in)** |
| Largest safe regression suite (`pytest tests/`, once) | **1076 passed, 1 failed, 2 skipped** (158.7s) |

The single failure across both runs is **one real product defect** (D1 below).
No other regression exists on the RC1.1 base.

## Contract verdicts (V1C-01 .. V1C-25)

| # | Contract | Verdict | Evidence |
|---|---|---|---|
| 01 | clean clone dependency closure | **PASS** | static module-level third-party import scan of `app/`, `core/`, `tools/unreal`, `tools/visual`, `run_agent.py`, launcher, builder == requirements.txt contract; lazy-optional imports (mcp/starlette/psutil) verified to stay lazy |
| 02 | fresh venv install from requirements.txt | **NOT RUN (opt-in)** | network-gated; run with `AIVIDO_QA_FRESH_VENV=1 pytest tests/test_v1_productization_contract.py::test_v1c02_fresh_venv_install` |
| 03 | all required runtime imports | **PASS** | 7-dep import contract + composition roots (`app.served`, `app.product_app`, `app.mcp_gateway`, `core.product_core`) + package builder importable |
| 04 | installer idempotency | **PASS** | `pip install --no-index --dry-run --report - -r requirements.txt` → install list empty |
| 05 | second install does not corrupt/reinstall | **PASS** | two package builds → identical manifest file lists, identical file sets, identical bytes (modulo timestamp metadata), no duplicate artifacts |
| 06 | duplicate backend start protection | **PASS** | second `start_service` on live backend → `duplicate=True`, same pid, no second process |
| 07 | start → health PASS | **PASS** | `start_service` returns ready only after real HTTP probe; `/api/ua/status` == 200 |
| 08 | launcher exits → backend remains alive | **PASS** | real `product_launcher.py start --port <ephemeral>` exits 0; pid alive + health 200 after launcher exit |
| 09 | stop → backend actually stops | **PASS** | launcher `stop` rc 0; port freed; pid dead; health probe fails |
| 10 | restart → backend returns healthy | **PASS** | launcher `restart` rc 0; new pid alive; health 200 |
| 11 | stale PID recovery | **PASS** | dead-pid file flagged `STALE`, auto-cleared by `service_status`; next start succeeds |
| 12 | occupied-port truthful failure | **PASS** | start refused with error naming the port; no pid file left behind |
| 13 | UI /app HTTP 200 | **PASS** | dev console `/app` + product `/` return 200 with real HTML |
| 14 | backend /api/status PASS | **PASS** | `ok=true`, models block present, editor truthfully reported not-ok offline (bridge blocked by pytest conftest) |
| 15 | Unreal-session API schema | **PASS** | OpenAPI contains all 6 `/api/unreal-coder*` paths; request schema `required=["prompt"]`; optional `mode/read_only/dry_run/mission_id/project`; prompt-only dry_run returns canonical envelope |
| 16 | Tailscale unavailable → local mode PASS | **PASS** | no public host configured → loopback-only defaults; `env_doctor` overall PASS/WARNING, never FAIL |
| 17 | remote setup cannot expose silently/publicly | **PASS** | loopback defaults verified in `mcp_gateway` (`--host` default), `run_agent.py`, `app_config` defaults, `service_lifecycle`, `START_AGENT.bat`; no `0.0.0.0` anywhere in defaults |
| 18 | secrets absent from package | **PASS** | built dist scanned: no key/pem/env/secret-named files; no private-key blocks, `avmcp_` keys, AWS ids, or secret-assignments in text files |
| 19 | temp/cache/worktree junk absent from dist | **FAIL — REAL PRODUCT DEFECT (D1)** | see below |
| 20 | installer failure produces useful logs | **PASS** | failed boot leaves non-empty err log with traceback; broken requirements fails loudly naming the missing distribution |
| 21 | no fake PASS when backend/process dies | **PASS** | after kill: `service_status.ready=False`, state != RUNNING, health probe fails; `ensure_running` never returns ok without a real ready probe; failed mission response can never carry `verdict=PASS` |
| 22 | package Quickstart ≤ 3 user actions | **PASS** | packaged README lists exactly 3 `product_launcher.py` commands; zip ships for one-step download |
| 23 | RC1.1 truthfulness regressions preserved | **PASS** | zero-step FAIL guard present in `core/mission.py`; capture intent flags `read_only/capture_only` intact |
| 24 | capture_unreal_viewport regression preserved | **PASS** | capture prompts plan a real READ-ONLY `capture_unreal_viewport` EVIDENCE step; no mutating tools |
| 25 | REQUESTED_TOOL_MISSING preserved | **PASS** | `_extract_requested_tools` + registry membership + gate source (`REQUESTED_TOOL_MISSING`, "refusing to report success") all intact |

## Defects reported (NOT fixed in this lane)

### D1 — REAL PRODUCT DEFECT · tracked worktree junk ships inside the product package · MAJOR, release blocker candidate

**Contract:** V1C-19. **Test:** `tests/test_v1_productization_contract.py::test_v1c19_no_junk_in_dist`.

`scripts/build_product_package.py` copies `ui/` verbatim (ignore list only excludes
`*.agentboard_backup`). Three junk items are **tracked in git** on the RC1.1 base and
therefore land in every shipped `dist/unreal-agent-*/` and its zip:

```
ui/backup-20260820-081408/app.js
ui/backup-20260820-081408/index.html
ui/backup-20260820-081408/styles.css
ui/ui.zip
ui/index.html.broken-encoding
```

**Impact:** every release package ships dead weight (a timestamped UI backup, a stale
`ui.zip` build artifact, and a broken-encoding HTML file). Bloats the download, confuses
the runtime UI tree, and violates the V1 packaging hygiene contract.

**Fix direction for `aivido/v1-productization`:** remove the three tracked junk items
from git, and add `backup-*`, `*.zip`, `*.broken-*` to the packager's
`shutil.ignore_patterns` so the source-tree state can never leak into dist again.

### D2 — MAJOR · MCP gateway is not installable from the clean dependency contract

**Evidence:** `app/mcp_gateway.py` lazily imports `mcp` (lines 608, 691) and
`starlette` (lines 685, 765) at feature time, but neither is in `requirements.txt` —
the file that declares itself "the single source of truth for installers". On a clean
clone the backend boots fine (lazy imports are correctly out of module scope — V1C-01
enforces that), but starting the gateway feature (`python -m app.mcp_gateway`) crashes
with `ModuleNotFoundError: No module named 'mcp'`.

**Fix direction:** ship an `requirements-optional.txt` (or documented extras) for the
gateway, or add the SDK to the authoritative contract.

### D3 — PRE-EXISTING / NON-BLOCKING · OpenAPI duplicate operation IDs

`app/unreal_coder_api.py` and `app/camera_api.py` emit
`UserWarning: Duplicate Operation ID ...` for every registration
(11 unreal-coder operations + 3 camera operations). Schema generation still succeeds
(all V1C-15 assertions pass), but tooling that consumes operation IDs may alias
endpoints. Cosmetic-to-minor; fix by namespacing operation IDs per registration.

### D4 — OBSERVATION · non-blocking

- `scripts/mcp_gateway_validate.py` imports `httpx2` (script-scope only, not runtime).
- FastAPI `on_event` deprecation warnings in `app/api.py` / `app/served.py`
  (lifespan migration candidate; no behavior impact today).
- V1C-02 (fresh venv) is network-gated and was not executed in this offline lane;
  contracts V1C-01/03/04/05 cover the closure statically and against a real
  satisfied environment.

## Harness defects found and fixed during this run (QA-lane only)

1. `V1C-05` — byte-hash comparison included `manifest.json` (contains `built_at`).
2. `V1C-08/09/10` — launcher subprocess argv vector was malformed (`scripts` treated as the script).
3. `V1C-14` — asserted the legacy `bridge_status` key; canonical `/api/status` reports editor state under `unreal`.
4. `V1C-16` — `load_public_host()` returns `""` (falsy) when unconfigured, not `None`.
5. `V1C-16` — doctor vocabulary is `PASS/WARNING/FAIL`; assertion expected `WARN`.

## Classification of every remaining failure

| Failure | Classification |
|---|---|
| `test_v1c19_no_junk_in_dist` | **REAL PRODUCT DEFECT** (D1) |
| `test_v1c02_fresh_venv_install` skipped | PRE-EXISTING / NON-BLOCKING (opt-in, network-gated) |
| (full suite) 2 skipped | PRE-EXISTING / NON-BLOCKING (unchanged RC1.1 opt-outs) |

No HARNESS DEFECT failures remain. **Zero critical defects found.**

## Gate recommendation

`aivido/v1-productization` must fix **D1** (and is strongly advised to fix **D2**)
before release sign-off. Everything else on the RC1.1 base is release-clean.
