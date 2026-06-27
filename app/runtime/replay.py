from __future__ import annotations

from typing import Any, Literal, cast

from app.domain.models import (
    AgentMemorySnapshot,
    CasePackage,
    CharacterFactAwarenessState,
    CharacterImpression,
    EventType,
    MeetingSessionState,
    MeetingVoteChoice,
    MeetingVoteState,
    MemoryCandidateState,
    MemoryLayer,
    MemoryOperation,
    MemoryScope,
    MemoryType,
    NarrativeState,
    NpcLocationState,
    PlayerKnowledgeAcquisition,
    PlayerKnowledgeSourceType,
    PlayerKnowledgeState,
    RelationshipState,
    SessionState,
    TownClockState,
    WorldEvent,
    normalize_memory_operation,
)
from app.rules.engine import relationship_key, relationship_threshold_key
from app.runtime.character_fact_awareness import build_initial_character_fact_awareness
from app.runtime.npc_locations import initial_npc_locations


def replay_events(case: CasePackage, events: list[WorldEvent]) -> SessionState:
    if not events:
        raise ValueError("Cannot replay an empty event list")

    first_event = events[0]
    session = SessionState(
        id=first_event.session_id,
        case_id=case.meta.id,
        narrative=NarrativeState(phase=case.meta.initial_phase),
        relationships={
            relationship_key(item.source_id, item.target_id): RelationshipState(**item.model_dump())
            for item in case.relationships
        },
        npc_locations=initial_npc_locations(case),
        character_fact_awareness=build_initial_character_fact_awareness(case),
    )

    for event in events:
        _apply_event(session, event)
        session.events.append(event)
    return session


