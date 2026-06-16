from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.agents.memory import MemoryRetriever
from app.agents.memory_retrieval import MemorySearchQuery, MemorySearchResult
from app.domain.models import (
    ActionType,
    AgentMemorySnapshot,
    CaseMeta,
    CasePackage,
    CharacterConfig,
    ClueConfig,
    EventType,
    MemoryCandidateState,
    MemoryOperation,
    NarrativeState,
    PlayerAction,
    SceneConfig,
    SessionState,
)
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem

CASE_ID = "memory_v2"
PHASE = "opening"
JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"
EMPTY_CAPSULES = "empty_capsules"
UNRELATED_TOPIC = "seating_chart"
NOW_TS = "2026-06-15T09:00:00Z"


class AnchorEmbeddingScorer:
    def score(
        self,
        *,
        query: MemorySearchQuery,
        snapshot: AgentMemorySnapshot,
    ) -> float:
        if (
            "embedding_anchor" in query.text_tokens
            and "latent medical pressure" in snapshot.content
        ):
            return 2.0
        return 0.0


class ReverseReranker:
    def rerank(
        self,
        *,
        query: MemorySearchQuery,
        results: Sequence[MemorySearchResult],
    ) -> Sequence[MemorySearchResult]:
        _ = query
        return list(reversed(results))


def test_memory_operation_accepts_v2_and_legacy_archive_alias() -> None:
    candidate = MemoryCandidateState(
        memory_id="memory.v2.operation.legacy",
        memory_type="episodic",
        memory_scope="npc_private",
        memory_layer="archival",
        operation="archived",
        subject_id="player",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
        content="Legacy archival event.",
        source_event_id="event.legacy.archive",
        source_event_ids=["event.legacy.archive"],
    )
    snapshot = AgentMemorySnapshot(
        memory_id="memory.v2.operation.snapshot",
        memory_type="episodic",
        memory_scope="npc_private",
        memory_layer="archival",
        last_operation="archived",
        subject_id="player",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
        content="Legacy archival snapshot.",
        source_event_ids=["event.legacy.archive"],
        last_updated_event_id="event.legacy.archive",
    )

    assert candidate.operation == MemoryOperation.ARCHIVE
    assert snapshot.last_operation == MemoryOperation.ARCHIVE


def test_memory_metadata_v2_allows_stable_fields_and_rejects_shape_drift() -> None:
    snapshot = AgentMemorySnapshot(
        memory_id="memory.v2.metadata",
        memory_type="belief",
        memory_scope="npc_private",
        memory_layer="working",
        subject_id="player",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
        content="Jiang links the player to the medicine clue.",
        source_event_ids=["event.metadata"],
        metadata={
            "world_info_id": "heart_medicine_replaced",
            "claim_id": "shared_death_chain",
            "scene_id": "study",
            "phase_id": "opening",
            "phase_ids": ["opening", "investigation", "opening"],
            "topic_tags": ["medicine", "pressure", "medicine"],
            "privacy_reason": "npc_private_owner_only",
            "decay_policy": {
                "name": "standard",
                "archive_after_days": 7,
                "reinforced_event_count": 2,
            },
        },
        last_updated_event_id="event.metadata",
    )

    assert snapshot.metadata["topic_tags"] == ["medicine", "pressure"]
    assert snapshot.metadata["phase_ids"] == ["opening", "investigation"]
    assert snapshot.metadata["decay_policy"] == {
        "name": "standard",
        "archive_after_days": 7,
        "reinforced_event_count": 2,
    }

    with pytest.raises(ValueError, match="topic_tags must be a list"):
        AgentMemorySnapshot(
            memory_id="memory.v2.metadata.bad_tags",
            content="Bad metadata.",
            metadata={"topic_tags": "medicine"},
            last_updated_event_id="event.bad_tags",
        )

    with pytest.raises(ValueError, match="Unsupported memory decay_policy keys"):
        AgentMemorySnapshot(
            memory_id="memory.v2.metadata.bad_decay",
            content="Bad metadata.",
            metadata={"decay_policy": {"freeform": True}},
            last_updated_event_id="event.bad_decay",
        )


