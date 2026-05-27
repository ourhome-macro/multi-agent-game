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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
SNAPSHOT_PATH = (
    PROJECT_ROOT / "tests" / "snapshots" / "fake_case_001_full_runtime_events.json"
)


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
    assert _summary_does_not_leak(summary.model_dump_json())

    snapshot = _normalize_events(session.events)
    assert SNAPSHOT_PATH.exists()
    expected_snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert snapshot == expected_snapshot


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
