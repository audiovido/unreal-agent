"""Mission-label audit: a brief that names absent actors must fail at gate time.

Run 9 burned both executor attempts on ``AIVIDO_CommandDais`` — a label from a
stale log that no longer existed (the real scene has ``AIVIDO_Dais_Tier1`` and
``AIVIDO_Dais_Tier2``). The graduation gate now audits every ``AIVIDO_*``
reference in the mission text against the live label list before any
automation runs, converting a mid-execution stall into a fast, honest
pre-flight failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.aivido_graduation_gate import audit_mission_labels  # noqa: E402

LIVE = [
    "AIVIDO_Floor",
    "AIVIDO_Dais_Tier1",
    "AIVIDO_Dais_Tier2",
    "AIVIDO_Console_Left_Desk",
    "AIVIDO_WorkerDesk_AV",
    "AIVIDO_WorkerDesk_ASSET",
    "AIVIDO_WorkerChairSeat_AV",
    "AIVIDO_KeyWarm",
    "AIVIDO_Practical_AV",
    "AIVIDO_Practical_UA",
]


def test_live_labels_pass():
    mission = (
        "Apply material /Game/Cinema/Materials/M_Cinema_Floor to AIVIDO_Floor. "
        "Set light_color of AIVIDO_KeyWarm to [1.0, 0.72, 0.42] and light_intensity to 3200."
    )
    assert audit_mission_labels(mission, LIVE) == []


def test_prefix_references_resolve_to_live_labels():
    mission = (
        "Apply material /Game/Cinema/Materials/M_Cinema_Seat to the four AIVIDO_WorkerChairSeat actors. "
        "Apply material /Game/Cinema/Materials/M_Cinema_Surface to AIVIDO_Dais_Tier1, AIVIDO_Dais_Tier2. "
        "Set the AIVIDO_Practical lights to [1.0, 0.78, 0.5] intensity 650."
    )
    assert audit_mission_labels(mission, LIVE) == []


def test_map_path_is_not_an_actor_label():
    mission = (
        "Operate ONLY on /Game/AIVIDO_Showcase. "
        "Apply material to AIVIDO_Floor."
    )
    assert audit_mission_labels(mission, LIVE) == []


def test_stale_labels_fail_fast():
    mission = (
        "Apply material to AIVIDO_CommandDais, AIVIDO_Console_A, AIVIDO_Console_B. "
        "Set light_color of AIVIDO_VisualCore to [1, 1, 1] and light_intensity to 100."
    )
    missing = audit_mission_labels(mission, LIVE)
    assert "AIVIDO_CommandDais" in missing
    assert "AIVIDO_Console_A" in missing
    assert "AIVIDO_Console_B" in missing
    assert "AIVIDO_VisualCore" in missing
    # Live labels referenced in the same text are not reported.
    assert all("AIVIDO_Floor" != m for m in missing)


def test_empty_live_labels_disables_audit():
    assert audit_mission_labels("AIVIDO_Anything", []) == []


def test_boundary_prefix_is_not_enough():
    # AIVIDO_Worker does not exist and is NOT a prefix boundary match of
    # AIVIDO_WorkerDesk_AV (prefix must extend to the next underscore).
    assert "AIVIDO_Worker" in audit_mission_labels("move AIVIDO_Worker", LIVE)
