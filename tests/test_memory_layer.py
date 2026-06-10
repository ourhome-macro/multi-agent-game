from __future__ import annotations

from pathlib import Path

from app.agents.context import build_agent_context
from app.agents.memory import MemoryRetriever
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    EventType,
    MemoryCandidateState,
    PlayerAction,
    SessionState,
)
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"
EMPTY_CAPSULES = "empty_capsules"

SESSION_WORKING_MEMORY = "memory.player.session.working.empty_capsules"
SESSION_ARCHIVAL_MEMORY = "memory.player.session.archival.empty_capsules"


def test_session_working_memory_is_injected_as_public_context() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _append_memory_candidate(
        session,
        memory_id=SESSION_WORKING_MEMORY,
        memory_scope="session",
        memory_layer="working",
        content="Session working memory about empty_capsules.",
    )

    jiang_context = build_agent_context(case, session, _talk_action(JIANG))
    shen_context = build_agent_context(case, session, _talk_action(SHEN))

    assert SESSION_WORKING_MEMORY in _context_memory_ids(jiang_context)
    assert SESSION_WORKING_MEMORY in _context_memory_ids(shen_context)


def test_archival_memory_is_replayed_but_not_default_injected() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _append_memory_candidate(
        session,
        memory_id=SESSION_ARCHIVAL_MEMORY,
        memory_scope="session",
        memory_layer="archival",
        content="Archival memory about empty_capsules.",
        salience=1.0,
    )

    context = build_agent_context(case, session, _talk_action(JIANG))
    retrieved = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(JIANG),
    )
    replayed = replay_events(case, session.events)

    assert SESSION_ARCHIVAL_MEMORY not in _context_memory_ids(context)
    assert SESSION_ARCHIVAL_MEMORY not in _memory_ids(retrieved)
    assert (
        replayed.memory_candidates[SESSION_ARCHIVAL_MEMORY].memory_layer
        == "archival"
    )
    assert (
        replayed.memory_snapshots[SESSION_ARCHIVAL_MEMORY].memory_layer
        == "archival"
    )
    assert (
        replayed.memory_snapshots[SESSION_ARCHIVAL_MEMORY].memory_scope
        == "session"
    )


def test_memory_snapshot_event_preserves_scope_and_layer_payload() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _append_memory_candidate(
        session,
        memory_id=SESSION_WORKING_MEMORY,
        memory_scope="session",
        memory_layer="working",
        content="Session working memory about empty_capsules.",
    )

    snapshot_event = next(
        event
        for event in session.events
        if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED
    )

    assert snapshot_event.payload["memory_scope"] == "session"
    assert snapshot_event.payload["memory_layer"] == "working"


def _append_memory_candidate(
    session: SessionState,
    *,
    memory_id: str,
    memory_scope: str,
    memory_layer: str,
    content: str,
    salience: float = 0.8,
) -> None:
    recorder = EventRecorder()
    source_event_id = f"source.{memory_id}"
    session.memory_candidates[memory_id] = MemoryCandidateState(
        memory_id=memory_id,
        rule_id="memory_rule.test.manual.v1",
        memory_type="episodic",
        memory_scope=memory_scope,
        memory_layer=memory_layer,
        subject_id="player",
        owner_character_id=None,
        visible_to_character_ids=[],
        content=content,
        source_event_id=source_event_id,
        source_event_ids=[source_event_id],
        visibility=["player"],
        salience=salience,
        confidence=1.0,
        metadata={},
    )
    event = recorder.append(
        session,
        actor_id="test",
        event_type=EventType.MEMORY_CANDIDATE_CREATED,
        payload={
            "memory_id": memory_id,
            "rule_id": "memory_rule.test.manual.v1",
            "memory_type": "episodic",
            "memory_scope": memory_scope,
            "memory_layer": memory_layer,
            "subject_id": "player",
            "owner_character_id": None,
            "visible_to_character_ids": [],
            "content": content,
            "source_event_id": source_event_id,
            "source_event_ids": [source_event_id],
            "source_memory_ids": [],
            "visibility": ["player"],
            "salience": salience,
            "confidence": 1.0,
            "metadata": {},
        },
    )
    MemorySnapshotSystem(recorder).apply(session=session, event=event)


def _talk_action(target_id: str) -> PlayerAction:
    return PlayerAction(
        type=ActionType.TALK,
        target_id=target_id,
        text=f"ask about {EMPTY_CAPSULES}",
    )


def _context_memory_ids(context: object) -> set[str]:
    return {memory.memory_id for memory in context.memory_snapshots}


def _memory_ids(memories: list[object]) -> set[str]:
    return {str(memory.memory_id) for memory in memories}
