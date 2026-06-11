from __future__ import annotations

import json
from pathlib import Path

from app.agents.gateway import AgentGateway
from app.agents.memory import MemoryRetriever
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    CasePackage,
    EventType,
    MemoryCandidateState,
    PlayerAction,
    PresentationMode,
    SessionState,
)
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem
from app.runtime.replay import replay_events
from app.runtime.service import RuntimeContainer, create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

JIANG = "jiang_yanhui"
QI = "qi_yan"
LIN = "lin_qichi"
SHEN = "shen_zhaoye"
STUDY = "study"
EMPTY_CAPSULES = "empty_capsules"

PRIVATE_PRESENTED_MEMORY = f"memory.player.presented_clue.{JIANG}.{EMPTY_CAPSULES}"
BELIEF_MEMORY = f"memory.player.belief.{JIANG}.{EMPTY_CAPSULES}"
RELATIONSHIP_MEMORY = f"memory.player.relationship.{JIANG}.{EMPTY_CAPSULES}"
STRATEGY_MEMORY = f"memory.player.strategy.{JIANG}.{EMPTY_CAPSULES}"
SCENE_SHARED_MEMORY = f"memory.player.scene_shared.presented_clue.{STUDY}.{EMPTY_CAPSULES}"
CASE_CORE_MEMORY = f"memory.player.clue_discovered.{EMPTY_CAPSULES}"
ARCHIVAL_MEMORY = "memory.player.archival.empty_capsules.audit_fixture"
PRIVATE_TYPED_MEMORY_IDS = {
    PRIVATE_PRESENTED_MEMORY,
    BELIEF_MEMORY,
    RELATIONSHIP_MEMORY,
    STRATEGY_MEMORY,
}


class RecordingAgent:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    def generate(self, context: AgentContext) -> AgentIntent:
        self.contexts.append(context)
        if context.player_action.force_forbidden:
            return AgentIntent(
                speech="Jiang replaced the medicine.",
                intent=AgentIntentType.ANSWER,
                proposed_actions=[],
            )
        return AgentIntent(
            speech="Recorded.",
            intent=AgentIntentType.ANSWER,
            proposed_actions=[],
        )


class DeterministicRealAgent(RecordingAgent):
    @property
    def model_name(self) -> str:
        return "deterministic-real-test-model"


def test_private_memory_stays_inside_target_npc_context_retriever_and_events() -> None:
    case, runtime, session, agent = _runtime_with_recording_agent()

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules(runtime, session, target_id=JIANG)
    _talk(runtime, session, JIANG)
    _talk(runtime, session, QI)
    _talk(runtime, session, SHEN)

    jiang_context = _last_context_for(agent, JIANG)
    qi_context = _last_context_for(agent, QI)
    shen_context = _last_context_for(agent, SHEN)

    assert PRIVATE_TYPED_MEMORY_IDS <= _context_memory_ids(jiang_context)
    assert CASE_CORE_MEMORY in _context_memory_ids(qi_context)
    assert CASE_CORE_MEMORY in _context_memory_ids(shen_context)
    assert not (PRIVATE_TYPED_MEMORY_IDS & _context_memory_ids(qi_context))
    assert not (PRIVATE_TYPED_MEMORY_IDS & _context_memory_ids(shen_context))
    assert not (PRIVATE_TYPED_MEMORY_IDS & _recent_memory_ids(qi_context))
    assert not (PRIVATE_TYPED_MEMORY_IDS & _recent_memory_ids(shen_context))

    jiang_retrieved = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(JIANG),
    )
    qi_retrieved = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(QI),
    )
    shen_retrieved = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(SHEN),
    )
    assert PRIVATE_TYPED_MEMORY_IDS <= _memory_ids(jiang_retrieved)
    assert not (PRIVATE_TYPED_MEMORY_IDS & _memory_ids(qi_retrieved))
    assert not (PRIVATE_TYPED_MEMORY_IDS & _memory_ids(shen_retrieved))
    assert all(
        session.memory_snapshots[memory_id].memory_scope == "npc_private"
        for memory_id in PRIVATE_TYPED_MEMORY_IDS
    )


