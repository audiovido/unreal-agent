# AIVIDO V2 — AUTONOMOUS QA REPORT

- **Run ID:** `qar_fc286b5a22d0`
- **Target:** Aivido V2 canonical release certification
- **Status:** COMPLETED
- **Started:** 2026-09-07 15:00:17
- **Finished:** 2026-09-07 15:01:11
- **Duration:** 54.11s
- **Score:** 100.00/100

## VERDICT: **RELEASE_READY**

RELEASE_READY: no open CRITICAL/MAJOR defects, core mission PASS, false-pass defense PASS, Unreal preservation PASS, evidence integrity PASS, regression acceptable.

### Summary
Total checks **63**: PASS **63** | FAIL **0** | BLOCKED **0** | SKIPPED **0**
Defects: CRITICAL **0** | MAJOR **0** | MINOR **0** | WARNING **0**

### Group Results

| Group | Status |
|---|---|
| RUNTIME_HEALTH | PASS |
| API_CONTRACT | PASS |
| MISSION_BLACKBOX | PASS |
| FALSE_PASS_DEFENSE | PASS |
| EVIDENCE_INTEGRITY | PASS |
| UNREAL_STATE_SAFETY | PASS |
| CINEMATIC_ARTIFACT | PASS |
| UI_BLACKBOX | PASS |
| RECOVERY | PASS |
| RELEASE_SAFETY | PASS |

### Release Gates

- **core black-box mission**: PASS
- **false-pass defense**: PASS
- **Unreal preservation**: PASS
- **evidence integrity**: PASS

### Open Defects (ledger)

_No open defects recorded._

### Checks

- `[PASS]` **backend_status** (RUNTIME_HEALTH) — status envelope healthy
  - verifier: `health_ok`
- `[PASS]` **backend_latency** (RUNTIME_HEALTH) — claim 'latency claim' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **doctor_report** (RUNTIME_HEALTH) — claim 'doctor report' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **bridge_identity** (RUNTIME_HEALTH) — expected 'ASSET_Showcase2' == observed 'ASSET_Showcase2'
  - verifier: `registry_match`
- `[PASS]` **bridge_engine_version** (RUNTIME_HEALTH) — claim 'UE 5.8' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **ports_listening** (RUNTIME_HEALTH) — claim 'ports claim' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **single_listener_per_port** (RUNTIME_HEALTH) — all observed listeners single-PID
  - verifier: `truthful_claim`
- `[PASS]` **status_endpoint** (API_CONTRACT) — HTTP 200
  - verifier: `http_ok`
- `[PASS]` **start_mission_endpoint** (API_CONTRACT) — claim 'accepted' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **mission_status_endpoint** (API_CONTRACT) — claim 'checkpoint payload' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **route_prompt** (API_CONTRACT) — claim 'routing decision' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **malformed_input_rejected** (API_CONTRACT) — claim '4xx' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **unknown_mission_id_404** (API_CONTRACT) — claim '404' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **timeout_behavior** (API_CONTRACT) — claim 'honest envelope' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **readonly_diagnostic_mission** (MISSION_BLACKBOX) — mission complete, verdict PASS, 3 steps, 1 real evidence file(s); evidence: 1 path(s)
  - verifier: `mission_verdict`
  - evidence: C:\Users\Shadow\Desktop\Unreal-Agent\.worktrees\v2-autonomous-qa\memory\diagnostics\backend_doctor_1788818420.json
- `[PASS]` **isolated_capture_mission** (MISSION_BLACKBOX) — mission complete, verdict PASS, 4 steps, 2 real evidence file(s); evidence: 2 path(s)
  - verifier: `mission_verdict`
  - evidence: C:/Users/Shadow/Desktop/Unreal-Agent/assetlib/tests/ue/ASSET_Showcase2/Saved/UnrealAgent/viewport_latest.png, C:\Users\Shadow\Desktop\Unreal-Agent\.worktrees\v2-autonomous-qa\memory\diagnostics\backend_doctor_1788818425.json
