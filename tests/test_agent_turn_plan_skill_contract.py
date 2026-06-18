from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.llm_contract import (
    LLMAgentPolicyViolationError,
    build_llm_agent_input,
    validate_llm_agent_output,
)
from app.agents.gateway import AgentGateway
from app.agents.real_llm_agent import _agent_intent_json_schema
from app.agents.turn_plan import build_agent_turn_plan
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    DisclosureMode,
    PlayerAction,
    ProposedActionType,
    RelationshipChangeAction,
    SubjectType,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
SKILL_ID = "butler_drawer_pressure_deflection"
SAFE_FRAGMENT_REF = "desk_forced_open.safe_fragment:drawer_was_forced"


def test_turn_plan_unifies_memory_skill_and_output_contract() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    action = _ask_about_drawer()

    plan = runtime.agent_loop.plan_turn(
        case=case,
        session=session,
        action=action,
    )

    assert plan.memory_retrieval_plan.skill_id == "ask_about_clue"
    assert plan.selected_skill_ids == [SKILL_ID]
    assert plan.output_contract.allowed_intents == ["answer", "conceal", "probe"]
    assert plan.output_contract.allowed_proposed_action_types == ["relationship.change"]
    assert set(plan.output_contract.allowed_rhetoric_tactics) == {
        "answer_adjacent_truth",
        "shift_focus",
        "qualify_certainty",
    }
    assert plan.output_contract.max_relationship_delta == {
        "suspicion": 0.2,
        "trust": 0.1,
    }


def test_llm_contract_uses_selected_skill_allowed_intents() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=_ask_about_drawer(),
    )
    contract = build_llm_agent_input(context)

    assert contract.output_contract.allowed_intents == ["answer", "conceal", "probe"]
    assert _valid_skill_payload()["intent"] == "answer"
    validate_llm_agent_output(_valid_skill_payload(), contract)

    with pytest.raises(LLMAgentPolicyViolationError, match="intent"):
        payload = _valid_skill_payload(intent="lie")
        validate_llm_agent_output(payload, contract)


def test_llm_contract_rejects_skill_forbidden_tactic() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    contract = build_llm_agent_input(
        runtime.agent_loop.build_context(
            case=case,
            session=session,
            action=_ask_about_drawer(),
        )
    )

    with pytest.raises(LLMAgentPolicyViolationError, match="tactic"):
        payload = _valid_skill_payload(tactic="emotional_screen")
        validate_llm_agent_output(payload, contract)


def test_llm_contract_rejects_skill_forbidden_proposed_action_type() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    contract = build_llm_agent_input(
        runtime.agent_loop.build_context(
            case=case,
            session=session,
            action=_ask_about_drawer(),
        )
    )

    with pytest.raises(LLMAgentPolicyViolationError, match="proposed action"):
        payload = _valid_skill_payload(
            proposed_actions=[
                {"type": "clue.discover", "clue_id": "hidden_letter"},
            ],
        )
        validate_llm_agent_output(payload, contract)


def test_llm_contract_rejects_relationship_delta_above_skill_cap() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    contract = build_llm_agent_input(
        runtime.agent_loop.build_context(
            case=case,
            session=session,
            action=_ask_about_drawer(),
        )
    )

    with pytest.raises(LLMAgentPolicyViolationError, match="relationship delta"):
        payload = _valid_skill_payload(
            proposed_actions=[
                {
                    "type": "relationship.change",
                    "source_id": "butler",
                    "target_id": "player",
                    "deltas": {
                        "trust": 0.11,
                        "suspicion": 0.2,
                        "fear": 0.0,
                        "intimacy": 0.0,
                        "hostility": 0.0,
                    },
                },
            ],
        )
        validate_llm_agent_output(payload, contract)


def test_llm_contract_allows_relationship_delta_at_skill_cap() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    contract = build_llm_agent_input(
        runtime.agent_loop.build_context(
            case=case,
            session=session,
            action=_ask_about_drawer(),
        )
    )

    intent = validate_llm_agent_output(
        _valid_skill_payload(
            proposed_actions=[
                {
                    "type": "relationship.change",
                    "source_id": "butler",
                    "target_id": "player",
                    "deltas": {
                        "trust": 0.1,
                        "suspicion": 0.2,
                        "fear": 0.0,
                        "intimacy": 0.0,
                        "hostility": 0.0,
                    },
                },
            ],
        ),
        contract,
    )

    assert intent.proposed_actions[0].type == "relationship.change"