def _apply_event(session: SessionState, event: WorldEvent) -> None:
    if event.type == EventType.TOWN_TICK_ADVANCED:
        session.town_clock = _town_clock_from_event(event)
        return

    if event.type == EventType.NPC_LOCATION_CHANGED:
        location = _npc_location_from_event(event)
        session.npc_locations[location.npc_id] = location
        return

    if event.type in _MEETING_EVENT_TYPES:
        _apply_meeting_event(session, event)
        return

    if event.type in {
        EventType.NPC_OBSERVED,
        EventType.NPC_HEARSAY_RECEIVED,
        EventType.NPC_AUTONOMY_INTENT_PROPOSED,
        EventType.NPC_AUTONOMY_INTENT_REJECTED,
    }:
        return

    if event.type == EventType.CLUE_DISCOVERED:
        clue_id = str(event.payload["clue_id"])
        session.discovered_clues.add(clue_id)
        session.narrative.discovered_clues.add(clue_id)
        return

    if event.type in {
        EventType.PLAYER_ASKED_ABOUT,
        EventType.PLAYER_PRESENTED_CLUE,
        EventType.PLAYER_ACCUSED,
        EventType.ACCUSATION_EVALUATED,
    }:
        return

    if event.type == EventType.RELATIONSHIP_CHANGED:
        current = event.payload.get("current")
        if isinstance(current, dict):
            relationship = RelationshipState.model_validate(current)
            session.relationships[
                relationship_key(relationship.source_id, relationship.target_id)
            ] = relationship
        return

    if event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
        session.relationship_thresholds_crossed.add(
            relationship_threshold_key(
                str(event.payload["source_id"]),
                str(event.payload["target_id"]),
                str(event.payload["metric"]),
                str(event.payload["state"]),
            )
        )
        return

    if event.type == EventType.PLAYER_KNOWLEDGE_UPDATED:
        knowledge = PlayerKnowledgeState(
            knowledge_id=str(event.payload["knowledge_id"]),
            clue_id=(
                str(event.payload["clue_id"])
                if event.payload.get("clue_id") is not None
                else None
            ),
            world_info_id=(
                str(event.payload["world_info_id"])
                if event.payload.get("world_info_id") is not None
                else None
            ),
            confidence=float(event.payload.get("confidence", 1.0)),
            acquisition=PlayerKnowledgeAcquisition(
                str(event.payload.get("acquisition", PlayerKnowledgeAcquisition.DISCOVERED))
            ),
            source_type=PlayerKnowledgeSourceType(
                str(event.payload.get("source_type", PlayerKnowledgeSourceType.CLUE))
            ),
            title=str(event.payload["title"]),
            summary=str(event.payload["summary"]),
            source_event_id=str(event.payload["source_event_id"]),
        )
        session.player_knowledge[knowledge.knowledge_id] = knowledge
        return

    if event.type == EventType.CHARACTER_FACT_AWARENESS_UPDATED:
        awareness = CharacterFactAwarenessState.model_validate(event.payload)
        session.character_fact_awareness[awareness.awareness_id] = awareness
        return

    if event.type == EventType.MEMORY_CANDIDATE_CREATED:
        memory = MemoryCandidateState(
            memory_id=str(event.payload["memory_id"]),
            rule_id=_optional_str(event.payload.get("rule_id")),
            memory_type=cast(
                MemoryType,
                str(event.payload.get("memory_type", "episodic")),
            ),
            memory_scope=cast(
                MemoryScope,
                str(event.payload.get("memory_scope", "npc_private")),
            ),
            memory_layer=cast(
                MemoryLayer,
                str(event.payload.get("memory_layer", "working")),
            ),
            operation=normalize_memory_operation(event.payload.get("operation")),
            subject_id=str(event.payload["subject_id"]),
            owner_character_id=_optional_str(event.payload.get("owner_character_id")),
            visible_to_character_ids=[
                str(item) for item in event.payload.get("visible_to_character_ids", [])
            ],
            content=str(event.payload["content"]),
            source_event_id=str(event.payload["source_event_id"]),
            source_event_ids=_source_event_ids(
                event.payload,
                str(event.payload["source_event_id"]),
            ),
            source_memory_ids=[
                str(item) for item in event.payload.get("source_memory_ids", [])
            ],
            visibility=[str(item) for item in event.payload["visibility"]],
            salience=float(event.payload["salience"]),
            confidence=float(event.payload.get("confidence", 1.0)),
            metadata=_metadata(event.payload.get("metadata")),
        )
        session.memory_candidates[memory.memory_id] = memory
        return

    if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED:
        memory_id = str(event.payload["memory_id"])
        current = session.memory_snapshots.get(memory_id)
        candidate = session.memory_candidates.get(memory_id)
        fallback_content = candidate.content if candidate is not None else ""
        content = str(event.payload.get("content") or fallback_content)
        created_at = current.created_at if current is not None else event.created_at
        operation = normalize_memory_operation(
            event.payload.get("operation") or event.payload.get("last_operation")
        )
        if current is not None and operation not in {
            MemoryOperation.REVISE,
            MemoryOperation.SUPERSEDE,
        }:
            content = current.content
        snapshot = AgentMemorySnapshot(
            memory_id=memory_id,
            rule_id=_optional_str(event.payload.get("rule_id")),
            memory_type=cast(
                MemoryType,
                str(
                    event.payload.get(
                        "memory_type",
                        candidate.memory_type if candidate is not None else "episodic",
                    )
                ),
            ),
            memory_scope=cast(
                MemoryScope,
                str(
                    event.payload.get(
                        "memory_scope",
                        candidate.memory_scope
                        if candidate is not None
                        else "npc_private",
                    )
                ),
            ),
            memory_layer=cast(
                MemoryLayer,
                str(
                    event.payload.get(
                        "memory_layer",
                        candidate.memory_layer if candidate is not None else "working",
                    )
                ),
            ),
            last_operation=operation,
            subject_id=_optional_str(event.payload.get("subject_id")),
            owner_character_id=_optional_str(event.payload.get("owner_character_id")),
            visible_to_character_ids=[
                str(item) for item in event.payload.get("visible_to_character_ids", [])
            ],
            content=content,
            source_event_ids=[str(item) for item in event.payload["source_event_ids"]],
            source_memory_ids=[
                str(item) for item in event.payload.get("source_memory_ids", [])
            ],
            salience=float(event.payload["salience"]),
            confidence=float(event.payload.get("confidence", 1.0)),
            visibility=cast(
                Literal["private", "public"],
                str(event.payload["visibility"]),
            ),
            metadata=_metadata(event.payload.get("metadata")),
            last_updated_event_id=event.id,
            created_at=created_at,
            updated_at=event.created_at,
        )
        session.memory_snapshots[memory_id] = snapshot
        return

    if event.type == EventType.CHARACTER_IMPRESSION_UPDATED:
        impression = CharacterImpression.model_validate(event.payload)
        session.character_impressions.setdefault(impression.observer_id, {})[
            impression.target_id
        ] = impression
        return

    if event.type == EventType.NARRATIVE_BEAT_COMPLETED:
        session.narrative.completed_beats.add(str(event.payload["beat_id"]))
        return

    if event.type == EventType.NARRATIVE_PHASE_CHANGED:
        session.narrative.phase = str(event.payload["phase"])
        return


_MEETING_EVENT_TYPES = frozenset(
    {
        EventType.MEETING_SESSION_STARTED,
        EventType.MEETING_SESSION_ENDED,
        EventType.MEETING_TURN_OPENED,
        EventType.MEETING_MESSAGE_PROPOSED,
        EventType.MEETING_MESSAGE_POSTED,
        EventType.MEETING_MESSAGE_REJECTED,
        EventType.MEETING_VOTE_OPENED,
        EventType.MEETING_VOTE_CAST,
        EventType.MEETING_VERDICT_PROPOSED,
        EventType.MEETING_VERDICT_ACCEPTED,
        EventType.MEETING_VERDICT_REJECTED,
    }
)


