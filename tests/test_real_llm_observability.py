from __future__ import annotations

from pathlib import Path

import httpx

from app.agents.gateway import AgentGateway
from app.agents.real_llm_agent import OpenAILLMAgent
from app.agents.real_llm_agent import _contract_repair_projection
from app.agents.llm_contract import (
    LLMAgentPolicyViolationError,
    validate_llm_agent_output,
)
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    DisclosureMode,
    LLMErrorSummary,
    LLMErrorType,
    LLMAgentContractInput,
    LLMAgentOutputContract,
    LLMContextLayerProjection,
    LLMDisclosureConstraint,
    LLMHardContextProjection,
    LLMSoftContextProjection,
    PlayerAction,
    SafeFactFragmentProjection,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


class FallbackAgent:
    @property
    def model_name(self) -> str:
        return "fallback-model"

    def generate(self, context: AgentContext) -> AgentIntent:
        return AgentIntent(
            speech=f"{context.target_agent_id} cannot answer through the LLM backend.",
            intent=AgentIntentType.REFUSE,
            proposed_actions=[],
            llm_error=LLMErrorSummary(
                backend="openai",
                error_type=LLMErrorType.TIMEOUT,
                error_message_sanitized="LLM provider request timed out",
                fallback_used=True,
            ),
        )


class RetryOnceClient:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls += 1
        request = httpx.Request("POST", url)
        if self.calls == 1:
            return httpx.Response(429, json={"error": "rate_limited"}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)


def test_openai_agent_retries_retryable_http_status(monkeypatch) -> None:
    monkeypatch.setenv("LLM_HTTP_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr("app.agents.real_llm_agent.time.sleep", lambda _: None)
    client = RetryOnceClient()
    agent = OpenAILLMAgent(api_key="test-key", client=client)

    payload = agent._post_json(  # noqa: SLF001
        "https://example.test/v1/responses",
        headers={},
        request_payload={"model": "test"},
    )

    assert payload == {"ok": True}
    assert client.calls == 2


def test_openai_agent_reads_timeout_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")

    agent = OpenAILLMAgent(api_key="test-key")

    assert agent._timeout_seconds == 45.0  # noqa: SLF001


def test_action_response_exposes_real_llm_fallback_summary() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=FallbackAgent()),
        runtime_tracer=RuntimeTracer.disabled(),
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

    assert response.llm_fallback_used is True
    assert response.llm_error is not None
    assert response.llm_error.error_type == LLMErrorType.TIMEOUT
    assert response.llm_error.error_message_sanitized == "LLM provider request timed out"


def test_runtime_trace_records_sanitized_llm_fallback_fields() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=FallbackAgent()),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)

    turn = runtime.action_service.agent_loop.run_turn(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )
    record = turn.trace
    rendered = RuntimeTracer.disabled().finish_turn(
        record,
        intent=turn.intent,
        director_allowed=True,
        director_reason_category=None,
        rule_rejections=[],
        new_events=[],
        phase_after=session.narrative.phase,
        public_speech=turn.intent.speech,
        public_speech_source="npc",
    )

    assert rendered["llm_fallback_used"] is True
    assert rendered["llm_error_type"] == "timeout"
    assert rendered["llm_error_message_sanitized"] == "LLM provider request timed out"
    assert rendered["schema_validation_errors"] == []


def test_openai_agent_missing_api_key_is_observable_configuration_error() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    context = runtime.action_service.agent_loop.build_context(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )

    intent = OpenAILLMAgent(api_key="").generate(context)

    assert intent.proposed_actions == []
    assert intent.llm_error is not None
    assert intent.llm_error.error_type == LLMErrorType.CONFIGURATION_ERROR
    assert intent.llm_error.fallback_used is True


def test_contract_projection_adds_missing_safe_fragment_disclosure_claim() -> None:
    contract_input = _safe_fragment_contract_input()

    projected = _contract_repair_projection(
        {
            "speech": "The bitter wine residue points to a sedative trace.",
            "intent": "answer",
            "emotional_shift": {},
            "proposed_actions": [],
            "memory_refs": [],
            "disclosure_claims": [],
        },
        contract_input=contract_input,
    )
    intent = validate_llm_agent_output(projected, contract_input)

    assert len(intent.disclosure_claims) == 1
    claim = intent.disclosure_claims[0]
    assert claim.world_info_id == "sedative_wine"
    assert claim.mode == DisclosureMode.PARTIAL
    assert claim.claim_refs == ["world_info:sedative_wine#wine_residue"]


def test_contract_projection_upgrades_low_mode_safe_fragment_claim() -> None:
    contract_input = _safe_fragment_contract_input(
        allowed_modes=[
            DisclosureMode.DEFLECT,
            DisclosureMode.HINT,
            DisclosureMode.PARTIAL,
        ]
    )

    projected = _contract_repair_projection(
        {
            "speech": "The bitter wine residue points to a sedative trace.",
            "intent": "answer",
            "emotional_shift": {},
            "proposed_actions": [],
            "memory_refs": [],
            "disclosure_claims": [
                {
                    "world_info_id": "sedative_wine",
                    "mode": "deflect",
                    "source_refs": [],
                    "claim_refs": [],
                }
            ],
        },
        contract_input=contract_input,
    )
    intent = validate_llm_agent_output(projected, contract_input)

    claim = intent.disclosure_claims[0]
    assert claim.mode == DisclosureMode.PARTIAL
    assert claim.claim_refs == ["world_info:sedative_wine#wine_residue"]