def test_memory_snapshot_system_records_explicit_reinforce_revise_supersede_archive() -> None:
    session = _session()
    recorder = EventRecorder()
    snapshot_system = MemorySnapshotSystem(recorder)
    _append_memory_candidate(
        session,
        snapshot_system,
        recorder,
        memory_id="memory.v2.reducer",
        operation="create",
        content="Initial player pressure.",
        source_event_id="event.source.1",
        salience=0.4,
        metadata={"topic_tags": ["medicine"]},
    )
    _append_memory_candidate(
        session,
        snapshot_system,
        recorder,
        memory_id="memory.v2.reducer",
        operation="reinforce",
        content="This reinforce content should not rewrite the canonical text.",
        source_event_id="event.source.2",
        salience=0.9,
        metadata={"world_info_id": "heart_medicine_replaced"},
    )
    _append_memory_candidate(
        session,
        snapshot_system,
        recorder,
        memory_id="memory.v2.reducer",
        operation="revise",
        content="Revised player pressure with clearer medicine anchor.",
        source_event_id="event.source.3",
        salience=0.7,
        metadata={"topic_tags": ["medicine", "revision"]},
    )
    _append_memory_candidate(
        session,
        snapshot_system,
        recorder,
        memory_id="memory.v2.reducer",
        operation="supersede",
        content="Superseding memory narrows the player medicine pressure.",
        source_event_id="event.source.4",
        salience=0.5,
        metadata={"topic_tags": ["medicine", "superseded"]},
    )
    _append_memory_candidate(
        session,
        snapshot_system,
        recorder,
        memory_id="memory.v2.reducer",
        operation="archive",
        content="Archive operation preserves revised content.",
        source_event_id="event.source.5",
        salience=0.8,
    )

    snapshot = session.memory_snapshots["memory.v2.reducer"]
    snapshot_events = [
        event
        for event in session.events
        if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED
        and event.payload["memory_id"] == "memory.v2.reducer"
    ]

    assert [event.payload["operation"] for event in snapshot_events] == [
        "create",
        "reinforce",
        "revise",
        "supersede",
        "archive",
    ]
    assert snapshot.source_event_ids == [
        "event.source.1",
        "event.source.2",
        "event.source.3",
        "event.source.4",
        "event.source.5",
    ]
    assert snapshot.content == "Superseding memory narrows the player medicine pressure."
    assert snapshot.salience == 0.8
    assert snapshot.memory_layer == "archival"
    assert snapshot.last_operation == MemoryOperation.ARCHIVE
    assert "world_info_id" not in snapshot.metadata
    assert snapshot.metadata["topic_tags"] == ["medicine", "superseded"]


def test_active_memory_candidate_without_source_is_rejected() -> None:
    session = _session()
    recorder = EventRecorder()
    snapshot_system = MemorySnapshotSystem(recorder)
    event = recorder.append(
        session,
        actor_id="test",
        event_type=EventType.MEMORY_CANDIDATE_CREATED,
        payload={
            "memory_id": "memory.v2.unsourced",
            "memory_type": "episodic",
            "memory_scope": "npc_private",
            "memory_layer": "working",
            "operation": "create",
            "subject_id": "player",
            "owner_character_id": JIANG,
            "visible_to_character_ids": [JIANG],
            "content": "Unsourced active memory must not become agent context.",
            "source_event_ids": [],
            "source_memory_ids": [],
            "visibility": ["player"],
            "salience": 1.0,
        },
    )

    with pytest.raises(ValueError, match="must include source_event_ids"):
        snapshot_system.apply(session=session, event=event)


