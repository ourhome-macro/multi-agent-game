from __future__ import annotations

import json
from pathlib import Path

from app.agents.gateway import AgentGateway
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    LLMAgentContractInput,
    PlayerAction,
)
from app.runtime.budget import (
    ContextBudgetManager,
    ProviderModelTokenEstimator,
    TokenBudgetProfile,
    TokenEstimate,
    estimate_tokens,
    resolve_token_budget_profile,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


class CountingEstimator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def estimate(
        self,
        text: str,
        *,
        profile: TokenBudgetProfile | None = None,
    ) -> TokenEstimate:
        self.calls.append(text)
        return TokenEstimate(tokens=len(text.split()), method="test_words")


class ProfileRecordingEstimator:
    def __init__(self) -> None:
        self.profiles: list[TokenBudgetProfile | None] = []

    def estimate(
        self,
        text: str,
        *,
        profile: TokenBudgetProfile | None = None,
    ) -> TokenEstimate:
        self.profiles.append(profile)
        return TokenEstimate(tokens=len(text), method="profile_recording")


class ProviderAwareAgent:
    provider_name = "deepseek"
    model_name = "deepseek-v4-flash"

    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        del context, contract_input
        return AgentIntent(
            speech="Profile-aware response.",
            intent=AgentIntentType.ANSWER,
            proposed_actions=[],
        )


def test_resolve_token_budget_profile_uses_model_profile_with_explicit_overrides() -> None:
    profile = resolve_token_budget_profile(
        provider="DeepSeek",
        model="DEEPSEEK-V4-FLASH",
        profiles={
            (
                "deepseek",
                "deepseek-v4-flash",
            ): TokenBudgetProfile(
                provider="deepseek",
                model="deepseek-v4-flash",
                context_limit_tokens=32000,
                reserved_output_tokens=2048,
                safety_margin_tokens=1024,
                conservative_multiplier=1.15,
            )
        },
        reserved_output_tokens=4096,
    )

    assert profile.provider == "deepseek"
    assert profile.model == "deepseek-v4-flash"
    assert profile.context_limit_tokens == 32000
    assert profile.reserved_output_tokens == 4096
    assert profile.safety_margin_tokens == 1024
    assert profile.available_input_tokens == 26880
    assert profile.conservative_multiplier == 1.15


def test_resolve_token_budget_profile_uses_provider_default_for_unknown_model() -> None:
    profile = resolve_token_budget_profile(provider="openai", model="custom-model")

    assert profile.provider == "openai"
    assert profile.model == "custom-model"
    assert profile.context_limit_tokens == 8000
    assert profile.reserved_output_tokens == 1024
    assert profile.safety_margin_tokens == 512
    assert profile.available_input_tokens == 6464
    assert profile.conservative_multiplier == 1.2


def test_provider_model_token_estimator_routes_by_budget_profile() -> None:
    tokenizer = ProfileRecordingEstimator()
    manager = ContextBudgetManager(
        budget_profile=resolve_token_budget_profile(
            provider="deepseek",
            model="deepseek-v4-flash",
            profiles={
                (
                    "deepseek",
                    "deepseek-v4-flash",
                ): TokenBudgetProfile(
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    context_limit_tokens=100,
                    reserved_output_tokens=20,
                    safety_margin_tokens=10,
                )
            },
        ),
        token_estimator=ProviderModelTokenEstimator(
            model_estimators={
                (
                    "deepseek",
                    "deepseek-v4-flash",
                ): tokenizer
            }
        ),
        compression_threshold_ratio=0.9,
    )

    result = manager.apply(
        prompt_text="12345",
        hard_context_text="12",
        soft_context_text="345",
        memory_ids=[],
        recent_event_ids=[],
    )

    assert result.provider == "deepseek"
    assert result.model == "deepseek-v4-flash"
    assert result.available_input_tokens == 70
    assert result.token_estimator_method == "profile_recording"
    assert tokenizer.profiles
    assert all(profile is manager.budget_profile for profile in tokenizer.profiles)


def test_context_budget_manager_uses_provider_model_profile_available_input_budget() -> None:
    manager = ContextBudgetManager(
        budget_profile=TokenBudgetProfile(
            provider="openai-compatible",
            model="small-context-model",
            context_limit_tokens=100,
            reserved_output_tokens=20,
            safety_margin_tokens=10,
            conservative_multiplier=1.0,
        ),
        token_estimator=CountingEstimator(),
        compression_threshold_ratio=0.5,
    )

    result = manager.apply(
        prompt_text="one two three four five six seven eight nine ten",
        hard_context_text="one two three",
        soft_context_text="four five six seven",
        memory_ids=[],
        recent_event_ids=[],
    )

    assert result.provider == "openai-compatible"
    assert result.model == "small-context-model"
    assert result.context_limit_tokens == 100
    assert result.available_input_tokens == 70
    assert result.reserved_output_tokens == 20
    assert result.safety_margin_tokens == 10
    assert result.context_tokens_estimated == 10
    assert result.hard_context_tokens_estimated == 3
    assert result.soft_context_tokens_estimated == 4
    assert result.context_budget_ratio == round(10 / 70, 4)
    assert result.compression_used is False


def test_context_budget_manager_applies_conservative_multiplier_to_all_estimates() -> None:
    manager = ContextBudgetManager(
        budget_profile=TokenBudgetProfile(
            provider="local",
            model="conservative",
            context_limit_tokens=100,
            reserved_output_tokens=0,
            safety_margin_tokens=0,
            conservative_multiplier=1.5,
        ),
        token_estimator=CountingEstimator(),
        compression_threshold_ratio=0.8,
    )

    result = manager.apply(
        prompt_text="one two three",
        hard_context_text="one two",
        soft_context_text="three",
        memory_ids=[],
        recent_event_ids=[],
    )

    assert result.token_estimator_method == "test_words"
    assert result.context_tokens_estimated == 5
    assert result.hard_context_tokens_estimated == 3
    assert result.soft_context_tokens_estimated == 2
    assert result.context_budget_ratio == 0.05


def test_default_token_estimator_is_more_conservative_than_legacy_character_division() -> None:
    text = "a" * 400

    assert estimate_tokens(text) > len(text) // 4


def test_runtime_trace_records_configured_provider_budget_profile(tmp_path: Path) -> None:
    case = CaseLoader().load(CASE_DIR)
    jsonl_path = tmp_path / "trace.jsonl"
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer(
            jsonl_path=jsonl_path,
            log_path=tmp_path / "trace.log",
        ),
        token_budget_profile=TokenBudgetProfile(
            provider="openai-compatible",
            model="trace-model",
            context_limit_tokens=10000,
            reserved_output_tokens=1000,
            safety_margin_tokens=500,
            conservative_multiplier=1.25,
        ),
        token_estimator=CountingEstimator(),
    )
    session = runtime.session_store.create(case)

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id="butler", text="Speak."),
    )

    record = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    budget = record["context_layer_budget"]
    assert budget["provider"] == "openai-compatible"
    assert budget["model"] == "trace-model"
    assert budget["context_limit_tokens"] == 10000
    assert budget["available_input_tokens"] == 8500
    assert budget["reserved_output_tokens"] == 1000
    assert budget["safety_margin_tokens"] == 500
    assert budget["conservative_multiplier"] == 1.25
    assert budget["token_estimator_method"] == "test_words"


def test_runtime_resolves_budget_profile_from_gateway_provider_and_model(
    tmp_path: Path,
) -> None:
    case = CaseLoader().load(CASE_DIR)
    jsonl_path = tmp_path / "trace.jsonl"
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=ProviderAwareAgent()),
        runtime_tracer=RuntimeTracer(
            jsonl_path=jsonl_path,
            log_path=tmp_path / "trace.log",
        ),
        token_estimator=CountingEstimator(),
    )
    session = runtime.session_store.create(case)

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id="butler", text="Speak."),
    )

    record = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    budget = record["context_layer_budget"]
    assert budget["provider"] == "deepseek"
    assert budget["model"] == "deepseek-v4-flash"
    assert budget["reserved_output_tokens"] == 1024
    assert budget["safety_margin_tokens"] == 512
    assert budget["token_estimator_method"] == "test_words"