def test_scene_shared_memory_reaches_present_scene_npcs_but_not_absent_npcs() -> None:
    case, runtime, session, agent = _runtime_with_recording_agent()

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules(runtime, session, target_id=JIANG, scene_id=STUDY)
    _talk(runtime, session, JIANG)
    _talk(runtime, session, QI)
    _talk(runtime, session, LIN)
    _talk(runtime, session, SHEN)

    jiang_context = _last_context_for(agent, JIANG)
    qi_context = _last_context_for(agent, QI)
    lin_context = _last_context_for(agent, LIN)
    shen_context = _last_context_for(agent, SHEN)

    shared = session.memory_snapshots[SCENE_SHARED_MEMORY]
    assert shared.memory_scope == "scene_shared"
    assert shared.memory_layer == "working"
    assert set(shared.visible_to_character_ids) == {LIN, QI, JIANG}
    assert SCENE_SHARED_MEMORY in _context_memory_ids(jiang_context)
    assert SCENE_SHARED_MEMORY in _context_memory_ids(qi_context)
    assert SCENE_SHARED_MEMORY in _context_memory_ids(lin_context)
    assert SCENE_SHARED_MEMORY not in _context_memory_ids(shen_context)
    assert SCENE_SHARED_MEMORY in _recent_memory_ids(qi_context)
    assert SCENE_SHARED_MEMORY in _recent_memory_ids(lin_context)
    assert SCENE_SHARED_MEMORY not in _recent_memory_ids(shen_context)
    assert PRIVATE_TYPED_MEMORY_IDS <= _context_memory_ids(jiang_context)
    assert not (PRIVATE_TYPED_MEMORY_IDS & _context_memory_ids(qi_context))
    assert not (PRIVATE_TYPED_MEMORY_IDS & _context_memory_ids(lin_context))

    qi_retrieved = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(QI),
    )
    shen_retrieved = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(SHEN),
    )
    assert SCENE_SHARED_MEMORY in _memory_ids(qi_retrieved)
    assert SCENE_SHARED_MEMORY not in _memory_ids(shen_retrieved)


def test_director_audit_memory_never_enters_npc_context_or_recent_events() -> None:
    case, runtime, session, agent = _runtime_with_recording_agent()

    _force_director_block(runtime, session, target_id=JIANG)
    _talk(runtime, session, JIANG, text="director blocked jiang_yanhui")
    _talk(runtime, session, QI, text="director blocked jiang_yanhui")

    audit_snapshot = _single_snapshot_by_scope(session, "director_audit")
    jiang_context = _last_context_for(agent, JIANG)
    qi_context = _last_context_for(agent, QI)

    assert audit_snapshot.memory_layer == "working"
    assert audit_snapshot.memory_id not in _context_memory_ids(jiang_context)
    assert audit_snapshot.memory_id not in _context_memory_ids(qi_context)
    assert audit_snapshot.memory_id not in _recent_memory_ids(jiang_context)
    assert audit_snapshot.memory_id not in _recent_memory_ids(qi_context)
    assert audit_snapshot.memory_id not in _memory_ids(
        MemoryRetriever(max_results=20).retrieve(
            case=case,
            session=session,
            action=_talk_action(JIANG),
        )
    )
    assert audit_snapshot.memory_id in _memory_ids(
        MemoryRetriever(max_results=20).retrieve_for_director(
            case=case,
            session=session,
            action=_talk_action(QI, text="director blocked jiang_yanhui"),
        )
    )


