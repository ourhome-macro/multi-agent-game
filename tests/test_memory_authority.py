from __future__ import annotations

import json

from app.agents.gateway import AgentGateway
from app.agents.loop import AgentLoop
from app.agents.memory import MemoryRetriever
from app.domain.models import (
    ActionType,
    AgentMemorySnapshot,
    CaseMeta,
    CasePackage,
    CharacterConfig,
    ClueConfig,
    NarrativeState,
    PlayerAction,
    SceneConfig,
    SessionState,
)
from app.runtime.tracing import RuntimeTraceBuffer, RuntimeTracer

CASE_ID = "memory_authority"
PHASE = "opening"
JIANG = "jiang_yanhui"
EMPTY_CAPSULES = "empty_capsules"
WORLD_INFO_ID = "heart_medicine_replaced"
NEW_TS = "2026-06-17T09:00:00Z"


def test_non_authoritative_belief_cannot_outrank_authoritative_event_anchored_belief() -> None:
    authoritative = _memory(
        memory_id="memory.authority.belief.authoritative",
        content=(
            "Jiang believes the player is approaching the medicine truth "
            "through empty capsules."
        ),
        memory_type="belief",
        confidence=0.95,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "believes",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
        },
    )
    hearsay = _memory(
        memory_id="memory.authority.belief.non_authoritative",
        content="Jiang heard a rumor that empty capsules prove nothing and should be ignored.",
        memory_type="belief",
        confidence=1.0,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "doubts",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
            "non_authoritative": True,
        },
    )

    memories = _retrieve([hearsay, authoritative])

    assert _memory_ids(memories) == [authoritative.memory_id]


def test_conflicting_memories_for_same_world_info_are_isolated_to_deterministic_winner() -> None:
    lower_confidence = _memory(
        memory_id="memory.authority.conflict.low_confidence",
        content="Jiang suspects the empty capsules are unrelated to the medicine replacement.",
        memory_type="belief",
        confidence=0.65,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "doubts",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
        },
    )
    higher_confidence = _memory(
        memory_id="memory.authority.conflict.high_confidence",
        content="Jiang knows the empty capsules point toward the medicine replacement.",
        memory_type="belief",
        confidence=0.9,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "knows",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
        },
    )

    memories = _retrieve([lower_confidence, higher_confidence])

    assert _memory_ids(memories) == [higher_confidence.memory_id]


def test_conflict_resolution_trace_summary_records_dropped_memory_without_content() -> None:
    dropped_private_phrase = "PRIVATE_PLAYER_ORIGINAL: empty capsules prove nothing"
    winner_private_phrase = "SAFE_FRAGMENT_SUMMARY: medicine replacement pressure"
    lower_confidence = _memory(
        memory_id="memory.authority.audit.dropped",
        content=dropped_private_phrase,
        memory_type="belief",
        confidence=0.65,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "doubts",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
        },
    )
    higher_confidence = _memory(
        memory_id="memory.authority.audit.winner",
        content=winner_private_phrase,
        memory_type="belief",
        confidence=0.9,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "knows",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
        },
    )
    retriever = MemoryRetriever(max_results=20)
    session = _session([lower_confidence, higher_confidence])
    event_count_before = len(session.events)

    memories = retriever.retrieve(
        case=_case(),
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="continue asking about empty capsules and the medicine replacement",
        ),
    )

    assert _memory_ids(memories) == [higher_confidence.memory_id]
    assert len(session.events) == event_count_before
    summary = retriever.last_authority_trace_summary
    assert summary is not None
    assert len(summary.memory_conflict_resolution) == 1
    resolution = summary.memory_conflict_resolution[0]
    assert resolution.category == "high_impact_memory_conflict"
    assert resolution.reason == "lower_authority_profile"
    assert resolution.conflict_key == (
        "belief",
        JIANG,
        "player",
        "belief_subject",
        "player_approaching_medicine_truth",
    )
    assert resolution.winner_memory_id == higher_confidence.memory_id
    assert resolution.dropped_memory_ids == (lower_confidence.memory_id,)

    serialized = json.dumps(summary.to_projection(), ensure_ascii=False)
    assert dropped_private_phrase not in serialized
    assert winner_private_phrase not in serialized
    assert "content" not in serialized
    assert "safe_fragment" not in serialized.casefold()