def test_contract_projection_adds_safe_fragment_ref_when_claim_refs_are_evidence_only() -> None:
    contract_input = _safe_fragment_contract_input(
        safe_fact_refs=["clue:bitter_wine"]
    )

    projected = _contract_repair_projection(
        {
            "speech": "The bitter wine residue points to a sedative trace.",
            "intent": "answer",
            "emotional_shift": {},
            "proposed_actions": [],
            "memory_refs": [],
            "disclosure_claims": [
                {
                    "world_info_id": "sedative_wine",
                    "mode": "partial",
                    "source_refs": ["clue:bitter_wine"],
                    "claim_refs": ["clue:bitter_wine"],
                }
            ],
        },
        contract_input=contract_input,
    )
    intent = validate_llm_agent_output(projected, contract_input)

    claim = intent.disclosure_claims[0]
    assert claim.source_refs == [
        "clue:bitter_wine",
        "world_info:sedative_wine#wine_residue",
    ]
    assert claim.claim_refs == [
        "clue:bitter_wine",
        "world_info:sedative_wine#wine_residue",
    ]


def test_contract_rejects_partial_safe_fragment_claim_with_only_evidence_refs() -> None:
    contract_input = _safe_fragment_contract_input(
        safe_fact_refs=["clue:bitter_wine"]
    )
    payload = {
        "speech": "The bitter wine residue points to a sedative trace.",
        "intent": "answer",
        "emotional_shift": {},
        "proposed_actions": [],
        "memory_refs": [],
        "disclosure_claims": [
            {
                "world_info_id": "sedative_wine",
                "mode": "partial",
                "source_refs": ["clue:bitter_wine"],
                "claim_refs": ["clue:bitter_wine"],
            }
        ],
    }

    try:
        validate_llm_agent_output(payload, contract_input)
    except LLMAgentPolicyViolationError as exc:
        assert "safe fragment" in str(exc)
    else:
        raise AssertionError("expected evidence-only refs to be rejected")


def test_contract_projection_infers_hint_only_chinese_safe_fragment() -> None:
    contract_input = _safe_fragment_contract_input(
        allowed_modes=[DisclosureMode.DEFLECT, DisclosureMode.HINT],
        world_info_id="timed_lock_modified",
        fragment_id="lock_has_delay_marks",
        fragment_ref="timed_lock_modified.safe_fragment:lock_has_delay_marks",
        aliases=["延迟落锁痕迹"],
        claim_patterns=["(延时|延迟).*落锁"],
        fragment_allowed_modes=[DisclosureMode.HINT],
    )

    projected = _contract_repair_projection(
        {
            "speech": "从事实层面说，你在看的是延迟落锁的痕迹。",
            "intent": "answer",
            "emotional_shift": {},
            "proposed_actions": [],
            "memory_refs": [],
            "disclosure_claims": [],
        },
        contract_input=contract_input,
    )
    intent = validate_llm_agent_output(projected, contract_input)

    claim = intent.disclosure_claims[0]
    assert claim.world_info_id == "timed_lock_modified"
    assert claim.mode == DisclosureMode.HINT
    assert claim.claim_refs == ["timed_lock_modified.safe_fragment:lock_has_delay_marks"]


def _safe_fragment_contract_input(
    *,
    allowed_modes: list[DisclosureMode] | None = None,
    world_info_id: str = "sedative_wine",
    fragment_id: str = "wine_residue",
    fragment_ref: str = "world_info:sedative_wine#wine_residue",
    aliases: list[str] | None = None,
    claim_patterns: list[str] | None = None,
    fragment_allowed_modes: list[DisclosureMode] | None = None,
    safe_fact_refs: list[str] | None = None,
) -> LLMAgentContractInput:
    allowed_modes = allowed_modes or [DisclosureMode.HINT, DisclosureMode.PARTIAL]
    aliases = aliases or ["bitter wine residue"]
    claim_patterns = claim_patterns or ["sedative trace"]
    fragment_allowed_modes = fragment_allowed_modes or [
        DisclosureMode.HINT,
        DisclosureMode.PARTIAL,
    ]
    context = AgentContext(
        case_id="case",
        session_id="session",
        target_agent_id="lin_qichi",
        current_phase="investigation",
        player_action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id="lin_qichi",
            clue_id="bitter_wine",
            text="Explain the bitter wine.",
        ),
    )
    return LLMAgentContractInput(
        agent_context=context,
        disclosure_constraints=[
            LLMDisclosureConstraint(
                item_id=world_info_id,
                item_kind="world_info",
                allowed_modes=allowed_modes,
                forbidden_modes=[DisclosureMode.FULL],
                safe_fact_refs=safe_fact_refs or [fragment_ref],
                safe_fragments=[
                    SafeFactFragmentProjection(
                        world_info_id=world_info_id,
                        fragment_id=fragment_id,
                        ref=fragment_ref,
                        summary=(
                            "Player has evidence that the bitter wine residue "
                            "supports a sedative trace."
                        ),
                        aliases=aliases,
                        claim_patterns=claim_patterns,
                        allowed_modes=fragment_allowed_modes,
                        source_refs=[f"player_knowledge.{world_info_id}"],
                    )
                ],
            )
        ],
        output_contract=LLMAgentOutputContract(
            allowed_intents=[AgentIntentType.ANSWER],
            allowed_disclosure_modes=allowed_modes,
        ),
        context_layers=LLMContextLayerProjection(
            hard=LLMHardContextProjection(current_phase="investigation"),
            soft=LLMSoftContextProjection(),
        ),
    )
