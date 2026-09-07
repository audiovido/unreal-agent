# AIVIDO — Parallel QA Defect Closure

**Branch:** `aivido/qa-defect-fixes`
**Source:** `aivido/parallel-qa-automation` @ `9d52422b46afee1cfefce2eb8e4e94a87b4283a8`
**Mode:** OFFLINE / HERMETIC — no Unreal Editor, no live bridge/backend, no
ports 6766/8765/8844, no overnight-worktree or `main` changes.

Closes the 4 verified offline defects found by the parallel QA lane. Test-only
verification: the 4 intentional defect checks now PASS (86/86 in the QA suites).

---

## QA-1 — MAJOR: invalid JSON in WORKER2 manifest — **PASS**

**Fix:** `reports/hq/WORKER2_CHARACTERS_MANIFEST.json` line 164
`"master_materials": quarter2,` → `"master_materials": 2,`

**Truthful value source (no invented data):** the character pipeline
(`assetlib/tools/ue_hq_characters.py`) builds exactly two master materials —
`M_Aivido_Skin` (SSS skin) and `M_Aivido_Cloth` — with per-character MICs
(`Aivido_Head`, `Aivido_Body`) giving 8 × 2 = 16 instances, matching the
manifest's own `"material_instances": 16`. Confirmed independently by
`reports/hq/WORKER2_CHARACTERS_HANDOFF.md` line 100:
**"Material Count: Optimized (2 masters + 16 instances)"**. The sibling
`performance_metrics` fields are counts, so `2` is the consistent type.

**Validation:** all 27 `reports/**/*.json` files now parse as JSON (previously
WORKER2_CHARACTERS_MANIFEST.json failed).

## QA-2 — MINOR: unguarded localStorage in `ui/aivido.js` — **PASS**

**Fix:** all 4 unguarded accesses wrapped with the project's existing
safe-storage pattern (`try { ... } catch (_) {}`, same style as the already
guarded `questStore`/`ledgerStore` readers):

1. top-level state read (line ~56): falls back to `DEFAULT` when storage is
   blocked → **boot can no longer throw**
2. `persist()` (line ~115): write fails safely
3. `questTick` `setItem` (line ~1087): write fails safely
4. `ledgerAdd` `setItem` (line ~1093): write fails safely

Behavior is unchanged when storage works (same values, same keys, same write
semantics). `node --check` passes. The hermetic guard check
(`test_all_localstorage_access_is_guarded`) now passes; its heuristic was also
tightened to require the try/catch guard on the access line (the project's
one-line guard pattern).

## QA-3 — MINOR: stale `build-manifest.json` hash — **PASS**

**Fix:** recomputed sha256 from actual committed file content:

| file | manifest before | manifest after (== committed file) |
|---|---|---|
| `aivido.html` | `ce771b9e…` | `800f2a13…` (was already stale vs committed `c1f4d5a7…`) |
| `aivido.js` | `dab4e2b5…` | `10baa905…` (changed by QA-2/QA-4, recomputed truthfully) |

Only the affected entries were touched. Cache-bust pin in `aivido.html`
(`/static/aivido.js?v=10baa905`) updated to match the new JS hash so browsers
pick up the guarded bundle; CSS pin unchanged. `test_manifest_hashes_match_files`
passes for all 15 manifest entries.

## QA-4 — INFO: duplicate `homeEnterRoom` in REFS — **PASS**

**Fix:** removed the second occurrence from the `REFS` array in `ui/aivido.js`
(the trailing entry on the settings line). `el.homeEnterRoom` is still assigned
from the first occurrence; the single click listener is unaffected. `node --check`
and the DOM-id suite pass.

---

## Verification battery

| Check | Result |
|---|---|
| 86 parallel QA tests (4 suites) | **86 passed / 0 failed** |
| Relevant UI tests (`test_ui_release`, `test_ui_detection_structure`, `test_live_ui_detector_graduation`) | **37 passed / 0 failed** |
| JSON parse validation (all `reports/**/*.json`) | **27/27 parse** |
| `node --check ui/aivido.js` | **PASS** |
| `git diff --check` | **clean** |
| Largest safe hermetic suite (`tests/`) | **1020 passed, 1 skipped, 1 failed** |

## Pre-existing vehicle blocker (NOT fixed, per mission)

`tests/test_api_action_vehicle_integration.py::test_vehicle_profile_keeps_bounded_strategy_and_corrected_locator`
remains **BLOCKED**: it requires generated proof artifact
`assetlib/proof/vehicle_showcase_controlled_20260905/final_fresh_vehicle.png`,
which is not committed and absent in fresh checkouts. Status:
**PRE-EXISTING/BLOCKED** — untouched, documented, not a regression from this
branch (test file byte-identical to source).

## Production files changed

- `reports/hq/WORKER2_CHARACTERS_MANIFEST.json` (QA-1, data fix)
- `ui/aivido.js` (QA-2 guards, QA-4 REFS dedup)
- `ui/aivido.html` (cache-bust pin for the changed JS)
- `ui/build-manifest.json` (QA-3 truthful hash entries)

Test file changed: `tests/test_ui_hermetic_contract.py` (guard-check heuristic
tightened to the project's one-line try/catch pattern).