from __future__ import annotations

import json
from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import (
    AgentIntent,
    AgentIntentType,
    EventType,
    NarrativePhaseChangeAction,
    PlayerAction,
    ProposedActionType,
    WorldEvent,
)
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime
from app.storage.memory import build_state_summary
from tests.utils.render_player_journey import render_player_journey

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
CASE_002_DIR = PROJECT_ROOT / "cases" / "fake_case_002"
SNAPSHOT_PATH = (
    PROJECT_ROOT / "tests" / "snapshots" / "fake_case_001_full_runtime_events.json"
)
JOURNEY_PATH = PROJECT_ROOT / "tests" / "snapshots" / "fake_case_001_player_journey.md"
SNAPSHOT_002_PATH = (
    PROJECT_ROOT / "tests" / "snapshots" / "fake_case_002_full_runtime_events.json"
)
JOURNEY_002_PATH = PROJECT_ROOT / "tests" / "snapshots" / "fake_case_002_player_journey.md"


def test_fake_case_001_full_runtime_scenario_smoke() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _run_fake_case_001_full_scenario(runtime, case, session)

    _assert_full_scenario_state(case, session, expected_final_phase="resolved")

    snapshot = _normalize_events(session.events)
    assert SNAPSHOT_PATH.exists()
    expected_snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert snapshot == expected_snapshot

    _assert_journey_matches_snapshot(case, session, JOURNEY_PATH)


def test_fake_case_002_full_runtime_scenario_smoke() -> None:
    case = CaseLoader().load(CASE_002_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _run_fake_case_002_full_scenario(runtime, case, session)

    _assert_full_scenario_state(case, session, expected_final_phase="resolved")

    snapshot = _normalize_events(session.events)
    assert SNAPSHOT_002_PATH.exists()
    expected_snapshot = json.loads(SNAPSHOT_002_PATH.read_text(encoding="utf-8"))
    assert snapshot == expected_snapshot

    _assert_journey_matches_snapshot(case, session, JOURNEY_002_PATH)


def _assert_full_scenario_state(case: object, session: object, expected_final_phase: str) -> None:
    event_types = [event.type for event in session.events]
    for expected_type in (
        EventType.SESSION_CREATED,
        EventType.PLAYER_INSPECTED,
        EventType.PLAYER_ASKED_ABOUT,
        EventType.PLAYER_PRESENTED_CLUE,
        EventType.PLAYER_ACCUSED,
        EventType.ACCUSATION_EVALUATED,
        EventType.CLUE_DISCOVERED,
        EventType.NARRATIVE_BEAT_COMPLETED,
        EventType.NARRATIVE_PHASE_CHANGED,
        EventType.PLAYER_TALKED,
        EventType.NPC_REPLIED,
        EventType.PLAYER_KNOWLEDGE_UPDATED,
        EventType.CHARACTER_FACT_AWARENESS_UPDATED,
        EventType.MEMORY_CANDIDATE_CREATED,
        EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
        EventType.CHARACTER_IMPRESSION_UPDATED,
        EventType.DIRECTOR_BLOCKED,
        EventType.RULE_REJECTED,
    ):
        assert expected_type in event_types
    if getattr(case, "npc_skills", []):
        assert EventType.RELATIONSHIP_CHANGED in event_types
        assert EventType.NPC_SKILL_SELECTED in event_types
        assert EventType.NPC_SKILL_REJECTED in event_types

    summary = build_state_summary(case, session)
    replayed = replay_events(case, session.events)
    replayed_summary = build_state_summary(case, replayed)

    assert _summary_key_fields(replayed_summary.model_dump(mode="json")) == _summary_key_fields(
        summary.model_dump(mode="json")
    )
    assert sorted(replayed.memory_candidates) == sorted(session.memory_candidates)
    assert sorted(replayed.memory_snapshots) == sorted(session.memory_snapshots)
    assert replayed.narrative.phase == session.narrative.phase
    assert replayed.narrative.phase == expected_final_phase
    assert replayed.narrative.completed_beats == session.narrative.completed_beats
    assert "case_solved" in session.narrative.completed_beats
    assert replayed.discovered_clues == session.discovered_clues
    assert replayed.player_knowledge == session.player_knowledge
    assert replayed.character_fact_awareness == session.character_fact_awareness
    assert replayed.relationships == session.relationships
    assert replayed.character_impressions == session.character_impressions
    assert len(replayed.events) == len(session.events)
    assert _summary_does_not_leak(summary.model_dump_json())


def _assert_journey_matches_snapshot(case: object, session: object, journey_path: Path) -> None:
    journey = render_player_journey(session.events)
    assert _summary_does_not_leak(journey)
    for required_text in (
        "`player.inspected`",
        "`player.talked`",
        "`player.asked_about`",
        "`player.presented_clue`",
        "`player.accused`",
        "`accusation.evaluated`",
        "`case_solved`",
        "`resolved`",
    ):
        assert required_text in journey
    if any(event.type == EventType.NPC_SKILL_SELECTED for event in session.events):
        assert "`npc_skill.selected`" in journey
    if any(event.type == EventType.NPC_SKILL_REJECTED for event in session.events):
        assert "`npc_skill.rejected`" in journey
    for fact in case.forbidden_facts:
        assert fact.id not in journey
        assert fact.text not in journey
        for blocked_term in fact.blocked_terms:
            assert blocked_term not in journey
    for private_value in _private_character_values(case):
        assert private_value not in journey
    for impressions_by_target in session.character_impressions.values():
        for impression in impressions_by_target.values():
            assert impression.personality_impression not in journey
            assert impression.perceived_motive not in journey
            assert impression.trust_boundary not in journey
    assert journey_path.exists()
    assert journey == journey_path.read_text(encoding="utf-8")


def _run_fake_case_001_full_scenario(runtime: object, case: object, session: object) -> None:
    for action in (
        PlayerAction(type="inspect", target_id="desk"),
        PlayerAction(
            type="ask_about",
            target_id="butler",
            subject_type="clue",
            subject_id="scratched_drawer",
            text="What about the drawer?",
        ),
        PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
        PlayerAction(type="talk", target_id="butler", text="Where were you last night?"),
        PlayerAction(type="inspect", target_id="portrait"),
        PlayerAction(type="talk", target_id="butler", text="What did you see?"),
        PlayerAction(
            type="talk",
            target_id="butler",
            text="Tell me the truth.",
            force_forbidden=True,
        ),
        PlayerAction(type="inspect", target_id="carpet"),
        PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
            text="You moved the key and staged the study entry.",
        ),
    ):
        runtime.action_service.handle(session=session, action=action)
    _apply_illegal_phase_change(runtime, case, session)


