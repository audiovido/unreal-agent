# AIVIDO Visual RC Acceptance Checklist — Visual Vertical Slice V1

**Scope**: Independent acceptance/review system for the Western/Frontier-Tech room visual vertical slice.
**Policy**: Deterministic checks only. Subjective visual quality is SCORED separately, never used as a gate.
**Execution**: Read-only. Never mutates Unreal or runtime state.

---

## 10 Deterministic Acceptance Gates (Binary PASS/FAIL)

| # | Check ID | Name | Deterministic Criteria |
|---|----------|------|------------------------|
| 1 | `HEIDI_HERO_FOCAL_POINT` | Heidi Hero Focal Point | Exactly 1 readable actor with label containing "heidi"; valid transform; not phantom |
| 2 | `MIN_THREE_WORKERS` | Minimum 3 Visible Workers | ≥3 readable actors with label containing "worker"; distinct internal names |
| 3 | `DISTINCT_WORKER_STATIONS_ROLES` | Distinct Worker Stations/Roles | ≥3 readable stations **OR** ≥3 workers with distinct role markers (miner/engineer/prospector/...) |
| 4 | `WORKER_ANIMATION_STATES` | Worker IDLE/WALK/WORK States | All 3 states observable via capture metadata `worker_states` or actor class/label |
| 5 | `HEIDI_WORKER_TASK_HANDOFF` | Heidi-to-Worker Task Handoff | Task/handoff/assign/interact/signal markers in actor labels/classes **OR** `task_handoff=true` in capture metadata |
| 6 | `NO_PLACEHOLDER_HEAVY` | No Placeholder-Heavy Final Presentation | ≤2 placeholder actors total; 0 critical placeholders (Heidi/worker/station); placeholder ratio < 30% |
| 7 | `SCENE_ACTOR_INTEGRITY` | Scene Actor Integrity | Map = `/Game/AIVIDO_Showcase`; 0 phantom critical actors; 0 invalid transforms (NaN/inf); 0 duplicate critical names |
| 8 | `FRESH_EVIDENCE` | Valid Fresh Screenshots/Evidence | `capture_metadata.json` exists with all 7 required keys; age ≤ 300s; sha256 matches frame; map matches scene |
| 9 | `NO_STALE_EVIDENCE` | No Stale Evidence | Current frame sha256 ∉ prior run hashes; capture metadata `stale` flag not set |
| 10 | `WESTERN_FRONTIER_READABILITY` | Western/Frontier-Tech Room Readability | ≥5 environment actors (non-Heidi/worker/station); ≥3 unique classes; no single class >50% dominance |

---

## Placeholder Detection Rules (Deterministic)

An actor is a **placeholder** if its label, class, or internal name contains any of:
```
cube, sphere, cylinder, cone, plane, default_, basic_, primitive_, starter_,
template_, placeholder, proxy_, graybox, whitebox, blockout, bs_, bp_cube,
bp_sphere, sm_cube, sm_sphere, defaultcube, defaultsphere
```

**Critical placeholders** (instant FAIL): Heidi, Worker, or Station actors flagged as placeholders.

---

## Evidence Freshness Contract

Every evidence frame **MUST** have a `capture_metadata.json` written atomically at capture time:

```json
{
  "frame": "shot_001.png",
  "path": "/absolute/path/shot_001.png",
  "sha256": "64-char-hex",
  "size_bytes": 1024000,
  "captured_at_epoch": 1726123456.789,
  "map": "/Game/AIVIDO_Showcase",
  "source": "bridge",
  "worker_states": {"Worker_Miner_01": "IDLE", "Worker_Engineer_01": "WALK", "Worker_Prospector_01": "WORK"},
  "task_handoff": true
}
```

- `captured_at_epoch` is the **source of truth** for freshness (not file mtime).
- Max age: **300 seconds** (5 minutes).
- Stale detection: SHA256 match against any prior run's evidence frames.

---

## Reproducible Demo Flow (Deterministic)

The demo flow is considered reproducible when **ALL 10 gates PASS** on a fresh capture
taken from the live scene after the demo sequence completes.

