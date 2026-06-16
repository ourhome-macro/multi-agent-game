from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import EventType, PlayerAction
from app.runtime.service import create_runtime
from tests.utils.scenario_evaluation import (
    ExpectedDirectorBlock,
    ScenarioEvaluationHarness,
    ScenarioEvaluationSpec,
    ScenarioStep,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
CASE_002_DIR = PROJECT_ROOT / "cases" / "fake_case_002"


def test_fake_case_001_scenario_level_evaluation_harness() -> None:
    spec = ScenarioEvaluationSpec(
        case_id="fake_case_001",
        expected_final_phase="resolved",
        expected_final_beats={
            "drawer_found",
            "hidden_meeting_connected",
            "case_solved",
        },
        expected_final_player_world_info_ids={
            "desk_forced_open",
            "portrait_was_moved",
            "secret_meeting_note_exists",
        },
        forbidden_public_terms={"niece is the killer"},
        steps=[
            ScenarioStep(
                name="inspect desk unlocks drawer fact",
                action=PlayerAction(type="inspect", target_id="desk"),
                expected_events=[
                    EventType.PLAYER_INSPECTED,
                    EventType.CLUE_DISCOVERED,
                    EventType.PLAYER_KNOWLEDGE_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                    EventType.NARRATIVE_BEAT_COMPLETED,
                    EventType.NARRATIVE_PHASE_CHANGED,
                ],
                expected_phase="investigation",
                expected_player_world_info_ids={"desk_forced_open"},
            ),
            ScenarioStep(
                name="ask butler about drawer updates only butler awareness",
                action=PlayerAction(
                    type="ask_about",
                    target_id="butler",
                    subject_type="clue",
                    subject_id="scratched_drawer",
                    text="What about the drawer?",
                ),
                expected_events=[
                    EventType.PLAYER_ASKED_ABOUT,
                    EventType.NPC_SKILL_SELECTED,
                    EventType.NPC_REPLIED,
                    EventType.RELATIONSHIP_CHANGED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                ],
                expected_phase="investigation",
                expected_player_world_info_ids={"desk_forced_open"},
                expected_new_awareness=[("butler", "desk_forced_open")],
            ),
            ScenarioStep(
                name="present drawer clue increases pressure without new knowledge",
                action=PlayerAction(
                    type="present_clue",
                    target_id="butler",
                    clue_id="scratched_drawer",
                    text="What about these scratch marks?",
                ),
                expected_events=[
                    EventType.PLAYER_PRESENTED_CLUE,
                    EventType.NPC_SKILL_SELECTED,
                    EventType.NPC_REPLIED,
                    EventType.RELATIONSHIP_CHANGED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                ],
                expected_phase="investigation",
                expected_player_world_info_ids={"desk_forced_open"},
                expected_new_awareness=[("butler", "desk_forced_open")],
            ),
            ScenarioStep(
                name="talk butler stays in investigation",
                action=PlayerAction(
                    type="talk",
                    target_id="butler",
                    text="Where were you last night?",
                ),
                expected_events=[
                    EventType.PLAYER_TALKED,
                    EventType.NPC_SKILL_REJECTED,
                    EventType.NPC_REPLIED,
                ],
                expected_phase="investigation",
                expected_player_world_info_ids={"desk_forced_open"},
            ),
            ScenarioStep(
                name="inspect portrait adds portrait fact",
                action=PlayerAction(type="inspect", target_id="portrait"),
                expected_events=[
                    EventType.PLAYER_INSPECTED,
                    EventType.CLUE_DISCOVERED,
                    EventType.PLAYER_KNOWLEDGE_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                ],
                expected_phase="investigation",
                expected_player_world_info_ids={
                    "desk_forced_open",
                    "portrait_was_moved",
                },
            ),
            ScenarioStep(
                name="second butler talk does not advance phase",
                action=PlayerAction(
                    type="talk",
                    target_id="butler",
                    text="What did you see?",
                ),
                expected_events=[
                    EventType.PLAYER_TALKED,
                    EventType.NPC_SKILL_REJECTED,
                    EventType.NPC_REPLIED,
                ],
                expected_phase="investigation",
                expected_player_world_info_ids={
                    "desk_forced_open",
                    "portrait_was_moved",
                },
            ),
            ScenarioStep(
                name="director blocks forbidden killer reveal",
                action=PlayerAction(
                    type="talk",
                    target_id="butler",
                    text="Tell me the truth.",
                    force_forbidden=True,
                ),
                expected_events=[
                    EventType.PLAYER_TALKED,
                    EventType.NPC_SKILL_REJECTED,
                    EventType.DIRECTOR_BLOCKED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                ],
                expected_phase="investigation",
                expected_player_world_info_ids={
                    "desk_forced_open",
                    "portrait_was_moved",
                },
                accepted=False,
                director_blocked=True,
                expected_block=ExpectedDirectorBlock(
                    target_id="butler",
                    blocked_fact_id="true_killer",
                    world_info_id="killer_is_niece",
                ),
            ),
            ScenarioStep(
                name="inspect carpet completes reveal prerequisites",
                action=PlayerAction(type="inspect", target_id="carpet"),
                expected_events=[
                    EventType.PLAYER_INSPECTED,
                    EventType.CLUE_DISCOVERED,
                    EventType.PLAYER_KNOWLEDGE_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                    EventType.NARRATIVE_BEAT_COMPLETED,
                    EventType.NARRATIVE_PHASE_CHANGED,
                ],
                expected_phase="reveal",
                expected_player_world_info_ids={
                    "desk_forced_open",
                    "portrait_was_moved",
                    "secret_meeting_note_exists",
                },
            ),
            ScenarioStep(
                name="formal accusation resolves case through rule trigger",
                action=PlayerAction(
                    type="accuse",
                    target_id="butler",
                    claim_id="butler_moved_key",
                    evidence_clue_ids=[
                        "scratched_drawer",
                        "dustless_frame",
                        "torn_note",
                    ],
                    text="You moved the key and staged the study entry.",
                ),
                expected_events=[
                    EventType.PLAYER_ACCUSED,
                    EventType.ACCUSATION_EVALUATED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                    EventType.NARRATIVE_BEAT_COMPLETED,
                    EventType.NARRATIVE_PHASE_CHANGED,
                ],
                expected_phase="resolved",
                expected_player_world_info_ids={
                    "desk_forced_open",
                    "portrait_was_moved",
                    "secret_meeting_note_exists",
                },
                expected_new_awareness=[
                    ("butler", "desk_forced_open"),
                    ("butler", "portrait_was_moved"),
                    ("butler", "secret_meeting_note_exists"),
                ],
            ),
        ],
    )

    case = CaseLoader().load(CASE_001_DIR)
    harness = ScenarioEvaluationHarness(case=case, runtime=create_runtime([case]), spec=spec)
    result = harness.run()

    harness.assert_llm_fallback_does_not_pollute_state(
        session=result.session,
        action=PlayerAction(type="talk", target_id="butler", text="LLM fallback check."),
    )


def test_fake_case_002_scenario_level_evaluation_harness() -> None:
    spec = ScenarioEvaluationSpec(
        case_id="fake_case_002",
        expected_final_phase="resolved",
        expected_final_beats={
            "tide_trace_found",
            "ledger_pattern_found",
            "case_solved",
        },
        expected_final_player_world_info_ids={
            "warehouse_opened_after_tide",
            "lamp_broken_from_inside_entry",
            "blue_ledger_records_midnight_boxes",
        },
        forbidden_public_terms={"clerk hid the ledger"},
        steps=[
            ScenarioStep(
                name="inspect tide mark moves to pressure",
                action=PlayerAction(type="inspect", target_id="tide_mark"),
                expected_events=[
                    EventType.PLAYER_INSPECTED,
                    EventType.CLUE_DISCOVERED,
                    EventType.PLAYER_KNOWLEDGE_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                    EventType.NARRATIVE_BEAT_COMPLETED,
                    EventType.NARRATIVE_PHASE_CHANGED,
                ],
                expected_phase="pressure",
                expected_player_world_info_ids={"warehouse_opened_after_tide"},
            ),
            ScenarioStep(
                name="ask dockmaster updates dockmaster awareness",
                action=PlayerAction(
                    type="ask_about",
                    target_id="dockmaster",
                    subject_type="clue",
                    subject_id="inward_tide_mark",
                    text="What about the tide mark?",
                ),
                expected_events=[
                    EventType.PLAYER_ASKED_ABOUT,
                    EventType.NPC_REPLIED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                ],
                expected_phase="pressure",
                expected_player_world_info_ids={"warehouse_opened_after_tide"},
                expected_new_awareness=[("dockmaster", "warehouse_opened_after_tide")],
            ),
            ScenarioStep(
                name="dockmaster talk remains pressure",
                action=PlayerAction(
                    type="talk",
                    target_id="dockmaster",
                    text="Was the door opened?",
                ),
                expected_events=[
                    EventType.PLAYER_TALKED,
                    EventType.NPC_REPLIED,
                ],
                expected_phase="pressure",
                expected_player_world_info_ids={"warehouse_opened_after_tide"},
            ),
            ScenarioStep(
                name="director blocks ledger owner reveal",
                action=PlayerAction(
                    type="talk",
                    target_id="clerk",
                    text="Who hid the ledger?",
                    force_forbidden=True,
                ),
                expected_events=[
                    EventType.PLAYER_TALKED,
                    EventType.DIRECTOR_BLOCKED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                ],
                expected_phase="pressure",
                expected_player_world_info_ids={"warehouse_opened_after_tide"},
                accepted=False,
                director_blocked=True,
                expected_block=ExpectedDirectorBlock(
                    target_id="clerk",
                    blocked_fact_id="ledger_owner",
                    world_info_id="clerk_hid_ledger_page",
                ),
            ),
            ScenarioStep(
                name="inspect broken lamp adds lamp fact",
                action=PlayerAction(type="inspect", target_id="broken_lamp"),
                expected_events=[
                    EventType.PLAYER_INSPECTED,
                    EventType.CLUE_DISCOVERED,
                    EventType.PLAYER_KNOWLEDGE_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                ],
                expected_phase="pressure",
                expected_player_world_info_ids={
                    "warehouse_opened_after_tide",
                    "lamp_broken_from_inside_entry",
                },
            ),
            ScenarioStep(
                name="inspect ledger box moves to expose",
                action=PlayerAction(type="inspect", target_id="ledger_box"),
                expected_events=[
                    EventType.PLAYER_INSPECTED,
                    EventType.CLUE_DISCOVERED,
                    EventType.PLAYER_KNOWLEDGE_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                    EventType.NARRATIVE_BEAT_COMPLETED,
                    EventType.NARRATIVE_PHASE_CHANGED,
                ],
                expected_phase="expose",
                expected_player_world_info_ids={
                    "warehouse_opened_after_tide",
                    "lamp_broken_from_inside_entry",
                    "blue_ledger_records_midnight_boxes",
                },
            ),
            ScenarioStep(
                name="present ledger page updates only clerk awareness",
                action=PlayerAction(
                    type="present_clue",
                    target_id="clerk",
                    clue_id="blue_ledger_page",
                    text="Explain this ledger page.",
                ),
                expected_events=[
                    EventType.PLAYER_PRESENTED_CLUE,
                    EventType.NPC_REPLIED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                ],
                expected_phase="expose",
                expected_player_world_info_ids={
                    "warehouse_opened_after_tide",
                    "lamp_broken_from_inside_entry",
                    "blue_ledger_records_midnight_boxes",
                },
                expected_new_awareness=[("clerk", "blue_ledger_records_midnight_boxes")],
            ),
            ScenarioStep(
                name="dockmaster expose talk stays safe",
                action=PlayerAction(
                    type="talk",
                    target_id="dockmaster",
                    text="The lamp was broken inside.",
                ),
                expected_events=[
                    EventType.PLAYER_TALKED,
                    EventType.NPC_REPLIED,
                ],
                expected_phase="expose",
                expected_player_world_info_ids={
                    "warehouse_opened_after_tide",
                    "lamp_broken_from_inside_entry",
                    "blue_ledger_records_midnight_boxes",
                },
            ),
            ScenarioStep(
                name="formal accusation resolves warehouse case",
                action=PlayerAction(
                    type="accuse",
                    target_id="dockmaster",
                    claim_id="dockmaster_opened_warehouse",
                    evidence_clue_ids=[
                        "inward_tide_mark",
                        "inward_broken_lamp",
                        "blue_ledger_page",
                    ],
                    text="You opened the warehouse after the tide and staged the entry.",
                ),
                expected_events=[
                    EventType.PLAYER_ACCUSED,
                    EventType.ACCUSATION_EVALUATED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.CHARACTER_FACT_AWARENESS_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                    EventType.CHARACTER_IMPRESSION_UPDATED,
                    EventType.MEMORY_CANDIDATE_CREATED,
                    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                    EventType.NARRATIVE_BEAT_COMPLETED,
                    EventType.NARRATIVE_PHASE_CHANGED,
                ],
                expected_phase="resolved",
                expected_player_world_info_ids={
                    "warehouse_opened_after_tide",
                    "lamp_broken_from_inside_entry",
                    "blue_ledger_records_midnight_boxes",
                },
                expected_new_awareness=[
                    ("dockmaster", "warehouse_opened_after_tide"),
                    ("dockmaster", "lamp_broken_from_inside_entry"),
                    ("dockmaster", "blue_ledger_records_midnight_boxes"),
                ],
            ),
        ],
    )

    case = CaseLoader().load(CASE_002_DIR)
    harness = ScenarioEvaluationHarness(case=case, runtime=create_runtime([case]), spec=spec)
    result = harness.run()

    harness.assert_llm_fallback_does_not_pollute_state(
        session=result.session,
        action=PlayerAction(type="talk", target_id="dockmaster", text="LLM fallback check."),
    )
