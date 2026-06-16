from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Protocol

from app.domain.models import CompressedHistoryContext


@dataclass(frozen=True)
class TokenBudgetProfile:
    provider: str = "default"
    model: str = "default"
    context_limit_tokens: int = 8000
    reserved_output_tokens: int = 0
    safety_margin_tokens: int = 0
    conservative_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.context_limit_tokens <= 0:
            raise ValueError("context_limit_tokens must be positive")
        if self.reserved_output_tokens < 0:
            raise ValueError("reserved_output_tokens must be non-negative")
        if self.safety_margin_tokens < 0:
            raise ValueError("safety_margin_tokens must be non-negative")
        if self.conservative_multiplier <= 0:
            raise ValueError("conservative_multiplier must be positive")
        if self.available_input_tokens <= 0:
            raise ValueError(
                "context_limit_tokens must exceed reserved_output_tokens "
                "and safety_margin_tokens"
            )

    @property
    def available_input_tokens(self) -> int:
        return (
            self.context_limit_tokens
            - self.reserved_output_tokens
            - self.safety_margin_tokens
        )


@dataclass(frozen=True)
class TokenEstimate:
    tokens: int
    method: str

    def __post_init__(self) -> None:
        if self.tokens < 0:
            raise ValueError("tokens must be non-negative")
        if not self.method:
            raise ValueError("method must be non-empty")


class TokenEstimator(Protocol):
    def estimate(
        self,
        text: str,
        *,
        profile: TokenBudgetProfile | None = None,
    ) -> TokenEstimate | int:
        ...


TokenEstimatorLike = TokenEstimator | Callable[[str], int | Sequence[object]]


@dataclass(frozen=True)
class CallableTokenEstimator:
    tokenizer: Callable[[str], int | Sequence[object]]
    method: str = "callable_tokenizer"

    def estimate(
        self,
        text: str,
        *,
        profile: TokenBudgetProfile | None = None,
    ) -> TokenEstimate:
        del profile
        result = self.tokenizer(text)
        if isinstance(result, int):
            tokens = result
        else:
            tokens = len(result)
        return TokenEstimate(tokens=max(0, tokens), method=self.method)


@dataclass(frozen=True)
class ConservativeTokenEstimator:
    method: str = "conservative_char_byte"

    def estimate(
        self,
        text: str,
        *,
        profile: TokenBudgetProfile | None = None,
    ) -> TokenEstimate:
        del profile
        if text == "":
            return TokenEstimate(tokens=0, method=self.method)
        char_count = len(text)
        byte_count = len(text.encode("utf-8"))
        word_count = len(text.split())
        token_count = max(
            ceil(char_count / 3),
            ceil(byte_count / 3),
            word_count,
            1,
        )
        return TokenEstimate(tokens=token_count, method=self.method)


@dataclass(frozen=True)
class CompressedHistory:
    summary: str
    important_event_ids: list[str]
    important_memory_ids: list[str]
    open_threads: list[str]
    risk_notes: list[str]

    def to_context(self) -> CompressedHistoryContext:
        return CompressedHistoryContext(
            summary=self.summary,
            important_event_ids=list(self.important_event_ids),
            important_memory_ids=list(self.important_memory_ids),
            open_threads=list(self.open_threads),
            risk_notes=list(self.risk_notes),
        )


@dataclass(frozen=True)
class ContextBudgetResult:
    context_tokens_estimated: int
    context_budget_ratio: float
    compression_used: bool
    compressed_history: CompressedHistory | None
    hard_context_tokens_estimated: int = 0
    soft_context_tokens_estimated: int = 0
    compression_scope: str = "none"
    compressed_layers: list[str] | None = None
    hard_context_over_limit: bool = False
    fallback_reason: str | None = None
    provider: str = "default"
    model: str = "default"
    context_limit_tokens: int = 8000
    available_input_tokens: int = 8000
    reserved_output_tokens: int = 0
    safety_margin_tokens: int = 0
    conservative_multiplier: float = 1.0
    token_estimator_method: str = "conservative_char_byte"


