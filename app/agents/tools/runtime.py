from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from app.agents.memory import MemoryRetriever
from app.domain.models import CasePackage, PlayerAction, SessionState


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: str
    result_count: int
    duration_ms: int
    error_category: str | None = None

    @property
    def summary(self) -> dict[str, object]:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_category": self.error_category,
            "result_count": self.result_count,
        }


class ToolRuntime:
    _ALLOWED_TOOLS = {
        "get_public_state",
        "get_known_clues",
        "get_relationship_to_player",
        "search_memory",
        "get_recent_events",
        "get_disclosure_constraints",
    }

    def __init__(self, *, memory_retriever: MemoryRetriever | None = None) -> None:
        self._memory_retriever = memory_retriever or MemoryRetriever()

    def call(
        self,
        tool_name: str,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> ToolResult:
        started_at = perf_counter()
        if tool_name not in self._ALLOWED_TOOLS:
            return self._result(
                tool_name=tool_name,
                status="error",
                started_at=started_at,
                error_category="tool.not_allowed",
            )
        if tool_name == "search_memory":
            result_count = len(
                self._memory_retriever.retrieve(
                    case=case,
                    session=session,
                    action=action,
                )
            )
            return self._result(
                tool_name=tool_name,
                status="ok",
                started_at=started_at,
                result_count=result_count,
            )
        if tool_name == "get_known_clues":
            return self._result(
                tool_name=tool_name,
                status="ok",
                started_at=started_at,
                result_count=len(session.discovered_clues),
            )
        if tool_name == "get_recent_events":
            return self._result(
                tool_name=tool_name,
                status="ok",
                started_at=started_at,
                result_count=min(len(session.events), 10),
            )
        return self._result(
            tool_name=tool_name,
            status="ok",
            started_at=started_at,
            result_count=1,
        )

    def _result(
        self,
        *,
        tool_name: str,
        status: str,
        started_at: float,
        result_count: int = 0,
        error_category: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            status=status,
            duration_ms=round((perf_counter() - started_at) * 1000),
            error_category=error_category,
            result_count=result_count,
        )