def test_agent_loop_trace_projects_memory_conflict_resolution_without_content() -> None:
    dropped_private_phrase = "PRIVATE_PLAYER_ORIGINAL: empty capsules prove nothing"
    winner_private_phrase = "SAFE_FRAGMENT_SUMMARY: medicine replacement pressure"
    lower_confidence = _memory(
        memory_id="memory.authority.loop.dropped",
        content=dropped_private_phrase,
        memory_type="belief",
        confidence=0.65,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "doubts",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
        },
    )
    higher_confidence = _memory(
        memory_id="memory.authority.loop.winner",
        content=winner_private_phrase,
        memory_type="belief",
        confidence=0.9,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "knows",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
        },
    )
    trace_buffer = RuntimeTraceBuffer()
    loop = AgentLoop(
        agent_gateway=AgentGateway(),
        runtime_tracer=RuntimeTracer(sink=trace_buffer),
        memory_retriever=MemoryRetriever(max_results=20),
    )
    session = _session([lower_confidence, higher_confidence])

    turn = loop.run_turn(
        case=_case(),
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="continue asking about empty capsules and the medicine replacement",
        ),
    )
    loop.finish_trace(
        turn,
        director_allowed=True,
        director_reason_category=None,
        rule_rejections=[],
        new_events=[],
        phase_after=PHASE,
        public_speech=turn.intent.speech,
        public_speech_source="npc",
    )

    records = trace_buffer.drain()
    assert len(records) == 1
    memory_projection = records[0]["memory_projection"]
    resolutions = memory_projection["memory_conflict_resolution"]
    assert resolutions == [
        {
            "category": "high_impact_memory_conflict",
            "reason": "lower_authority_profile",
            "conflict_key": [
                "belief",
                JIANG,
                "player",
                "belief_subject",
                "player_approaching_medicine_truth",
            ],
            "winner_memory_id": higher_confidence.memory_id,
            "dropped_memory_ids": [lower_confidence.memory_id],
        }
    ]
    serialized_projection = json.dumps(memory_projection, ensure_ascii=False)
    serialized_resolutions = json.dumps(resolutions, ensure_ascii=False)
    assert dropped_private_phrase not in serialized_projection
    assert winner_private_phrase not in serialized_projection
    assert "content" not in serialized_projection
    assert "safe_fragment" not in serialized_resolutions.casefold()
    assert len(session.events) == 0


def test_low_confidence_strategy_memory_is_gated_from_npc_context() -> None:
    low_confidence_strategy = _memory(
        memory_id="memory.authority.strategy.low_confidence",
        content="Jiang should aggressively deny everything about empty capsules.",
        memory_type="strategy",
        confidence=0.34,
        metadata={
            "strategy_id": "deny_empty_capsules",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
        },
    )
    episodic_anchor = _memory(
        memory_id="memory.authority.episodic.anchor",
        content="Player presented empty capsules to Jiang.",
        memory_type="episodic",
        confidence=0.8,
        metadata={"clue_id": EMPTY_CAPSULES, "world_info_id": WORLD_INFO_ID},
    )

    memories = _retrieve([low_confidence_strategy, episodic_anchor])

    assert _memory_ids(memories) == [episodic_anchor.memory_id]


def test_higher_authority_source_beats_lower_authority_high_confidence_belief() -> None:
    player_evidence = _memory(
        memory_id="memory.authority.level.player_evidence",
        content="Jiang saw the player connect empty capsules to the medicine replacement.",
        memory_type="belief",
        confidence=0.72,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "believes",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
            "authority_source": "player_evidence",
        },
    )
    npc_hearsay = _memory(
        memory_id="memory.authority.level.npc_hearsay",
        content="Jiang heard hearsay that the capsules were planted.",
        memory_type="belief",
        confidence=0.99,
        metadata={
            "belief_subject": "player_approaching_medicine_truth",
            "belief_polarity": "doubts",
            "world_info_id": WORLD_INFO_ID,
            "clue_id": EMPTY_CAPSULES,
            "authority_source": "npc_hearsay",
        },
    )

    memories = _retrieve([npc_hearsay, player_evidence])

    assert _memory_ids(memories) == [player_evidence.memory_id]


def _retrieve(snapshots: list[AgentMemorySnapshot]) -> list[AgentMemorySnapshot]:
    return MemoryRetriever(max_results=20).retrieve(
        case=_case(),
        session=_session(snapshots),
        action=PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=JIANG,
            subject_type="clue",
            subject_id=EMPTY_CAPSULES,
            text="continue asking about empty capsules and the medicine replacement",
        ),
    )


def _memory(
    *,
    memory_id: str,
    content: str,
    memory_type: str,
    confidence: float,
    metadata: dict[str, object],
) -> AgentMemorySnapshot:
    return AgentMemorySnapshot(
        memory_id=memory_id,
        rule_id="memory_rule.test.authority.v1",
        memory_type=memory_type,
        memory_scope="npc_private",
        memory_layer="working",
        subject_id="player",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
        content=content,
        source_event_ids=[f"event.{memory_id}"],
        source_memory_ids=[],
        salience=0.8,
        confidence=confidence,
        visibility="private",
        metadata=metadata,
        last_updated_event_id=f"snapshot.{memory_id}",
        created_at=NEW_TS,
        updated_at=NEW_TS,
    )


def _case() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(id=CASE_ID, title="Memory Authority Case", initial_phase=PHASE),
        characters=[CharacterConfig(id=JIANG, display_name="Jiang", public_role="Doctor")],
        scenes=[SceneConfig(id="study", name="Study")],
        clues=[
            ClueConfig(
                id=EMPTY_CAPSULES,
                title="empty capsules",
                description="Empty capsules in the medicine box.",
                reveals_world_info=[WORLD_INFO_ID],
            )
        ],
    )


def _session(snapshots: list[AgentMemorySnapshot]) -> SessionState:
    return SessionState(
        id="session.memory_authority",
        case_id=CASE_ID,
        narrative=NarrativeState(phase=PHASE),
        relationships={},
        memory_snapshots={snapshot.memory_id: snapshot for snapshot in snapshots},
    )


def _memory_ids(memories: list[AgentMemorySnapshot]) -> list[str]:
    return [memory.memory_id for memory in memories]
