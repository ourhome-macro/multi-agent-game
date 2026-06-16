from __future__ import annotations

import json
from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, PlayerAction
from app.runtime.budget import (
    ContextBudgetManager,
    TokenBudgetProfile,
    TokenEstimate,
    estimate_tokens,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


class CountingEstimator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def estimate(self, text: str, *, profile: TokenBudgetProfile | None = None) -> TokenEstimate:
        self.calls.append(text)
        return TokenEstimate(tokens=len(text.split()), method="test_words")


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