class ContextBudgetManager:
    def __init__(
        self,
        *,
        context_limit_tokens: int | None = None,
        budget_profile: TokenBudgetProfile | None = None,
        token_estimator: TokenEstimatorLike | None = None,
        compression_threshold_ratio: float = 0.8,
    ) -> None:
        if not 0 < compression_threshold_ratio:
            raise ValueError("compression_threshold_ratio must be positive")
        self._budget_profile = _resolve_budget_profile(
            budget_profile=budget_profile,
            context_limit_tokens=context_limit_tokens,
        )
        self._token_estimator = _coerce_token_estimator(token_estimator)
        self._compression_threshold_ratio = compression_threshold_ratio

    def apply(
        self,
        *,
        prompt_text: str,
        memory_ids: list[str],
        recent_event_ids: list[str],
        hard_context_text: str | None = None,
        soft_context_text: str | None = None,
    ) -> ContextBudgetResult:
        total_estimate = self._estimate(prompt_text)
        hard_estimate = (
            self._estimate(hard_context_text) if hard_context_text is not None else None
        )
        soft_estimate = (
            self._estimate(soft_context_text) if soft_context_text is not None else None
        )
        hard_token_estimate = hard_estimate.tokens if hard_estimate is not None else 0
        soft_token_estimate = soft_estimate.tokens if soft_estimate is not None else 0
        ratio = round(
            total_estimate.tokens / self._budget_profile.available_input_tokens,
            4,
        )
        hard_context_over_limit = (
            hard_estimate is not None
            and hard_token_estimate > self._budget_profile.available_input_tokens
        )
        if hard_context_over_limit:
            return ContextBudgetResult(
                context_tokens_estimated=total_estimate.tokens,
                context_budget_ratio=ratio,
                compression_used=False,
                compressed_history=None,
                hard_context_tokens_estimated=hard_token_estimate,
                soft_context_tokens_estimated=soft_token_estimate,
                compression_scope="hard_context_over_limit",
                compressed_layers=[],
                hard_context_over_limit=True,
                fallback_reason="hard_context_over_limit",
                **self._result_profile_fields(total_estimate.method),
            )
        if ratio <= self._compression_threshold_ratio:
            return ContextBudgetResult(
                context_tokens_estimated=total_estimate.tokens,
                context_budget_ratio=ratio,
                compression_used=False,
                compressed_history=None,
                hard_context_tokens_estimated=hard_token_estimate,
                soft_context_tokens_estimated=soft_token_estimate,
                compression_scope="none",
                compressed_layers=[],
                hard_context_over_limit=hard_context_over_limit,
                **self._result_profile_fields(total_estimate.method),
            )
        return ContextBudgetResult(
            context_tokens_estimated=total_estimate.tokens,
            context_budget_ratio=ratio,
            compression_used=True,
            compressed_history=CompressedHistory(
                summary=(
                    "Context exceeded budget threshold; preserve referenced events "
                    "and memories as compressed history."
                ),
                important_event_ids=recent_event_ids,
                important_memory_ids=memory_ids,
                open_threads=[],
                risk_notes=[],
            ),
            hard_context_tokens_estimated=hard_token_estimate,
            soft_context_tokens_estimated=soft_token_estimate,
            compression_scope="soft_context",
            compressed_layers=["soft_context"],
            hard_context_over_limit=hard_context_over_limit,
            **self._result_profile_fields(total_estimate.method),
        )

    @property
    def budget_profile(self) -> TokenBudgetProfile:
        return self._budget_profile

    def _estimate(self, text: str) -> TokenEstimate:
        raw = _coerce_token_estimate(
            self._token_estimator.estimate(text, profile=self._budget_profile)
        )
        tokens = ceil(raw.tokens * self._budget_profile.conservative_multiplier)
        if text != "":
            tokens = max(1, tokens)
        return TokenEstimate(tokens=tokens, method=raw.method)

    def _result_profile_fields(self, estimator_method: str) -> dict[str, object]:
        return {
            "provider": self._budget_profile.provider,
            "model": self._budget_profile.model,
            "context_limit_tokens": self._budget_profile.context_limit_tokens,
            "available_input_tokens": self._budget_profile.available_input_tokens,
            "reserved_output_tokens": self._budget_profile.reserved_output_tokens,
            "safety_margin_tokens": self._budget_profile.safety_margin_tokens,
            "conservative_multiplier": self._budget_profile.conservative_multiplier,
            "token_estimator_method": estimator_method,
        }


def estimate_tokens(
    text: str,
    *,
    profile: TokenBudgetProfile | None = None,
    token_estimator: TokenEstimatorLike | None = None,
) -> int:
    budget_profile = profile or TokenBudgetProfile()
    estimator = _coerce_token_estimator(token_estimator)
    raw = _coerce_token_estimate(estimator.estimate(text, profile=budget_profile))
    tokens = ceil(raw.tokens * budget_profile.conservative_multiplier)
    if text != "":
        tokens = max(1, tokens)
    return tokens


def _resolve_budget_profile(
    *,
    budget_profile: TokenBudgetProfile | None,
    context_limit_tokens: int | None,
) -> TokenBudgetProfile:
    if budget_profile is None:
        return TokenBudgetProfile(
            context_limit_tokens=(
                context_limit_tokens if context_limit_tokens is not None else 8000
            )
        )
    if context_limit_tokens is None:
        return budget_profile
    return TokenBudgetProfile(
        provider=budget_profile.provider,
        model=budget_profile.model,
        context_limit_tokens=context_limit_tokens,
        reserved_output_tokens=budget_profile.reserved_output_tokens,
        safety_margin_tokens=budget_profile.safety_margin_tokens,
        conservative_multiplier=budget_profile.conservative_multiplier,
    )


def _coerce_token_estimator(
    estimator: TokenEstimatorLike | None,
) -> TokenEstimator:
    if estimator is None:
        return ConservativeTokenEstimator()
    if callable(estimator) and not hasattr(estimator, "estimate"):
        return CallableTokenEstimator(estimator)
    return estimator


def _coerce_token_estimate(value: TokenEstimate | int) -> TokenEstimate:
    if isinstance(value, TokenEstimate):
        return value
    return TokenEstimate(tokens=value, method="custom_int")