def test_archival_memory_replays_but_does_not_project_by_default() -> None:
    case, runtime, session, agent = _runtime_with_recording_agent()

    _discover_empty_capsules(runtime, session)
    _append_memory_candidate(
        session,
        memory_id=ARCHIVAL_MEMORY,
        memory_scope="session",
        memory_layer="archival",
        content="Archived empty capsules signal.",
    )
    _talk(runtime, session, JIANG, text="archival empty_capsules")

    context = _last_context_for(agent, JIANG)
    replayed = replay_events(case, session.events)

    assert ARCHIVAL_MEMORY in session.memory_snapshots
    assert replayed.memory_candidates[ARCHIVAL_MEMORY].memory_scope == "session"
    assert replayed.memory_candidates[ARCHIVAL_MEMORY].memory_layer == "archival"
    assert replayed.memory_snapshots[ARCHIVAL_MEMORY].memory_scope == "session"
    assert replayed.memory_snapshots[ARCHIVAL_MEMORY].memory_layer == "archival"
    assert ARCHIVAL_MEMORY not in _context_memory_ids(context)
    assert ARCHIVAL_MEMORY not in _recent_memory_ids(context)
    assert ARCHIVAL_MEMORY not in _memory_ids(
        MemoryRetriever(max_results=20).retrieve(
            case=case,
            session=session,
            action=_talk_action(JIANG, text="archival empty_capsules"),
        )
    )


def test_replay_preserves_mixed_memory_projection_boundaries() -> None:
    case, runtime, session, agent = _runtime_with_recording_agent()

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules(runtime, session, target_id=JIANG)
    _present_empty_capsules(runtime, session, target_id=JIANG, scene_id=STUDY)
    _force_director_block(runtime, session, target_id=JIANG)
    _append_memory_candidate(
        session,
        memory_id=ARCHIVAL_MEMORY,
        memory_scope="session",
        memory_layer="archival",
        content="Archived empty capsules signal.",
    )

    replayed = replay_events(case, session.events)
    _talk(runtime, replayed, JIANG, text="empty_capsules replay check")
    _talk(runtime, replayed, QI, text="empty_capsules replay check")
    jiang_context = _last_context_for(agent, JIANG)
    qi_context = _last_context_for(agent, QI)
    audit_snapshot = _single_snapshot_by_scope(replayed, "director_audit")

    for memory_id, snapshot in session.memory_snapshots.items():
        assert replayed.memory_snapshots[memory_id].memory_scope == snapshot.memory_scope
        assert replayed.memory_snapshots[memory_id].memory_layer == snapshot.memory_layer

    assert CASE_CORE_MEMORY in _context_memory_ids(jiang_context)
    assert PRIVATE_PRESENTED_MEMORY in _context_memory_ids(jiang_context)
    assert SCENE_SHARED_MEMORY in _context_memory_ids(jiang_context)
    assert CASE_CORE_MEMORY in _context_memory_ids(qi_context)
    assert SCENE_SHARED_MEMORY in _context_memory_ids(qi_context)
    assert PRIVATE_PRESENTED_MEMORY not in _context_memory_ids(qi_context)
    assert audit_snapshot.memory_id not in _context_memory_ids(jiang_context)
    assert audit_snapshot.memory_id not in _context_memory_ids(qi_context)
    assert ARCHIVAL_MEMORY not in _context_memory_ids(jiang_context)


def test_real_backend_trace_records_memory_scope_layer_projection(tmp_path: Path) -> None:
    case = CaseLoader().load(CASE_DIR)
    agent = DeterministicRealAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(backend="real", real_agent=agent),
        runtime_tracer=RuntimeTracer(
            jsonl_path=tmp_path / "trace.jsonl",
            log_path=tmp_path / "trace.log",
        ),
    )
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules(runtime, session, target_id=JIANG, scene_id=STUDY)
    _force_director_block(runtime, session, target_id=JIANG)
    _append_memory_candidate(
        session,
        memory_id=ARCHIVAL_MEMORY,
        memory_scope="session",
        memory_layer="archival",
        content="Archived empty capsules signal.",
    )
    _talk(runtime, session, JIANG, text="empty_capsules trace projection")

    records = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    record = records[-1]
    memory_projection = record["memory_projection"]
    projection = {
        item["memory_id"]: item
        for item in memory_projection["items"]
    }

    assert record["agent_backend"] == "real"
    assert record["model"] == "deterministic-real-test-model"
    assert memory_projection["skill_id"] == "talk"
    assert memory_projection["selected_count"] == len(memory_projection["items"])
    assert projection[CASE_CORE_MEMORY]["memory_scope"] == "case"
    assert projection[CASE_CORE_MEMORY]["memory_layer"] == "core"
    assert projection[PRIVATE_PRESENTED_MEMORY]["memory_scope"] == "npc_private"
    assert projection[PRIVATE_PRESENTED_MEMORY]["memory_layer"] == "working"
    assert projection[SCENE_SHARED_MEMORY]["memory_scope"] == "scene_shared"
    assert projection[SCENE_SHARED_MEMORY]["memory_layer"] == "working"
    assert ARCHIVAL_MEMORY not in projection
    assert not any(item["memory_scope"] == "director_audit" for item in projection.values())
    assert "content" not in json.dumps(memory_projection, ensure_ascii=False)
    assert set(record["memory_ids_used"]) == set(projection)


