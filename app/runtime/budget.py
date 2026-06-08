from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import CompressedHistoryContext


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


class ContextBudgetManager:
    def __init__(
        self,
        *,
        context_limit_tokens: int = 8000,
        compression_threshold_ratio: float = 0.8,
    ) -> None:
        if context_limit_tokens <= 0:
            raise ValueError("context_limit_tokens must be positive")
        self._context_limit_tokens = context_limit_tokens
        self._compression_threshold_ratio = compression_threshold_ratio

    def apply(
        self,
        *,
        prompt_text: str,
        memory_ids: list[str],
        recent_event_ids: list[str],
    ) -> ContextBudgetResult:
        token_estimate = estimate_tokens(prompt_text)
        ratio = round(token_estimate / self._context_limit_tokens, 4)
        if ratio <= self._compression_threshold_ratio:
            return ContextBudgetResult(
                context_tokens_estimated=token_estimate,
                context_budget_ratio=ratio,
                compression_used=False,
                compressed_history=None,
            )
        return ContextBudgetResult(
            context_tokens_estimated=token_estimate,
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
        )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