def test_non_authoritative_unsourced_memory_can_be_stored_but_not_retrieved() -> None:
    session = _session()
    recorder = EventRecorder()
    snapshot_system = MemorySnapshotSystem(recorder)
    event = recorder.append(
        session,
        actor_id="test",
        event_type=EventType.MEMORY_CANDIDATE_CREATED,
        payload={
            "memory_id": "memory.v2.unsourced.non_authoritative",
            "memory_type": "episodic",
            "memory_scope": "npc_private",
            "memory_layer": "working",
            "operation": "create",
            "subject_id": "player",
            "owner_character_id": JIANG,
            "visible_to_character_ids": [JIANG],
            "content": "empty capsules hearsay without event provenance",
            "source_event_ids": [],
            "source_memory_ids": [],
            "visibility": ["player"],
            "salience": 1.0,
            "metadata": {"non_authoritative": True},
        },
    )

    snapshot_system.apply(session=session, event=event)
    memories = MemoryRetriever(max_results=10).retrieve(
        case=_case(),
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="empty capsules"),
    )

    assert (
        session.memory_snapshots[
            "memory.v2.unsourced.non_authoritative"
        ].source_event_ids
        == []
    )
    assert memories == []


def test_memory_retrieval_returns_empty_when_no_relevant_hit_even_with_high_salience() -> None:
    unrelated = _memory(
        memory_id="memory.v2.unrelated.high_salience",
        content="The player studied the seating chart for a long time.",
        salience=1.0,
    )

    memories = MemoryRetriever(max_results=10).retrieve(
        case=_case(),
        session=_session([unrelated]),
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="empty capsules",
        ),
    )

    assert memories == []


def test_memory_retrieval_hard_filter_blocks_other_npc_private_before_scoring() -> None:
    jiang_memory = _memory(
        memory_id="memory.v2.jiang.empty_capsules",
        content="Jiang remembers the player asking about empty capsules.",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
        salience=0.2,
    )
    shen_private = _memory(
        memory_id="memory.v2.shen.private.empty_capsules",
        content="Shen remembers the player asking about empty capsules.",
        owner_character_id=SHEN,
        visible_to_character_ids=[SHEN],
        salience=1.0,
    )

    memories = MemoryRetriever(max_results=10).retrieve(
        case=_case(),
        session=_session([shen_private, jiang_memory]),
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="empty capsules",
        ),
    )

    assert [memory.memory_id for memory in memories] == [jiang_memory.memory_id]


def test_memory_retrieval_phase_filter_runs_before_scoring() -> None:
    opening_memory = _memory(
        memory_id="memory.v2.phase.opening.empty_capsules",
        content="Jiang remembers empty capsules in the opening.",
        metadata={"phase_ids": ["opening"]},
        salience=0.1,
    )
    reconstruction_memory = _memory(
        memory_id="memory.v2.phase.reconstruction.empty_capsules",
        content="Jiang remembers empty capsules only during reconstruction.",
        metadata={"phase_id": "reconstruction"},
        salience=1.0,
    )

    memories = MemoryRetriever(max_results=10).retrieve(
        case=_case(),
        session=_session([reconstruction_memory, opening_memory]),
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="empty capsules"),
    )

    assert [memory.memory_id for memory in memories] == [opening_memory.memory_id]


def test_memory_retrieval_accepts_topic_and_source_relevance_without_salience_fallback() -> None:
    topic = _memory(
        memory_id="memory.v2.topic",
        content="Jiang remembers the player applying pressure.",
        metadata={"topic_tags": ["empty_capsules"]},
        salience=0.1,
    )
    source = _memory(
        memory_id="memory.v2.source",
        content="Jiang remembers a prior pressure turn.",
        source_event_ids=["event.empty_capsules.presented"],
        salience=0.1,
    )
    unrelated = _memory(
        memory_id="memory.v2.unrelated.topic_high_salience",
        content="Jiang remembers seating chart questions.",
        salience=1.0,
    )

    memories = MemoryRetriever(max_results=10).retrieve(
        case=_case(),
        session=_session([unrelated, source, topic]),
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="empty_capsules"),
    )

    assert {memory.memory_id for memory in memories} == {
        source.memory_id,
        topic.memory_id,
    }
    assert unrelated.memory_id not in {memory.memory_id for memory in memories}