def _runtime_with_recording_agent() -> tuple[
    CasePackage,
    RuntimeContainer,
    SessionState,
    RecordingAgent,
]:
    case = CaseLoader().load(CASE_DIR)
    agent = RecordingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)
    return case, runtime, session, agent


def _discover_empty_capsules(runtime: RuntimeContainer, session: SessionState) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="medicine_box"),
    )


def _present_empty_capsules(
    runtime: RuntimeContainer,
    session: SessionState,
    *,
    target_id: str,
    scene_id: str | None = None,
) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=target_id,
            clue_id=EMPTY_CAPSULES,
            presentation_mode=(
                PresentationMode.SCENE_SHARED
                if scene_id is not None
                else PresentationMode.PRIVATE
            ),
            scene_id=scene_id,
            text="present empty capsules",
        ),
    )


def _force_director_block(
    runtime: RuntimeContainer,
    session: SessionState,
    *,
    target_id: str,
) -> None:
    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=target_id,
            text="force forbidden audit",
            force_forbidden=True,
        ),
    )
    assert response.director_blocked is True


def _talk(
    runtime: RuntimeContainer,
    session: SessionState,
    target_id: str,
    *,
    text: str = "empty_capsules",
) -> None:
    runtime.action_service.handle(
        session=session,
        action=_talk_action(target_id, text=text),
    )


def _talk_action(target_id: str, *, text: str = "empty_capsules") -> PlayerAction:
    return PlayerAction(type=ActionType.TALK, target_id=target_id, text=text)


def _append_memory_candidate(
    session: SessionState,
    *,
    memory_id: str,
    memory_scope: str,
    memory_layer: str,
    content: str,
) -> None:
    recorder = EventRecorder()
    source_event_id = f"source.{memory_id}"
    session.memory_candidates[memory_id] = MemoryCandidateState(
        memory_id=memory_id,
        rule_id="memory_rule.test.archival.v1",
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
        salience=1.0,
        confidence=1.0,
        metadata={},
    )
    event = recorder.append(
        session,
        actor_id="test",
        event_type=EventType.MEMORY_CANDIDATE_CREATED,
        payload={
            "memory_id": memory_id,
            "rule_id": "memory_rule.test.archival.v1",
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
            "salience": 1.0,
            "confidence": 1.0,
            "metadata": {},
        },
    )
    MemorySnapshotSystem(recorder).apply(session=session, event=event)


def _last_context_for(agent: RecordingAgent, target_id: str) -> AgentContext:
    return next(
        context
        for context in reversed(agent.contexts)
        if context.target_agent_id == target_id
    )


def _single_snapshot_by_scope(session: SessionState, scope: str) -> object:
    return next(
        snapshot
        for snapshot in session.memory_snapshots.values()
        if snapshot.memory_scope == scope
    )


def _context_memory_ids(context: AgentContext) -> set[str]:
    return {memory.memory_id for memory in context.memory_snapshots}


def _memory_ids(memories: list[object]) -> set[str]:
    return {str(memory.memory_id) for memory in memories}


def _recent_memory_ids(context: AgentContext) -> set[str]:
    memory_ids: set[str] = set()
    for event in context.recent_events:
        if event.type in {
            EventType.MEMORY_CANDIDATE_CREATED,
            EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
        }:
            memory_id = event.payload.get("memory_id")
            if isinstance(memory_id, str):
                memory_ids.add(memory_id)
    return memory_ids