def test_no_selected_skill_blocks_active_proposed_actions_by_default() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    action = PlayerAction(
        type=ActionType.TALK,
        target_id="butler",
        text="Just chatting.",
    )
    context = runtime.agent_loop.build_context(case=case, session=session, action=action)
    contract = build_llm_agent_input(context)

    assert context.npc_skill_projections == []
    assert contract.output_contract.allowed_proposed_action_types == []
    with pytest.raises(LLMAgentPolicyViolationError, match="proposed action"):
        validate_llm_agent_output(
            _valid_payload_without_disclosure(
                proposed_actions=[
                    {
                        "type": "relationship.change",
                        "source_id": "butler",
                        "target_id": "player",
                        "deltas": {
                            "trust": 0.1,
                            "suspicion": 0.0,
                            "fear": 0.0,
                            "intimacy": 0.0,
                            "hostility": 0.0,
                        },
                    }
                ],
            ),
            contract,
        )


def test_no_selected_skill_rejects_full_disclosure_claim_by_default() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    action = PlayerAction(
        type=ActionType.TALK,
        target_id="butler",
        text="Just chatting.",
    )
    context = runtime.agent_loop.build_context(case=case, session=session, action=action)
    contract = build_llm_agent_input(context)

    assert context.npc_skill_projections == []
    with pytest.raises(LLMAgentPolicyViolationError, match="disclosure mode"):
        validate_llm_agent_output(
            {
                "speech": "The drawer was forced open and that is the full truth.",
                "intent": "answer",
                "emotional_shift": {},
                "proposed_actions": [],
                "memory_refs": [],
                "disclosure_claims": [
                    {
                        "world_info_id": "desk_forced_open",
                        "mode": DisclosureMode.FULL.value,
                        "tactic": "answer_adjacent_truth",
                        "source_refs": [],
                        "claim_refs": [],
                    }
                ],
            },
            contract,
        )


def test_explicit_turn_plan_can_be_passed_to_llm_contract() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    action = _ask_about_drawer()
    context = runtime.agent_loop.build_context(case=case, session=session, action=action)
    turn_plan = build_agent_turn_plan(
        case=case,
        session=session,
        action=action,
        context=context,
    )

    contract = build_llm_agent_input(context, turn_plan=turn_plan)

    assert contract.turn_plan_id == turn_plan.plan_id
    assert contract.output_contract.allowed_intents == ["answer", "conceal", "probe"]


def test_real_llm_json_schema_uses_skill_allowed_proposed_actions() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    contract = build_llm_agent_input(
        runtime.agent_loop.build_context(
            case=case,
            session=session,
            action=_ask_about_drawer(),
        )
    )

    schema = _agent_intent_json_schema(contract)
    proposed_action_items = schema["properties"]["proposed_actions"]["items"]
    serialized = str(proposed_action_items)

    assert "relationship.change" in serialized
    assert "clue.discover" not in serialized


def test_real_llm_json_schema_uses_skill_relationship_delta_caps() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    contract = build_llm_agent_input(
        runtime.agent_loop.build_context(
            case=case,
            session=session,
            action=_ask_about_drawer(),
        )
    )

    schema = _agent_intent_json_schema(contract)
    deltas_schema = schema["properties"]["proposed_actions"]["items"]["properties"][
        "deltas"
    ]["properties"]

    assert deltas_schema["trust"]["minimum"] == -0.1
    assert deltas_schema["trust"]["maximum"] == 0.1
    assert deltas_schema["suspicion"]["minimum"] == -0.2
    assert deltas_schema["suspicion"]["maximum"] == 0.2
    assert deltas_schema["fear"]["minimum"] == 0
    assert deltas_schema["fear"]["maximum"] == 0


