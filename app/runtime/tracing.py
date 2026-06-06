from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.domain.models import ActionType, AgentIntent, PlayerAction, WorldEvent

TRACE_SCHEMA_VERSION = 1


@dataclass
class RuntimeTraceDraft:
    case_id: str
    session_id: str
    turn_id: int
    action: PlayerAction
    target_agent_id: str
    agent_backend: str
    phase_before: str
    model: str | None = None
    context_tokens_estimated: int = 0
    context_budget_ratio: float = 0.0
    compression_used: bool = False
    memory_ids_used: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    security_flags: list[str] = field(default_factory=list)
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: float = field(default_factory=perf_counter)


class RuntimeTracer:
    def __init__(
        self,
        *,
        jsonl_path: Path | str = Path("logs") / "runtime_trace.jsonl",
        log_path: Path | str = Path("logs") / "runtime_trace.log",
        enabled: bool = True,
    ) -> None:
        self._jsonl_path = Path(jsonl_path)
        self._log_path = Path(log_path)
        self._enabled = enabled
        self._turn_ids_by_session: dict[str, int] = {}

    @classmethod
    def disabled(cls) -> RuntimeTracer:
        return cls(enabled=False)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def next_turn_id(self, session_id: str) -> int:
        next_turn = self._turn_ids_by_session.get(session_id, 0) + 1
        self._turn_ids_by_session[session_id] = next_turn
        return next_turn

    def start_turn(
        self,
        *,
        case_id: str,
        session_id: str,
        action: PlayerAction,
        target_agent_id: str,
        agent_backend: str,
        phase_before: str,
        model: str | None = None,
        context_tokens_estimated: int = 0,
        context_budget_ratio: float = 0.0,
        compression_used: bool = False,
        memory_ids_used: list[str] | None = None,
        tool_calls: list[dict[str, object]] | None = None,
        security_flags: list[str] | None = None,
    ) -> RuntimeTraceDraft:
        return RuntimeTraceDraft(
            case_id=case_id,
            session_id=session_id,
            turn_id=self.next_turn_id(session_id),
            action=action,
            target_agent_id=target_agent_id,
            agent_backend=agent_backend,
            model=model,
            phase_before=phase_before,
            context_tokens_estimated=context_tokens_estimated,
            context_budget_ratio=context_budget_ratio,
            compression_used=compression_used,
            memory_ids_used=memory_ids_used or [],
            tool_calls=[_sanitize_tool_call(item) for item in (tool_calls or [])],
            security_flags=security_flags or [],
        )

    def finish_turn(
        self,
        draft: RuntimeTraceDraft,
        *,
        intent: AgentIntent | None,
        director_allowed: bool,
        director_reason_category: str | None,
        rule_rejections: list[str],
        new_events: list[WorldEvent],
        phase_after: str,
        status: str = "ok",
        error_category: str | None = None,
    ) -> dict[str, object]:
        record = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_id": draft.trace_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "case_id": draft.case_id,
            "session_id": draft.session_id,
            "turn_id": draft.turn_id,
            "action_type": draft.action.type.value,
            "target_agent_id": draft.target_agent_id,
            "agent_backend": draft.agent_backend,
            "model": draft.model,
            "duration_ms": round((perf_counter() - draft.started_at) * 1000),
            "context_tokens_estimated": draft.context_tokens_estimated,
            "context_budget_ratio": draft.context_budget_ratio,
            "compression_used": draft.compression_used,
            "memory_ids_used": draft.memory_ids_used,
            "tool_calls": draft.tool_calls,
            "security_flags": draft.security_flags,
            "intent_type": intent.intent.value if intent is not None else None,
            "director_allowed": director_allowed,
            "director_reason_category": director_reason_category,
            "rule_rejections": rule_rejections,
            "new_event_types": [event.type.value for event in new_events],
            "phase_before": draft.phase_before,
            "phase_after": phase_after,
            "status": status,
            "error_category": error_category,
            "player_text_hash": _hash_text(draft.action.text),
            "player_text_length": len(draft.action.text or ""),
            "claim_hash": _hash_text(draft.action.text)
            if draft.action.type == ActionType.ACCUSE
            else None,
            "evidence_ids": list(draft.action.evidence_clue_ids)
            if draft.action.type == ActionType.ACCUSE
            else [],
        }
        self.write(record)
        return record

    def write(self, record: dict[str, object]) -> None:
        if not self._enabled:
            return
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._jsonl_path.open("a", encoding="utf-8") as jsonl_file:
            jsonl_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        with self._log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(_render_log_record(record) + "\n")


def _sanitize_tool_call(tool_call: dict[str, object]) -> dict[str, object]:
    return {
        "tool_name": str(tool_call.get("tool_name", "")),
        "status": str(tool_call.get("status", "")),
        "duration_ms": int(tool_call.get("duration_ms", 0)),
        "error_category": tool_call.get("error_category"),
        "result_count": int(tool_call.get("result_count", 0)),
    }


def _hash_text(text: str | None) -> str | None:
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _render_log_record(record: dict[str, object]) -> str:
    security = ",".join(str(item) for item in record.get("security_flags", [])) or "none"
    events = ",".join(str(item) for item in record.get("new_event_types", [])) or "none"
    memories = len(record.get("memory_ids_used", []))
    tools = len(record.get("tool_calls", []))
    return (
        f"[{record['timestamp']}] turn={record['turn_id']} trace={record['trace_id']} "
        f"case={record['case_id']} session={record['session_id']} "
        f"action={record['action_type']} target={record['target_agent_id']} "
        f"backend={record['agent_backend']} model={record.get('model')} "
        f"status={record['status']} error={record.get('error_category')} "
        f"duration={record['duration_ms']}ms context={record['context_budget_ratio']} "
        f"tokens={record['context_tokens_estimated']} "
        f"compression={str(record['compression_used']).lower()} memories={memories} "
        f"tools={tools} security={security} intent={record.get('intent_type')} "
        f"director={'allowed' if record.get('director_allowed') else 'blocked'} "
        f"reason={record.get('director_reason_category')} "
        f"phase={record['phase_before']}->{record['phase_after']} events={events} "
        f"player_text={record.get('player_text_hash')} "
        f"len={record.get('player_text_length')}"
    )