- `[PASS]` **plain_capture_phrasing_routing** (MISSION_BLACKBOX) — claim 'plans an EVIDENCE/capture step' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **code_task_pipeline** (MISSION_BLACKBOX) — code task PASS: commit 2682a22f8930 evidence_files=2
  - verifier: `truthful_claim`
  - evidence: C:\Users\Shadow\Desktop\Unreal-Agent\.worktrees\v2-autonomous-qa\memory\code_tasks\evidence\ct0001\evidence.json, C:\Users\Shadow\Desktop\Unreal-Agent\.worktrees\v2-autonomous-qa\memory\code_tasks\evidence\ct0001\change.patch
- `[PASS]` **mixed_routing_mission** (MISSION_BLACKBOX) — claim 'code stage + unreal stage PASS' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **completed_without_evidence** (FALSE_PASS_DEFENSE) — bad case rejected (mission_verdict -> mission PASS unverified: no real evidence files (0 entries))
  - verifier: `expect_failure`
- `[PASS]` **missing_screenshot** (FALSE_PASS_DEFENSE) — bad case rejected (screenshot_valid -> screenshot missing: C:\Users\Shadow\Desktop\Unreal-Agent\.worktrees\v2-autonomous-qa\memory\qa\no_such_screenshot.png)
  - verifier: `expect_failure`
- `[PASS]` **invalid_screenshot** (FALSE_PASS_DEFENSE) — bad case rejected (screenshot_valid -> invalid image: UnidentifiedImageError: cannot identify image file 'C:\\Users\\Shadow\\Desktop\\Unreal-Agent\\.worktrees\\v2-autonomous-qa\\memory\\qa\\fake_screenshot.png')
  - verifier: `expect_failure`
- `[PASS]` **stale_duplicate_evidence** (FALSE_PASS_DEFENSE) — bad case rejected (no_stale_duplicate -> stale duplicate evidence (identical sha256): C:\Users\Shadow\Desktop\Unreal-Agent\.worktrees\v2-autonomous-qa\memory\qa\dup_a.png; C:\Users\Shadow\Desktop\Unreal-Agent\.worktrees\v2-autonomous-qa\memory\qa\dup_b.png)
  - verifier: `expect_failure`
- `[PASS]` **wrong_task_id_rejected** (FALSE_PASS_DEFENSE) — claim '404' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **blocked_task_not_pass** (FALSE_PASS_DEFENSE) — bad case rejected (mission_verdict -> mission PASS unverified: status='blocked'; verdict='BLOCKED'; 0 executed steps; no real evidence files (0 entries))
  - verifier: `expect_failure`
- `[PASS]` **timed_out_task_not_pass** (FALSE_PASS_DEFENSE) — bad case rejected (mission_verdict -> mission PASS unverified: status='executing'; verdict=None; 0 executed steps; no real evidence files (0 entries))
  - verifier: `expect_failure`
- `[PASS]` **bridge_unavailable_fails** (FALSE_PASS_DEFENSE) — bad case rejected (registry_match -> expected 'ASSET_Showcase2' != observed '')
  - verifier: `expect_failure`
- `[PASS]` **impossible_claim_rejected** (FALSE_PASS_DEFENSE) — bad case rejected (truthful_claim -> claim 'the mission created 12 blueprints' has NO independent evidence)
  - verifier: `expect_failure`
- `[PASS]` **evidence_files_exist** (EVIDENCE_INTEGRITY) — claim 'real files' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **no_object_object_in_evidence** (EVIDENCE_INTEGRITY) — claim 'no [object Object]' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **mrq_not_viewport_fallback** (EVIDENCE_INTEGRITY) — claim 'real MRQ artifact' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **evidence_timestamps_relevant** (EVIDENCE_INTEGRITY) — claim 'recent artifacts' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **proof_stills_valid** (EVIDENCE_INTEGRITY) — 1920x1080 decodable image, 2205300 bytes
  - verifier: `screenshot_valid`
- `[PASS]` **certified_level_open** (UNREAL_STATE_SAFETY) — claim 'AividoHQ level' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **actor_count** (UNREAL_STATE_SAFETY) — actor count 166
  - verifier: `actor_count_ok`
