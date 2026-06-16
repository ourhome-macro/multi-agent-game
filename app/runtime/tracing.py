from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from app.domain.models import ActionType, AgentIntent, PlayerAction, WorldEvent

TRACE_SCHEMA_VERSION = 5


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
    memory_projection: dict[str, object] = field(default_factory=dict)
    npc_skill_projection: dict[str, object] = field(default_factory=dict)
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    security_flags: list[str] = field(default_factory=list)
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: float = field(default_factory=perf_counter)


class RuntimeTraceSink(Protocol):
    def write(self, record: dict[str, object]) -> None:
        ...


class JsonlRuntimeTraceSink:
    def __init__(
        self,
        *,
        jsonl_path: Path | str = Path("logs") / "runtime_trace.jsonl",
        log_path: Path | str = Path("logs") / "runtime_trace.log",
    ) -> None:
        self._jsonl_path = Path(jsonl_path)
        self._log_path = Path(log_path)

    def write(self, record: dict[str, object]) -> None:
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._jsonl_path.open("a", encoding="utf-8") as jsonl_file:
            jsonl_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        with self._log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(_render_log_record(record) + "\n")


class PostgresRuntimeTraceStore(Protocol):
    def append_runtime_trace(self, record: dict[str, object]) -> str:
        ...


class PostgresTraceSink:
    def __init__(self, event_store: PostgresRuntimeTraceStore) -> None:
        self._event_store = event_store

    def write(self, record: dict[str, object]) -> None:
        self._event_store.append_runtime_trace(record)


class RuntimeTraceBuffer:
    """Collect trace records until the persistence boundary can flush them."""

    def __init__(self) -> None:
        self._records: list[dict[str, object]] = []

    def write(self, record: dict[str, object]) -> None:
        self._records.append(dict(record))

    def drain(self) -> list[dict[str, object]]:
        records = self._records
        self._records = []
        return records

    def clear(self) -> None:
        self._records = []


class RuntimeTracer:
    def __init__(
        self,
        *,
        jsonl_path: Path | str = Path("logs") / "runtime_trace.jsonl",
        log_path: Path | str = Path("logs") / "runtime_trace.log",
        enabled: bool = True,
        sink: RuntimeTraceSink | None = None,
    ) -> None:
        self._enabled = enabled
        self._sink = sink or JsonlRuntimeTraceSink(
            jsonl_path=jsonl_path,
            log_path=log_path,
        )
        self._turn_ids_by_session: dict[str, int] = {}

    @classmethod
    def disabled(cls) -> RuntimeTracer:
        return cls(enabled=False)

    @classmethod
    def postgres(cls, event_store: PostgresRuntimeTraceStore) -> RuntimeTracer:
        return cls(sink=PostgresTraceSink(event_store))

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
        memory_projection: dict[str, object] | None = None,
        npc_skill_projection: dict[str, object] | None = None,
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
            memory_projection=_sanitize_memory_projection(memory_projection or {}),
            npc_skill_projection=_sanitize_npc_skill_projection(
                npc_skill_projection or {}
            ),
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
        public_speech: str | None = None,
        public_speech_source: str | None = None,
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
            "memory_projection": draft.memory_projection,
            "npc_skill_projection": draft.npc_skill_projection,
            "tool_calls": draft.tool_calls,
            "security_flags": draft.security_flags,
            "intent_type": intent.intent.value if intent is not None else None,
            "public_speech": public_speech,
            "public_speech_source": public_speech_source,
            "director_allowed": director_allowed,
            "director_reason_category": director_reason_category,
            "rule_rejections": rule_rejections,
            "new_event_types": [event.type.value for event in new_events],
            "phase_before": draft.phase_before,
            "phase_after": phase_after,
            "status": status,
            "error_category": error_category or _llm_error_type(intent),
            "llm_fallback_used": _llm_fallback_used(intent),
            "llm_error_type": _llm_error_type(intent),
            "llm_error_message_sanitized": _llm_error_message(intent),
            "schema_validation_errors": _llm_schema_validation_errors(intent),
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
        self._sink.write(record)


def _sanitize_tool_call(tool_call: dict[str, object]) -> dict[str, object]:
    return {
        "tool_name": str(tool_call.get("tool_name", "")),
        "status": str(tool_call.get("status", "")),
        "duration_ms": int(tool_call.get("duration_ms", 0)),
        "error_category": tool_call.get("error_category"),
        "result_count": int(tool_call.get("result_count", 0)),
    }


def _sanitize_memory_projection(projection: dict[str, object]) -> dict[str, object]:
    raw_items = projection.get("items", [])
    items = raw_items if isinstance(raw_items, list) else []
    return {
        "skill_id": str(projection.get("skill_id", "")),
        "included_memory_types": _string_list(
            projection.get("included_memory_types", []),
        ),
        "included_scopes": _string_list(projection.get("included_scopes", [])),
        "included_layers": _string_list(projection.get("included_layers", [])),
        "forbidden_scopes": _string_list(projection.get("forbidden_scopes", [])),
        "forbidden_layers": _string_list(projection.get("forbidden_layers", [])),
        "selected_count": int(projection.get("selected_count", 0)),
        "director_safe_fragment_refs": _string_list(
            projection.get("director_safe_fragment_refs", []),
        ),
        "store": _sanitize_memory_store_projection(projection.get("store", {})),
        "items": [_sanitize_memory_projection_item(item) for item in items],
    }