**Required sequence:**
1. Load `/Game/AIVIDO_Showcase`
2. Run demo sequence (Heidi enters → approaches workers → assigns tasks → workers transition IDLE→WALK→WORK)
3. Capture fresh screenshot + `capture_metadata.json`
4. Run `aivido_visual_rc_gate.py --json-out verdict.json`
5. Verdict = PASS → slice accepted

---

## Running the Gate

```bash
# Full gate (requires live Unreal bridge on 127.0.0.1:6766)
python tools/visual_rc/aivido_visual_rc_gate.py --json-out verdict.json

# With custom evidence directory
python tools/visual_rc/aivido_visual_rc_gate.py --evidence-dir ./evidence --json-out verdict.json

# With explicit prior hashes for stale detection
python tools/visual_rc/aivido_visual_rc_gate.py --prior-hashes prior_hashes.json --json-out verdict.json

# Single check for debugging
python tools/visual_rc/aivido_visual_rc_gate.py --check 3
```

**Exit codes**: `0` = PASS, `42` = FAIL, `2` = usage error.

---

## Hermetic Unit Tests

All 10 criteria are unit-tested offline with synthetic `SceneEvidence` — no Unreal required.

```bash
# Run visual RC tests
python -m pytest tests/visual_rc/test_visual_rc_gate.py -v

# Run specific test class
python -m pytest tests/visual_rc/test_visual_rc_gate.py::TestDeterministicCriteria -v
```

**Test coverage**: 40+ test cases covering PASS/FAIL paths for every criterion.

---

## Separation: Deterministic Gates vs. Visual Quality Scoring

| Layer | Purpose | Tool | Output |
|-------|---------|------|--------|
| **Deterministic Gates** | Binary acceptance — structural correctness | `aivido_visual_rc_gate.py` | PASS/FAIL per check + overall |
| **Visual Quality Scoring** | Graded assessment — composition, lighting, fidelity | `core.visual_acceptance` + vision review | 0-10 scores per category |

**Graduation requires BOTH:**
- All 10 deterministic gates = PASS
- Visual acceptance score ≥ 8.0 overall, all mandatory categories ≥ 7.0

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Worker state metadata not propagated to capture | Medium | High | Gate checks both actor labels AND capture metadata; demo sequence must emit states |
| Task handoff markers missing from scene | Medium | High | Add explicit `BP_TaskHandoff` actor or metadata flag in demo sequence |
| Placeholder assets slip into critical roles | Low | High | Gate checks critical actors explicitly; placeholder list is comprehensive |
| Stale evidence from prior manual run | Medium | Medium | `--prior-hashes` auto-scans `evidence/**/verdict.json`; gate fails on hash match |
| Map name mismatch (e.g. `/Game/AIVIDO_Showcase_02`) | Low | High | Gate checks substring; map rename requires gate update |
| Phantom handles on critical actors | Low | High | Gate fails on any unreadable critical actor |
| Animation state not exposed to metadata | Medium | High | Demo sequence must write `worker_states` to capture metadata |

---

## Files Created

```
tools/visual_rc/
├── __init__.py
├── scene_criteria.py           # Deterministic check implementations
└── aivido_visual_rc_gate.py    # Read-only gate runner (CLI + JSON output)

tests/visual_rc/
├── __init__.py
└── test_visual_rc_gate.py      # 40+ hermetic unit tests

docs/
└── VISUAL_RC_ACCEPTANCE.md     # This checklist
```

---

## Commit & Cherry-Pick Recommendation

**COMMIT**: All files under `tools/visual_rc/`, `tests/visual_rc/`, `docs/` — isolated clone only.

**CHERRY-PICK**: **YES** — This is a self-contained acceptance system with no runtime dependencies.
Safe to cherry-pick into any branch preparing for Visual Vertical Slice V1 review.

**TEST COUNT**: 42 unit tests (TestDeterministicCriteria: 25, TestAggregatedRunner: 3, TestConstantsAndContracts: 10, TestVisualRCGateStatic: 4)

---

## Final Verification

Before declaring the slice ready for review:

- [ ] All 10 deterministic gates PASS on fresh capture
- [ ] Visual acceptance score ≥ 8.0 overall (separate run)
- [ ] No backend regression (run `aivido_rc1_gate.py` — separate gate)
- [ ] Evidence package complete: `verdict.json` + `verdict.md` + frames + metadata
- [ ] Demo flow documented and reproducible