def _apply_meeting_event(session: SessionState, event: WorldEvent) -> None:
    payload = event.payload
    if event.type == EventType.MEETING_SESSION_STARTED:
        session.meeting = MeetingSessionState(
            active=True,
            meeting_id=str(payload["meeting_id"]),
            topic=_optional_str(payload.get("topic")),
            participant_ids=[str(item) for item in payload.get("participant_ids", [])],
            started_at_event_id=event.id,
        )
        return
    if event.type == EventType.MEETING_SESSION_ENDED:
        session.meeting.active = False
        session.meeting.ended_at_event_id = event.id
        return
    if event.type == EventType.MEETING_TURN_OPENED:
        session.meeting.turn = int(payload.get("turn", session.meeting.turn + 1))
        return
    if event.type == EventType.MEETING_VOTE_OPENED:
        session.meeting.vote_open = True
        session.meeting.vote_target_id = _optional_str(payload.get("target_id"))
        session.meeting.votes = {}
        return
    if event.type == EventType.MEETING_VOTE_CAST:
        voter_id = str(payload["voter_id"])
        session.meeting.votes[voter_id] = MeetingVoteState(
            voter_id=voter_id,
            target_id=str(payload["target_id"]),
            choice=MeetingVoteChoice(str(payload["choice"])),
            reason=_optional_str(payload.get("reason")),
            event_id=event.id,
        )
        return
    if event.type == EventType.MEETING_VERDICT_PROPOSED:
        session.meeting.verdict_target_id = _optional_str(payload.get("target_id"))
        session.meeting.verdict_status = "proposed"
        session.meeting.verdict_result = None
        session.meeting.verdict_reason = None
        session.meeting.missing_required_evidence = []
        session.meeting.missing_required_world_info = []
        session.meeting.verdict_event_id = event.id
        return
    if event.type == EventType.MEETING_VERDICT_ACCEPTED:
        session.meeting.vote_open = False
        session.meeting.verdict_target_id = _optional_str(payload.get("target_id"))
        session.meeting.verdict_status = "accepted"
        session.meeting.verdict_result = _optional_str(payload.get("result"))
        session.meeting.verdict_reason = None
        session.meeting.missing_required_evidence = []
        session.meeting.missing_required_world_info = []
        session.meeting.verdict_event_id = event.id
        return
    if event.type == EventType.MEETING_VERDICT_REJECTED:
        session.meeting.verdict_target_id = _optional_str(payload.get("target_id"))
        session.meeting.verdict_status = "rejected"
        session.meeting.verdict_result = None
        session.meeting.verdict_reason = _optional_str(payload.get("reason"))
        session.meeting.missing_required_evidence = [
            str(item) for item in payload.get("missing_required_evidence", [])
        ]
        session.meeting.missing_required_world_info = [
            str(item) for item in payload.get("missing_required_world_info", [])
        ]
        session.meeting.verdict_event_id = event.id


def _town_clock_from_event(event: WorldEvent) -> TownClockState:
    payload = _current_payload(event.payload)
    tick = payload.get("tick", payload.get("to_tick"))
    if tick is None:
        raise ValueError("town.tick.advanced payload requires current.tick")
    return TownClockState(
        tick=int(cast(Any, tick)),
        updated_at_event_id=event.id,
    )


def _npc_location_from_event(event: WorldEvent) -> NpcLocationState:
    payload = _current_payload(event.payload)
    npc_id = payload.get("npc_id", payload.get("character_id", event.actor_id))
    scene_id = payload.get("scene_id", payload.get("to_scene_id"))
    if scene_id is None:
        raise ValueError("npc.location.changed payload requires current.scene_id")

    location_payload: dict[str, Any] = {
        "npc_id": str(npc_id),
        "scene_id": str(scene_id),
        "updated_at_event_id": event.id,
    }
    for key in ("position_x", "position_y", "facing", "updated_at_tick"):
        if key in payload and payload[key] is not None:
            location_payload[key] = payload[key]
    return NpcLocationState.model_validate(location_payload)


def _current_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload.get("current")
    if isinstance(current, dict):
        return {str(key): item for key, item in current.items()}
    return payload


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _source_event_ids(payload: dict[str, object], fallback_event_id: str) -> list[str]:
    values = payload.get("source_event_ids")
    if isinstance(values, list):
        return [str(item) for item in values if str(item)]
    return [fallback_event_id]


def _metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}