- `[PASS]` **cast_8_of_8_present** (UNREAL_STATE_SAFETY) — all 8 members present
  - verifier: `list_members_present`
- `[PASS]` **no_whiteh** (UNREAL_STATE_SAFETY) — no forbidden members (WhiteH)
  - verifier: `list_members_absent`
- `[PASS]` **no_avcam_residue** (UNREAL_STATE_SAFETY) — no forbidden members (AVCam, UA_Test, BP_ProdProbe, RenderMap)
  - verifier: `list_members_absent`
- `[PASS]` **no_transient_z_repair** (UNREAL_STATE_SAFETY) — no forbidden members (ZRepair, tempz, zfix)
  - verifier: `list_members_absent`
- `[PASS]` **cine_mrq_isolated** (UNREAL_STATE_SAFETY) — claim 'certified level not RenderMap' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **durable_orientation** (UNREAL_STATE_SAFETY) — Master rotation.z=0.0 (durable orientation)
  - verifier: `truthful_claim`
- `[PASS]` **headless_mrq_report_exists** (CINEMATIC_ARTIFACT) — claim 'report file' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **mrq_video_exists_playable** (CINEMATIC_ARTIFACT) — 562973 bytes, MP4 container header present
  - verifier: `video_file_ok`
- `[PASS]` **mrq_video_resolution_fps_duration** (CINEMATIC_ARTIFACT) — ffprobe: 1920x1080 30/1 8.0s
  - verifier: `truthful_claim`
- `[PASS]` **frame_count_claim_consistent** (CINEMATIC_ARTIFACT) — 240-frame claim verified independently via MP4 duration(8.0s) x fps(30); raw frames dir is untracked by repo convention
  - verifier: `report_claim_consistent`
- `[PASS]` **proof_stills_exist** (CINEMATIC_ARTIFACT) — claim '3 proof stills' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **production_routes_serve** (UI_BLACKBOX) — claim 'HTTP 200 on all routes' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **no_js_fatal_in_pages** (UI_BLACKBOX) — no fatal markers in response
  - verifier: `no_js_fatal`
- `[PASS]` **api_state_renders** (UI_BLACKBOX) — claim 'API-backed state present' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **no_false_pass_labels** (UI_BLACKBOX) — no contradictory PASS label found
  - verifier: `no_false_pass_label`
- `[PASS]` **evidence_fields_readable** (UI_BLACKBOX) — claim 'no [object Object]' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **retry_unknown_mission_404** (RECOVERY) — claim '404' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **cancel_unknown_mission_404** (RECOVERY) — claim '404' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **duplicate_submission_protected** (RECOVERY) — claim 'repeated submission rejected or idempotent' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **stale_task_recovery** (RECOVERY) — claim 'no stale running tasks' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **watchdog_supervisor_present** (RECOVERY) — claim 'supervisor alive' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **secrets_not_in_committed_files** (RELEASE_SAFETY) — no secret markers found
  - verifier: `secrets_hygiene`
- `[PASS]` **no_absolute_local_paths_in_product** (RELEASE_SAFETY) — no absolute local path markers
  - verifier: `no_absolute_local_path`
- `[PASS]` **certified_files_clean** (RELEASE_SAFETY) — claim 'no dirty certified files' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **correct_branch_assumption** (RELEASE_SAFETY) — expected 'aivido/v2-autonomous-qa' == observed 'aivido/v2-autonomous-qa'
  - verifier: `registry_match`
- `[PASS]` **junk_build_artifacts** (RELEASE_SAFETY) — claim 'no junk in tracked tree' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **startup_doctor_sanity** (RELEASE_SAFETY) — claim 'doctor reachable' backed by observed data
  - verifier: `truthful_claim`
- `[PASS]` **release_prerequisites** (RELEASE_SAFETY) — claim 'install/start scripts + README' backed by observed data
  - verifier: `truthful_claim`

---
_Generated by the Aivido autonomous QA bot (run `qar_fc286b5a22d0`) at 2026-09-07 15:13:53._