def test_runtime_degrades_skill_contract_violation_without_applying_side_effects() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=_OverCapSkillAgent()),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=_ask_about_drawer(),
    )

    assert response.accepted is True
    assert response.llm_fallback_used is True
    assert response.llm_error is not None
    assert response.llm_error.error_type == "policy_violation"
    assert not any(
        event.type == "relationship.changed"
        for event in response.new_events
    )


def test_runtime_degrades_schema_contract_violation_without_applying_side_effects() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=_MalformedSchemaAgent()),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=_ask_about_drawer(),
    )

    assert response.accepted is True
    assert response.llm_fallback_used is True
    assert response.llm_error is not None
    assert response.llm_error.error_type == "schema_error"
    assert not any(
        event.type == "relationship.changed"
        for event in response.new_events
    )


def test_runtime_trace_records_turn_plan_and_output_contract_summary(
    tmp_path: Path,
) -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer(
            jsonl_path=tmp_path / "trace.jsonl",
            log_path=tmp_path / "trace.log",
        ),
    )
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    runtime.action_service.handle(session=session, action=_ask_about_drawer())

    record = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8"))
    summary = record["output_contract_summary"]

    assert record["turn_plan_id"].startswith("agent_turn_plan.")
    assert summary["allowed_intents"] == ["answer", "conceal", "probe"]
    assert summary["allowed_proposed_action_types"] == ["relationship.change"]
    assert set(summary["allowed_rhetoric_tactics"]) == {
        "answer_adjacent_truth",
        "shift_focus",
        "qualify_certainty",
    }
    assert summary["max_relationship_delta"] == {
        "suspicion": 0.2,
        "trust": 0.1,
    }


class _OverCapSkillAgent:
    def generate(self, context: AgentContext) -> AgentIntent:
        return AgentIntent(
            speech="The drawer pressure changes how I read you.",
            intent=AgentIntentType.PROBE,
            proposed_actions=[
                RelationshipChangeAction(
                    type=ProposedActionType.RELATIONSHIP_CHANGE,
                    source_id=context.target_agent_id,
                    target_id="player",
                    deltas={"trust": 0.11, "suspicion": 0.2},
                )
            ],
        )


class _MalformedSchemaAgent:
    def generate(self, context: AgentContext) -> object:
        _ = context
        return _MalformedSchemaIntent()


class _MalformedSchemaIntent:
    speech = "Malformed payload should not reach rules."
    llm_error = None

    def model_dump(self, **_: object) -> dict[str, object]:
        return {
            "intent": "answer",
            "emotional_shift": {},
            "proposed_actions": [
                {
                    "type": "relationship.change",
                    "source_id": "butler",
                    "target_id": "player",
                    "deltas": {
                        "trust": 0.1,
                        "suspicion": 0.0,
                        "fear": 0.0,
                        "intimacy": 0.0,
                        "hostility": 0.0,
                    },
                }
            ],
            "memory_refs": [],
            "disclosure_claims": [],
        }


def _runtime_with_drawer_unlocked() -> tuple[object, object, object]:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    return case, runtime, session


def _ask_about_drawer() -> PlayerAction:
    return PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id="butler",
        subject_type=SubjectType.CLUE,
        subject_id="scratched_drawer",
        text="What about the drawer scratches?",
    )


def _valid_skill_payload(
    *,
    intent: str = "answer",
    tactic: str = "answer_adjacent_truth",
    proposed_actions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "speech": "There were signs the drawer was forced, but I cannot say more.",
        "intent": intent,
        "emotional_shift": {},
        "proposed_actions": proposed_actions or [],
        "memory_refs": [],
        "disclosure_claims": [
            {
                "world_info_id": "desk_forced_open",
                "mode": DisclosureMode.PARTIAL.value,
                "tactic": tactic,
                "source_refs": [SAFE_FRAGMENT_REF],
                "claim_refs": [SAFE_FRAGMENT_REF],
            }
        ],
    }


def _valid_payload_without_disclosure(
    *,
    proposed_actions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "speech": "I cannot move that forward right now.",
        "intent": "refuse",
        "emotional_shift": {},
        "proposed_actions": proposed_actions or [],
        "memory_refs": [],
        "disclosure_claims": [],
    }
