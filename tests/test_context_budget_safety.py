from __future__ import annotations

import json
from pathlib import Path

from app.agents.gateway import AgentGateway
from app.agents.llm_contract import build_llm_agent_input
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    LLMAgentContractInput,
    LLMErrorType,
    PlayerAction,
    ProposedActionType,
    RelationshipChangeAction,
    SubjectType,
)
from app.runtime.budget import ContextBudgetManager
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


class _ExplodingActionAgent:
    def __init__(self) -> None:
        self.generate_calls = 0

    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        self.generate_calls += 1
        return AgentIntent(
            speech="This should not be generated when hard context is over limit.",
            intent=AgentIntentType.ANSWER,
            emotional_shift={},
            proposed_actions=[
                RelationshipChangeAction(
                    type=ProposedActionType.RELATIONSHIP_CHANGE,
                    source_id=context.target_agent_id,
                    target_id="player",
                    deltas={"trust": 0.5},
                )
            ],
            memory_refs=[],
            disclosure_claims=[],
        )


def test_context_budget_compression_is_soft_only_and_reports_hard_tokens() -> None:
    manager = ContextBudgetManager(
        context_limit_tokens=100,
        compression_threshold_ratio=0.5,
    )

    result = manager.apply(
        prompt_text="hard:" + ("h" * 120) + "\nsoft:" + ("s" * 400),
        hard_context_text="hard:" + ("h" * 120),
        soft_context_text="soft:" + ("s" * 400),
        memory_ids=["memory.hard.ref"],
        recent_event_ids=["event.soft.1", "event.soft.2"],
    )

    assert result.compression_used is True
    assert result.compression_scope == "soft_context"
    assert result.compressed_layers == ["soft_context"]
    assert result.hard_context_tokens_estimated > 0
    assert result.soft_context_tokens_estimated > result.hard_context_tokens_estimated
    assert result.compressed_history is not None
    assert result.compressed_history.important_memory_ids == ["memory.hard.ref"]
    assert result.compressed_history.important_event_ids == [
        "event.soft.1",
        "event.soft.2",
    ]


def test_context_budget_reports_hard_context_over_limit_without_soft_compression() -> None:
    manager = ContextBudgetManager(
        context_limit_tokens=20,
        compression_threshold_ratio=0.5,
    )

    result = manager.apply(
        prompt_text="hard:" + ("h" * 120) + "\nsoft:" + ("s" * 20),
        hard_context_text="hard:" + ("h" * 120),
        soft_context_text="soft:" + ("s" * 20),
        memory_ids=["memory.hard.ref"],
        recent_event_ids=["event.soft.1"],
    )

    assert result.hard_context_over_limit is True
    assert result.fallback_reason == "hard_context_over_limit"
    assert result.compression_used is False
    assert result.compression_scope == "hard_context_over_limit"
    assert result.compressed_layers == []
    assert result.compressed_history is None


def test_context_budget_hard_over_limit_wins_even_when_soft_context_is_larger() -> None:
    manager = ContextBudgetManager(
        context_limit_tokens=20,
        compression_threshold_ratio=0.5,
    )

    result = manager.apply(
        prompt_text="hard:" + ("h" * 120) + "\nsoft:" + ("s" * 800),
        hard_context_text="hard:" + ("h" * 120),
        soft_context_text="soft:" + ("s" * 800),
        memory_ids=["memory.hard.ref"],
        recent_event_ids=["event.soft.1"],
    )

    assert result.hard_context_over_limit is True
    assert result.soft_context_tokens_estimated > result.hard_context_tokens_estimated
    assert result.fallback_reason == "hard_context_over_limit"
    assert result.compression_used is False
    assert result.compression_scope == "hard_context_over_limit"
    assert result.compressed_layers == []
    assert result.compressed_history is None