def test_memory_retrieval_can_use_embedding_and_reranker_slots() -> None:
    first = _memory(
        memory_id="memory.v2.embedding.first",
        content="latent medical pressure",
        salience=0.1,
    )
    second = _memory(
        memory_id="memory.v2.embedding.second",
        content="latent medical pressure",
        salience=0.2,
    )

    memories = MemoryRetriever(
        max_results=10,
        embedding_scorer=AnchorEmbeddingScorer(),
        reranker=ReverseReranker(),
    ).retrieve(
        case=_case(),
        session=_session([first, second]),
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="embedding_anchor",
        ),
    )

    assert [memory.memory_id for memory in memories] == [
        first.memory_id,
        second.memory_id,
    ]


def _append_memory_candidate(
    session: SessionState,
    snapshot_system: MemorySnapshotSystem,
    recorder: EventRecorder,
    *,
    memory_id: str,
    operation: str,
    content: str,
    source_event_id: str,
    salience: float,
    metadata: dict[str, object] | None = None,
) -> None:
    event = recorder.append(
        session,
        actor_id="test",
        event_type=EventType.MEMORY_CANDIDATE_CREATED,
        payload={
            "memory_id": memory_id,
            "rule_id": "memory_rule.test.v2",
            "memory_type": "episodic",
            "memory_scope": "npc_private",
            "memory_layer": "working",
            "operation": operation,
            "subject_id": "player",
            "owner_character_id": JIANG,
            "visible_to_character_ids": [JIANG],
            "content": content,
            "source_event_id": source_event_id,
            "source_event_ids": [source_event_id],
            "source_memory_ids": [],
            "visibility": ["player"],
            "salience": salience,
            "confidence": 1.0,
            "metadata": metadata or {},
        },
    )
    snapshot_system.apply(session=session, event=event)


def _memory(
    *,
    memory_id: str,
    content: str,
    salience: float,
    owner_character_id: str | None = JIANG,
    visible_to_character_ids: list[str] | None = None,
    memory_scope: str = "npc_private",
    memory_layer: str = "working",
    source_event_ids: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> AgentMemorySnapshot:
    return AgentMemorySnapshot(
        memory_id=memory_id,
        memory_type="episodic",
        memory_scope=memory_scope,
        memory_layer=memory_layer,
        subject_id="player",
        owner_character_id=owner_character_id,
        visible_to_character_ids=visible_to_character_ids or [JIANG],
        content=content,
        source_event_ids=source_event_ids or [f"source.{memory_id}"],
        source_memory_ids=[],
        salience=salience,
        confidence=1.0,
        visibility="private",
        metadata=metadata or {},
        last_updated_event_id=f"snapshot.{memory_id}",
        created_at=NOW_TS,
        updated_at=NOW_TS,
    )


def _case() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id=CASE_ID,
            title="Memory v2 Case",
            initial_phase=PHASE,
        ),
        characters=[
            CharacterConfig(id=JIANG, display_name="Jiang", public_role="Doctor"),
            CharacterConfig(id=SHEN, display_name="Shen", public_role="Heir"),
        ],
        scenes=[SceneConfig(id="study", name="Study")],
        clues=[
            ClueConfig(
                id=EMPTY_CAPSULES,
                title="empty capsules",
                description="Empty capsules in the medicine box.",
                reveals_world_info=["heart_medicine_replaced"],
            ),
            ClueConfig(
                id=UNRELATED_TOPIC,
                title="seating chart",
                description="A seating chart.",
            ),
        ],
    )


def _session(
    snapshots: list[AgentMemorySnapshot] | None = None,
) -> SessionState:
    return SessionState(
        id="session.memory_v2",
        case_id=CASE_ID,
        narrative=NarrativeState(phase=PHASE),
        relationships={},
        memory_snapshots={
            snapshot.memory_id: snapshot
            for snapshot in snapshots or []
        },
    )
