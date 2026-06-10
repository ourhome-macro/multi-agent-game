from __future__ import annotations

import json
from pathlib import Path

from app.agents.gateway import AgentGateway
from app.agents.memory import MemoryRetriever
from app.agents.tools.runtime import ToolRuntime
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, AgentContext, AgentIntent, AgentIntentType, PlayerAction
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"
EMPTY_CAPSULES = "empty_capsules"
JIANG_ASK_MEMORY = f"memory.player.asked_about.{JIANG}.clue.{EMPTY_CAPSULES}"
SHEN_ASK_MEMORY = f"memory.player.asked_about.{SHEN}.clue.{EMPTY_CAPSULES}"
JIANG_PRESENT_MEMORY = f"memory.player.presented_clue.{JIANG}.{EMPTY_CAPSULES}"


class RecordingAgent:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    def generate(self, context: AgentContext) -> AgentIntent:
        self.contexts.append(context)
        return AgentIntent(
            speech="Recorded.",
            intent=AgentIntentType.ANSWER,
            proposed_actions=[],
        )


def test_presented_clue_memory_candidate_records_owner_and_visibility() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            text="把空胶囊给江医生看",
        ),
    )

    candidate = session.memory_candidates[JIANG_PRESENT_MEMORY]
    assert candidate.owner_character_id == JIANG
    assert candidate.visible_to_character_ids == [JIANG]


def test_memory_snapshot_preserves_owner_and_visibility() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    snapshot = session.memory_snapshots[JIANG_PRESENT_MEMORY]

    assert snapshot.owner_character_id == JIANG
    assert snapshot.visible_to_character_ids == [JIANG]


def test_memory_retriever_returns_presented_clue_memory_to_owner_npc() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    memories = MemoryRetriever().retrieve(
        case=case,
        session=session,
        action=_talk_action(JIANG, "空胶囊"),
    )

    assert JIANG_PRESENT_MEMORY in _memory_ids(memories)


def test_memory_retriever_hides_presented_clue_memory_from_other_npc() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    memories = MemoryRetriever().retrieve(
        case=case,
        session=session,
        action=_talk_action(SHEN, "空胶囊"),
    )

    assert JIANG_PRESENT_MEMORY not in _memory_ids(memories)


def test_director_retriever_can_see_presented_clue_memory_for_audit() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    memories = MemoryRetriever().retrieve_for_director(
        case=case,
        session=session,
        action=_talk_action(SHEN, "空胶囊"),
    )

    assert JIANG_PRESENT_MEMORY in _memory_ids(memories)


def test_asked_about_memory_candidate_records_target_owner() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)

    _ask_jiang_about_empty_capsules(runtime, session)

    candidate = session.memory_candidates[JIANG_ASK_MEMORY]
    assert candidate.owner_character_id == JIANG
    assert candidate.visible_to_character_ids == [JIANG]


def test_second_npc_agent_context_does_not_receive_first_npc_ask_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    agent = RecordingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _ask_jiang_about_empty_capsules(runtime, session)

    runtime.action_service.handle(
        session=session,
        action=_ask_action(SHEN, "我问沈照夜关于空胶囊的事情"),
    )

    shen_context = _last_context_for(agent, SHEN)
    assert JIANG_ASK_MEMORY not in _context_memory_ids(shen_context)


def test_first_npc_agent_context_does_not_receive_second_npc_ask_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    agent = RecordingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    runtime.action_service.handle(session=session, action=_ask_action(SHEN, "问沈照夜空胶囊"))

    runtime.action_service.handle(
        session=session,
        action=_ask_action(JIANG, "我再问江医生空胶囊"),
    )

    jiang_context = _last_context_for(agent, JIANG)
    assert SHEN_ASK_MEMORY not in _context_memory_ids(jiang_context)


def test_owner_npc_agent_context_receives_own_ask_memory_on_later_turn() -> None:
    case = CaseLoader().load(CASE_DIR)
    agent = RecordingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _ask_jiang_about_empty_capsules(runtime, session)

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="继续说空胶囊"),
    )

    jiang_context = _last_context_for(agent, JIANG)
    assert JIANG_ASK_MEMORY in _context_memory_ids(jiang_context)


def test_clue_discovery_memory_remains_visible_to_all_npcs_as_player_knowledge() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)

    jiang_memories = MemoryRetriever().retrieve(
        case=case,
        session=session,
        action=_talk_action(JIANG, EMPTY_CAPSULES),
    )
    shen_memories = MemoryRetriever().retrieve(
        case=case,
        session=session,
        action=_talk_action(SHEN, EMPTY_CAPSULES),
    )

    clue_memory = f"memory.player.clue_discovered.{EMPTY_CAPSULES}"
    assert clue_memory in _memory_ids(jiang_memories)
    assert clue_memory in _memory_ids(shen_memories)


def test_tool_runtime_search_memory_counts_only_target_visible_memories() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    jiang_result = ToolRuntime().call(
        "search_memory",
        case=case,
        session=session,
        action=_talk_action(JIANG, EMPTY_CAPSULES),
    )
    shen_result = ToolRuntime().call(
        "search_memory",
        case=case,
        session=session,
        action=_talk_action(SHEN, EMPTY_CAPSULES),
    )

    assert int(jiang_result.summary["result_count"]) > int(shen_result.summary["result_count"])


def test_agent_trace_memory_ids_exclude_other_npc_private_memory(tmp_path: Path) -> None:
    case = CaseLoader().load(CASE_DIR)
    jsonl_path = tmp_path / "trace.jsonl"
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer(jsonl_path=jsonl_path, log_path=tmp_path / "trace.log"),
    )
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _ask_jiang_about_empty_capsules(runtime, session)

    runtime.action_service.handle(session=session, action=_ask_action(SHEN, "问沈照夜空胶囊"))

    records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    shen_record = next(record for record in records if record["target_agent_id"] == SHEN)
    assert JIANG_ASK_MEMORY not in shen_record["memory_ids_used"]


def test_replay_preserves_memory_owner_and_visibility() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    replayed = replay_events(case, session.events)

    assert replayed.memory_candidates[JIANG_PRESENT_MEMORY].owner_character_id == JIANG
    assert replayed.memory_candidates[JIANG_PRESENT_MEMORY].visible_to_character_ids == [JIANG]
    assert replayed.memory_snapshots[JIANG_PRESENT_MEMORY].owner_character_id == JIANG
    assert replayed.memory_snapshots[JIANG_PRESENT_MEMORY].visible_to_character_ids == [JIANG]


def _discover_empty_capsules(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="medicine_box"),
    )


def _present_empty_capsules_to_jiang(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            text="把空胶囊给江医生看",
        ),
    )


def _ask_jiang_about_empty_capsules(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=_ask_action(JIANG, "我问江医生关于空胶囊的事情"),
    )


def _ask_action(target_id: str, text: str) -> PlayerAction:
    return PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id=target_id,
        subject_type="clue",
        subject_id=EMPTY_CAPSULES,
        text=text,
    )


def _talk_action(target_id: str, text: str) -> PlayerAction:
    return PlayerAction(type=ActionType.TALK, target_id=target_id, text=text)


def _memory_ids(memories: list[object]) -> set[str]:
    return {str(memory.memory_id) for memory in memories}


def _context_memory_ids(context: AgentContext) -> set[str]:
    return {memory.memory_id for memory in context.memory_snapshots}


def _last_context_for(agent: RecordingAgent, target_id: str) -> AgentContext:
    return next(
        context
        for context in reversed(agent.contexts)
        if context.target_agent_id == target_id
    )