def test_llm_contract_has_explicit_hard_soft_context_projection_under_budget_pressure() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer.disabled(),
        context_limit_tokens=1,
    )
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    action = PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id="butler",
        subject_type=SubjectType.CLUE,
        subject_id="scratched_drawer",
        text="What about the drawer scratches?",
    )
    context = runtime.agent_loop.build_context(case=case, session=session, action=action)
    turn_plan = runtime.agent_loop.plan_turn(
        case=case,
        session=session,
        action=action,
        context=context,
    )

    contract = build_llm_agent_input(context, turn_plan=turn_plan)
    layers = contract.context_layers

    assert layers.compression_policy == "soft_only"
    assert layers.hard.current_phase == session.narrative.phase
    assert "scratched_drawer" in layers.hard.discovered_clues
    assert "player_knowledge.desk_forced_open" in layers.hard.player_knowledge_ids
    assert any(
        ref.startswith("desk_forced_open.safe_fragment:")
        for ref in layers.hard.director_safe_fragment_refs
    )
    assert "true_killer" in layers.hard.blocked_fact_ids
    assert layers.hard.selected_npc_skill_ids == ["butler_drawer_pressure_deflection"]
    assert layers.hard.selected_memory_ids == []
    assert set(layers.hard.output_contract_allowed_intents) == {
        "answer",
        "conceal",
        "probe",
    }
    assert layers.soft.recent_event_ids
    assert layers.soft.compressed_history_present is False


def test_llm_contract_hard_context_includes_selected_memory_refs() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    action = PlayerAction(
        type=ActionType.TALK,
        target_id="butler",
        text="What about the drawer scratches?",
    )
    context = runtime.agent_loop.build_context(case=case, session=session, action=action)

    contract = build_llm_agent_input(context)

    assert contract.context_layers.hard.selected_memory_ids == [
        "memory.player.clue_discovered.scratched_drawer"
    ]
    assert contract.context_layers.soft.memory_description_ids == [
        "memory.player.clue_discovered.scratched_drawer"
    ]


def test_agent_trace_records_budget_compression_only_on_soft_context(tmp_path: Path) -> None:
    case = CaseLoader().load(CASE_DIR)
    jsonl_path = tmp_path / "trace.jsonl"
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer(
            jsonl_path=jsonl_path,
            log_path=tmp_path / "trace.log",
        ),
        context_limit_tokens=1000,
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
    budget = record["context_layer_budget"]
    assert budget["compression_scope"] == "soft_context"
    assert budget["compressed_layers"] == ["soft_context"]
    assert budget["hard_context_tokens_estimated"] > 0
    assert budget["soft_context_tokens_estimated"] > 0
    assert budget["hard_context_preserved"] is True
    assert budget["soft_recent_event_count"] > 0
    assert budget["selected_memory_count"] == 1


def test_agent_loop_blocks_generation_when_hard_context_exceeds_budget(
    tmp_path: Path,
) -> None:
    case = CaseLoader().load(CASE_DIR)
    jsonl_path = tmp_path / "trace.jsonl"
    agent = _ExplodingActionAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(backend="llm_stub", llm_stub=agent),
        runtime_tracer=RuntimeTracer(
            jsonl_path=jsonl_path,
            log_path=tmp_path / "trace.log",
        ),
        context_limit_tokens=1,
    )
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )

    event_types = [event.type.value for event in response.new_events]
    record = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    budget = record["context_layer_budget"]

    assert agent.generate_calls == 0
    assert response.llm_fallback_used is True
    assert response.llm_error is not None
    assert response.llm_error.error_type == LLMErrorType.CONTEXT_OVER_LIMIT
    assert response.llm_error.error_message_sanitized == "hard_context_over_limit"
    assert "relationship.changed" not in event_types
    assert "rule.rejected" not in event_types
    assert "npc.replied" in event_types
    assert record["llm_fallback_used"] is True
    assert record["llm_error_type"] == "context_over_limit"
    assert budget["hard_context_over_limit"] is True
    assert budget["fallback_reason"] == "hard_context_over_limit"
    assert budget["compression_scope"] == "hard_context_over_limit"
    assert budget["compressed_layers"] == []
    assert budget["hard_context_preserved"] is False