def _sanitize_memory_store_projection(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        "backend": str(value.get("backend", "")),
        "candidate_count": int(value.get("candidate_count", 0)),
        "requested_filters": _sanitize_memory_store_filters(
            value.get("requested_filters", {}),
        ),
    }


def _sanitize_memory_store_filters(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        "session_id": str(value.get("session_id", "")),
        "target_id": str(value.get("target_id", "")),
        "phase": str(value.get("phase", "")),
        "scopes": _string_list(value.get("scopes", [])),
        "layers": _string_list(value.get("layers", [])),
        "memory_types": _string_list(value.get("memory_types", [])),
    }


def _sanitize_memory_projection_item(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        item = {}
    visible_to = item.get("visible_to_character_ids", [])
    if not isinstance(visible_to, list):
        visible_to = []
    return {
        "memory_id": str(item.get("memory_id", "")),
        "memory_type": str(item.get("memory_type", "")),
        "memory_scope": str(item.get("memory_scope", "")),
        "memory_layer": str(item.get("memory_layer", "")),
        "owner_character_id": item.get("owner_character_id"),
        "visible_to_character_ids": [str(value) for value in visible_to],
    }


def _sanitize_npc_skill_projection(projection: dict[str, object]) -> dict[str, object]:
    raw_items = projection.get("items", [])
    items = raw_items if isinstance(raw_items, list) else []
    return {
        "selected_skill_ids": _string_list(projection.get("selected_skill_ids", [])),
        "skill_safe_fragment_refs": _string_list(
            projection.get("skill_safe_fragment_refs", []),
        ),
        "items": [_sanitize_npc_skill_projection_item(item) for item in items],
    }


def _sanitize_npc_skill_projection_item(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        item = {}
    return {
        "skill_id": str(item.get("skill_id", "")),
        "type": str(item.get("type", "")),
        "level": int(item.get("level", 0)),
        "signature": bool(item.get("signature", False)),
        "allowed_intents": _string_list(item.get("allowed_intents", [])),
        "allowed_tactics": _string_list(item.get("allowed_tactics", [])),
        "max_disclosure_mode_by_world_info": _string_dict(
            item.get("max_disclosure_mode_by_world_info", {}),
        ),
        "safe_fragment_refs": _string_list(item.get("safe_fragment_refs", [])),
        "memory_plan_id": (
            str(item["memory_plan_id"])
            if item.get("memory_plan_id") is not None
            else None
        ),
        "allowed_proposed_actions": _string_list(
            item.get("allowed_proposed_actions", []),
        ),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


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
    public_speech = record.get("public_speech")
    speech_source = record.get("public_speech_source")
    speech_part = (
        f" speech_source={speech_source} speech={_single_line_text(public_speech)}"
        if isinstance(public_speech, str) and public_speech
        else ""
    )
    return (
        f"[{record['timestamp']}] turn={record['turn_id']} trace={record['trace_id']} "
        f"case={record['case_id']} session={record['session_id']} "
        f"action={record['action_type']} target={record['target_agent_id']} "
        f"backend={record['agent_backend']} model={record.get('model')} "
        f"status={record['status']} error={record.get('error_category')} "
        f"llm_fallback={str(record.get('llm_fallback_used')).lower()} "
        f"llm_error={record.get('llm_error_type')} "
        f"duration={record['duration_ms']}ms context={record['context_budget_ratio']} "
        f"tokens={record['context_tokens_estimated']} "
        f"compression={str(record['compression_used']).lower()} memories={memories} "
        f"tools={tools} security={security} intent={record.get('intent_type')} "
        f"director={'allowed' if record.get('director_allowed') else 'blocked'} "
        f"reason={record.get('director_reason_category')} "
        f"phase={record['phase_before']}->{record['phase_after']} events={events} "
        f"player_text={record.get('player_text_hash')} "
        f"len={record.get('player_text_length')}"
        f"{speech_part}"
    )


def _single_line_text(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _llm_fallback_used(intent: AgentIntent | None) -> bool:
    return bool(
        intent is not None
        and intent.llm_error is not None
        and intent.llm_error.fallback_used
    )


def _llm_error_type(intent: AgentIntent | None) -> str | None:
    if intent is None or intent.llm_error is None:
        return None
    return intent.llm_error.error_type.value


def _llm_error_message(intent: AgentIntent | None) -> str | None:
    if intent is None or intent.llm_error is None:
        return None
    return intent.llm_error.error_message_sanitized


def _llm_schema_validation_errors(intent: AgentIntent | None) -> list[dict[str, object]]:
    if intent is None or intent.llm_error is None:
        return []
    return [
        error.model_dump(mode="json")
        for error in intent.llm_error.schema_validation_errors
    ]
