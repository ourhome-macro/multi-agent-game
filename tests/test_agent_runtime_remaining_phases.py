from __future__ import annotations

import json
from pathlib import Path

from app.agents.gateway import AgentGateway
from app.agents.memory import MemoryRetriever
from app.agents.orchestrator import AgentOrchestrator
from app.agents.tools.runtime import ToolRuntime
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, AgentContext, AgentIntent, AgentIntentType, PlayerAction
from app.runtime.budget import ContextBudgetManager
from app.runtime.persistence import JsonlEventStore
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


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


def test_memory_retriever_returns_relevant_visible_memory_only() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="portrait"),
    )

    memories = MemoryRetriever(max_results=1).retrieve(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="What about the drawer scratches?",
        ),
    )

    assert [memory.memory_id for memory in memories] == [
        "memory.player.clue_discovered.scratched_drawer"
    ]


def test_context_budget_manager_compresses_over_80_percent_with_source_ids() -> None:
    manager = ContextBudgetManager(
        context_limit_tokens=100,
        compression_threshold_ratio=0.8,
    )

    result = manager.apply(
        prompt_text="x" * 400,
        memory_ids=["memory.a", "memory.b"],
        recent_event_ids=["event.a", "event.b"],
    )

    assert result.context_budget_ratio > 0.8
    assert result.compression_used is True
    assert result.compressed_history is not None
    assert result.compressed_history.important_memory_ids == ["memory.a", "memory.b"]
    assert result.compressed_history.important_event_ids == ["event.a", "event.b"]


def test_agent_loop_uses_memory_retriever_and_budget_in_trace(tmp_path: Path) -> None:
    case = CaseLoader().load(CASE_DIR)
    jsonl_path = tmp_path / "trace.jsonl"
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer(jsonl_path=jsonl_path, log_path=tmp_path / "trace.log"),
        context_limit_tokens=100,
    )
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="What about the drawer scratches?",
        ),
    )

    record = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["memory_ids_used"] == ["memory.player.clue_discovered.scratched_drawer"]
    assert record["context_budget_ratio"] > 0.8
    assert record["compression_used"] is True


def test_agent_loop_passes_retrieved_memory_context_to_gateway() -> None:
    case = CaseLoader().load(CASE_DIR)
    agent = RecordingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="portrait"),
    )

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="What about the drawer scratches?",
        ),
    )

    assert len(agent.contexts) == 1
    assert [memory.memory_id for memory in agent.contexts[0].memory_snapshots] == [
        "memory.player.clue_discovered.scratched_drawer"
    ]


def test_prompt_builder_receives_compressed_history_projection() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id="butler", text="drawer"),
    )
    budget = ContextBudgetManager(context_limit_tokens=1).apply(
        prompt_text="x" * 100,
        memory_ids=["memory.player.clue_discovered.scratched_drawer"],
        recent_event_ids=[event.id for event in context.recent_events],
    )

    bundle = runtime.agent_loop.prompt_builder.build(
        context.model_copy(
            update={
                "compressed_history": (
                    budget.compressed_history.to_context()
                    if budget.compressed_history is not None
                    else None
                )
            }
        )
    )
    assert "compressed_history" in bundle.agent_prompt
    assert "memory.player.clue_discovered.scratched_drawer" in bundle.agent_prompt
    assert "source_event_ids" not in bundle.agent_prompt


def test_agent_loop_trace_includes_safe_tool_summaries(tmp_path: Path) -> None:
    case = CaseLoader().load(CASE_DIR)
    jsonl_path = tmp_path / "trace.jsonl"
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer(jsonl_path=jsonl_path, log_path=tmp_path / "trace.log"),
    )
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="What about the drawer scratches?",
        ),
    )

    record = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["tool_calls"] == [
        {
            "tool_name": "search_memory",
            "status": "ok",
            "duration_ms": record["tool_calls"][0]["duration_ms"],
            "error_category": None,
            "result_count": 1,
        }
    ]
    assert set(record["tool_calls"][0]) == {
        "tool_name",
        "status",
        "duration_ms",
        "error_category",
        "result_count",
    }


def test_tool_runtime_returns_safe_summary_and_trace_sanitizes_payload() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    tool_runtime = ToolRuntime()

    result = tool_runtime.call(
        "search_memory",
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id="butler", text="drawer"),
    )

    assert result.summary["tool_name"] == "search_memory"
    assert set(result.summary) == {
        "tool_name",
        "status",
        "duration_ms",
        "error_category",
        "result_count",
    }
    assert "result" not in result.summary
    assert "args" not in result.summary


def test_orchestrator_keeps_secondary_agent_context_isolated() -> None:
    case = CaseLoader().load(CASE_DIR)
    primary = RecordingAgent()
    secondary = RecordingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=primary),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)

    result = AgentOrchestrator(
        primary_loop=runtime.agent_loop,
        secondary_gateway=AgentGateway(mock_agent=secondary),
        max_secondary_agents=1,
    ).run_secondary_reactions(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id="butler", text="Speak."),
    )

    assert [turn.context.target_agent_id for turn in result.secondary_turns] == ["niece"]
    serialized_context = result.secondary_turns[0].context.model_dump_json()
    butler_private_values = _private_values_for_character(case, "butler")
    for value in butler_private_values:
        assert value not in serialized_context


def test_jsonl_event_store_persists_events_and_replay_rebuilds_state(tmp_path: Path) -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    store = JsonlEventStore(tmp_path / "events.jsonl")

    store.save(session.events)
    loaded_events = store.load()
    replayed = replay_events(case, loaded_events)

    assert len(loaded_events) == len(session.events)
    assert replayed.discovered_clues == session.discovered_clues
    assert replayed.player_knowledge == session.player_knowledge


def _private_values_for_character(case: object, character_id: str) -> list[str]:
    character = next(item for item in case.characters if item.id == character_id)
    values: list[str] = []
    values.extend(goal.summary for goal in character.private.goals)
    values.extend(secret.summary for secret in character.private.secrets)
    values.extend(knowledge.summary for knowledge in character.private.knowledge)
    return values
