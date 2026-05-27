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
SNAPSHOT_PATH = (
    PROJECT_ROOT / "tests" / "snapshots" / "fake_case_001_full_runtime_events.json"
)
JOURNEY_PATH = PROJECT_ROOT / "tests" / "snapshots" / "fake_case_001_player_journey.md"


def test_fake_case_001_full_runtime_scenario_smoke() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

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
        EventType.RELATIONSHIP_CHANGED,
        EventType.RELATIONSHIP_THRESHOLD_CROSSED,
        EventType.PLAYER_KNOWLEDGE_UPDATED,
        EventType.MEMORY_CANDIDATE_CREATED,
        EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
        EventType.DIRECTOR_BLOCKED,
        EventType.RULE_REJECTED,
    ):
        assert expected_type in event_types

    summary = build_state_summary(case, session)
    replayed = replay_events(case, session.events)
    replayed_summary = build_state_summary(case, replayed)

    assert _summary_key_fields(replayed_summary.model_dump(mode="json")) == _summary_key_fields(
        summary.model_dump(mode="json")
    )
    assert sorted(replayed.memory_candidates) == sorted(session.memory_candidates)
    assert sorted(replayed.memory_snapshots) == sorted(session.memory_snapshots)
    assert replayed.narrative.phase == session.narrative.phase
    assert replayed.narrative.completed_beats == session.narrative.completed_beats
    assert replayed.discovered_clues == session.discovered_clues
    assert replayed.player_knowledge == session.player_knowledge
    assert replayed.relationships == session.relationships
    assert len(replayed.events) == len(session.events)
    assert _summary_does_not_leak(summary.model_dump_json())

    snapshot = _normalize_events(session.events)
    assert SNAPSHOT_PATH.exists()
    expected_snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert snapshot == expected_snapshot

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
    for fact in case.forbidden_facts:
        assert fact.id not in journey
        assert fact.text not in journey
        for blocked_term in fact.blocked_terms:
            assert blocked_term not in journey
    assert JOURNEY_PATH.exists()
    assert journey == JOURNEY_PATH.read_text(encoding="utf-8")


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
        '"truth_status":',
        '"forbidden_facts":',
        '"solution_claims":',
    )
    return all(term not in serialized_summary for term in forbidden_terms)


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
        if key == "source_event_id" and isinstance(value, str):
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