def _run_fake_case_002_full_scenario(runtime: object, case: object, session: object) -> None:
    for action in (
        PlayerAction(type="inspect", target_id="tide_mark"),
        PlayerAction(
            type="ask_about",
            target_id="dockmaster",
            subject_type="clue",
            subject_id="inward_tide_mark",
            text="What about the tide mark?",
        ),
        PlayerAction(type="talk", target_id="dockmaster", text="Was the door opened?"),
        PlayerAction(
            type="talk",
            target_id="clerk",
            text="Who hid the ledger?",
            force_forbidden=True,
        ),
        PlayerAction(type="inspect", target_id="broken_lamp"),
        PlayerAction(type="inspect", target_id="ledger_box"),
        PlayerAction(
            type="present_clue",
            target_id="clerk",
            clue_id="blue_ledger_page",
            text="Explain this ledger page.",
        ),
        PlayerAction(type="talk", target_id="dockmaster", text="The lamp was broken inside."),
        PlayerAction(
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
    ):
        runtime.action_service.handle(session=session, action=action)
    _apply_illegal_phase_change(runtime, case, session)


def _apply_illegal_phase_change(runtime: object, case: object, session: object) -> None:
    illegal_intent = AgentIntent(
        speech="I want to advance the phase directly.",
        intent=AgentIntentType.ANSWER,
        proposed_actions=[
            NarrativePhaseChangeAction(
                type=ProposedActionType.NARRATIVE_PHASE_CHANGE,
                phase="opening",
            )
        ],
    )
    runtime.rule_engine.apply_agent_intent(
        case=case,
        session=session,
        intent=illegal_intent,
        caused_by_event_id=session.events[-1].id,
    )


def _summary_key_fields(summary: dict) -> dict:
    return {
        "case_id": summary["case_id"],
        "narrative_phase": summary["narrative_phase"],
        "completed_beats": summary["completed_beats"],
        "discovered_clues": [clue["id"] for clue in summary["discovered_clues"]],
        "player_knowledge": [item["knowledge_id"] for item in summary["player_knowledge"]],
        "relationships": sorted(
            summary["relationships"],
            key=lambda item: (item["source_id"], item["target_id"]),
        ),
        "event_count": summary["event_count"],
    }


def _summary_does_not_leak(serialized_summary: str) -> bool:
    forbidden_terms = (
        '"secrets":',
        '"goals":',
        '"knowledge":',
        '"private":',
        '"character_impressions":',
        '"character_fact_awareness":',
        '"inner_portraits":',
        '"truth_status":',
        '"forbidden_facts":',
        '"solution_claims":',
    )
    return all(term not in serialized_summary for term in forbidden_terms)


def _private_character_values(case: object) -> list[str]:
    values: list[str] = []
    for character in case.characters:
        values.extend(goal.summary for goal in character.private.goals)
        values.extend(secret.summary for secret in character.private.secrets)
        values.extend(knowledge.summary for knowledge in character.private.knowledge)
    return values


def _normalize_events(events: list[WorldEvent]) -> list[dict]:
    id_map = {event.id: f"event_{index:03d}" for index, event in enumerate(events, start=1)}
    return [
        {
            "id": id_map[event.id],
            "case_id": event.case_id,
            "session_id": "session",
            "actor_id": event.actor_id,
            "type": event.type,
            "payload": _normalize_payload(event.payload, id_map),
            "caused_by_event_id": (
                id_map[event.caused_by_event_id]
                if event.caused_by_event_id is not None
                else None
            ),
            "created_at": "timestamp",
        }
        for event in events
    ]


def _normalize_payload(payload: dict, id_map: dict[str, str]) -> dict:
    normalized: dict[str, object] = {}
    for key, value in payload.items():
        if key in {"source_event_id", "last_updated_event_id"} and isinstance(value, str):
            normalized[key] = id_map.get(value, value)
        elif key == "source_event_ids" and isinstance(value, list):
            normalized[key] = [id_map.get(str(item), str(item)) for item in value]
        elif key == "memory_id" and isinstance(value, str):
            normalized[key] = value.removesuffix(value.split(".")[-1]) + id_map.get(
                value.split(".")[-1],
                value.split(".")[-1],
            )
        elif isinstance(value, dict):
            normalized[key] = _normalize_payload(value, id_map)
        elif isinstance(value, list):
            normalized[key] = [
                _normalize_payload(item, id_map) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            normalized[key] = value
    return normalized
