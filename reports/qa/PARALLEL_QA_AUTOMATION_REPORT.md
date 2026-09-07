# AIVIDO — Parallel QA Automation Lane

**Branch:** `aivido/parallel-qa-automation`
**Source:** `origin/aivido/polish-90` @ `9fb11ef416a308e267d76ba671cd676692573c7d`
**Mode:** OFFLINE / HERMETIC — no live Unreal Editor access, no live backend,
no bridge ports (6766/8765/8844), no production writes. All tests run under
the existing pytest hermetic guards (`tests/conftest.py` blocks live bridge
I/O and live model calls for unmarked tests).

**Isolation:** dedicated worktree
`C:/Users/Shadow/Desktop/Unreal-Agent-parallel-qa`; the source branch,
certification, and the overnight-release worktrees were not touched.

---

## 1. Tests added

Four new hermetic suites (86 tests) targeting the certified polish-90 product:

| Suite | File | Covers |
|---|---|---|
| Idle-driver regression | `tests/test_idle_driver_hermetic.py` | duplicate-start prevention; stop restores exact base transforms; bounded motion (no cumulative drift); invalid-actor handling; reload-safe restart; `include_editor` mode — all against a fake `unreal` module, zero editor access |
| UI contract | `tests/test_ui_hermetic_contract.py` | 360/390/430 responsive contract; hero CTA clipping regression; required DOM ids (REFS/SCREENS/direct `$()`); duplicate ids; localStorage guards; no duplicate mutation wiring; JS syntax (`node --check`); CSS brace balance; manifest cache-bust pin + file hashes |
| Planner evidence | `tests/test_planner_evidence_hermetic.py` | actor-less prompts containing `capture` / `screenshot` / `screen shot` / `proof` / `visual evidence` MUST emit an EVIDENCE step using `capture_unreal_viewport`; case-insensitive; step ordering; control prompt gets no spurious evidence; plan well-formedness; no production planner edits |
| Release integrity | `tests/test_release_integrity_hermetic.py` | all `reports/hq/*.json` parse; polish-90 scorecard contract (baseline 80, truthful score, branch, PASS/WARN/FAIL categories); every evidence path exists and PNGs are real PNGs; no DEMO status promoted as LIVE; no credentials/secrets in release reports |

Production source files modified: **0** (tests only, per mission rules).

## 2. Suite results

**Targeted run (new suites):** 82 passed, 4 failed.

**Largest safe suite (full `tests/` collection, hermetic):**
**1016 passed, 5 failed, 1 skipped** (1022 collected, 121 s).
The 1 skipped test is a pre-existing explicit skip. No live-Unreal-marked test
executed (the only `live_unreal` references are the conftest blocker and the
test that verifies the blocker refuses live access).

## 3. Defects discovered (by this lane, tests only)

1. **MAJOR — `reports/hq/WORKER2_CHARACTERS_MANIFEST.json` is invalid JSON.**
   Line 164: `"master_materials": quarter2,` — bare identifier instead of a
   quoted string. The certified worker manifest does not parse. Verified
   against utf-8-sig / utf-16 / latin-1: no decoding rescues it.
2. **MINOR — unguarded `localStorage` access in `ui/aivido.js` (4 sites).**
   Initial state read (line ~57) and `persist()` (line ~115) at IIFE top
   level, plus `questTick`/`ledgerAdd` `setItem` writes (lines ~1087/~1093)
   are not inside try/catch. In a storage-blocked context (sandboxed/iframe
   with storage disabled) the boot-time read throws and breaks the whole UI.
   The `questStore`/`ledgerStore` read helpers ARE guarded — the gap is the
   top-level read, persist, and the two writers.
3. **MINOR — stale `ui/build-manifest.json` hash for `aivido.html`.**
   Manifest records `ce771b9e…`; the committed file hashes to `c1f4d5a7…`
   (LF-normalized, verified against the committed blob — not a line-ending
   artifact). Runtime cache-bust pins remain consistent (HTML css pin
   `cb503c40` == manifest `aivido.css` prefix), so this is metadata drift
   only, but the manifest is not an accurate record of the shipped tree.
4. **INFO — `homeEnterRoom` listed twice in the `REFS` array**
   (`ui/aivido.js`). Assignment is idempotent and the click listener is
   registered once, so no double wiring occurs; flagged as a lint-level
   cleanliness issue.

## 4. Pre-existing failure (not caused by this lane)

- `tests/test_api_action_vehicle_integration.py::test_vehicle_profile_keeps_bounded_strategy_and_corrected_locator`
  — the test drives `api._run_production_visual_director` with baseline path
  `assetlib/proof/vehicle_showcase_controlled_20260905/final_fresh_vehicle.png`,
  a generated artifact that is not committed, so it is absent in a fresh
  checkout; the run stalls to `BLOCKED` instead of `COMPLETE`. The test file
  is byte-identical to the source commit (verified `git diff` empty) — the
  failure is inherent to the source branch, environment/artifact-dependent.

## 5. What PASSED cleanly (highlights)

- **Idle driver (16/16):** second start idempotent (1 callback registered);
  stop restores 8/8 exactly; motion bounded ≤ 4.2 cm bob / ≤ 2.6 cm sway /
  ≤ 2.6° yaw over 30–60 s of ticks; 5 start/stop cycles → zero drift; broken
  label / broken write actors skipped without blocking others; tick errors
  swallowed and logged; restart after stop works; editor-mode drives 4/4
  game+editor characters.
- **Planner evidence (12/12):** all actor-less proof prompts produce an
  EVIDENCE/capture step; control prompt produces none; steps serializable.
- **UI contract:** CTA fix media query (≤440px, column + nowrap) present and
  the only block that restyles `.hero-cta`; intrinsic button budget fits
  360/390/430; all REFS/SCREENS ids exist; single boot dispatch; JS parses.
- **Release integrity:** 13/14 report JSONs parse (see defect #1); scorecard
  contract holds; 16/16 evidence paths exist; PNGs valid; **no secrets
  found**; no DEMO-as-LIVE.

## 6. Production impact

Production files modified by this lane: **none**. The planner evidence branch,
bridge, backend, session runtime, and certified reports were read-only inputs
to the tests. All discovered defects are reported here for the release
hardening lane to action; none were "fixed" silently.

## 7. How to run

```bash
# from the worktree (or repo root) with the project venv
python -m pytest tests/test_idle_driver_hermetic.py \
               tests/test_ui_hermetic_contract.py \
               tests/test_planner_evidence_hermetic.py \
               tests/test_release_integrity_hermetic.py -q
# largest safe suite
python -m pytest tests/ -q
```