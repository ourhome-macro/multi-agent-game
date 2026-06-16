from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.main as app_main
from app.domain.models import (
    ActionType,
    AgentIntent,
    AgentIntentType,
    LLMErrorSummary,
    LLMErrorType,
    LLMSchemaValidationError,
    PlayerAction,
)
from app.runtime.tracing import JsonlRuntimeTraceSink, PostgresTraceSink, RuntimeTracer


def test_postgres_trace_sink_appends_complete_record() -> None:
    store = _RecordingTraceStore()
    record = _trace_record()

    PostgresTraceSink(store).write(record)

    assert store.records == [record]
    assert store.records[0]["llm_fallback_used"] is True
    assert store.records[0]["llm_error_type"] == "timeout"
    assert store.records[0]["llm_error_message_sanitized"] == "LLM provider timed out"
    assert store.records[0]["schema_validation_errors"] == [
        {
            "loc": ["speech"],
            "error_type": "missing",
            "message_sanitized": "field required",
        }
    ]


def test_runtime_tracer_can_write_finished_trace_to_postgres_sink() -> None:
    store = _RecordingTraceStore()
    tracer = RuntimeTracer.postgres(store)
    draft = tracer.start_turn(
        case_id="case.trace",
        session_id="session.trace",
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
        target_agent_id="butler",
        agent_backend="openai",
        model="gpt-test",
        phase_before="opening",
    )
    intent = _fallback_intent()

    rendered = tracer.finish_turn(
        draft,
        intent=intent,
        director_allowed=True,
        director_reason_category=None,
        rule_rejections=[],
        new_events=[],
        phase_after="investigation",
        public_speech=intent.speech,
        public_speech_source="npc",
    )

    assert store.records == [rendered]
    assert rendered["llm_fallback_used"] is True
    assert rendered["llm_error_type"] == "timeout"
    assert rendered["llm_error_message_sanitized"] == "LLM provider timed out"
    assert rendered["schema_validation_errors"] == [
        {
            "loc": ["speech"],
            "error_type": "missing",
            "message_sanitized": "field required",
        }
    ]


def test_jsonl_trace_sink_still_writes_jsonl_and_readable_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _trace_record()
    written: dict[str, list[str]] = {}

    def fake_mkdir(self: Path, **_: object) -> None:
        written.setdefault(str(self), [])

    def fake_open(self: Path, *_: object, **__: object) -> _FakeAppendFile:
        return _FakeAppendFile(written.setdefault(str(self), []))

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    monkeypatch.setattr(Path, "open", fake_open)

    jsonl_path = Path("logs") / "runtime_trace.jsonl"
    log_path = Path("logs") / "runtime_trace.log"

    JsonlRuntimeTraceSink(jsonl_path=jsonl_path, log_path=log_path).write(record)

    assert json.loads("".join(written[str(jsonl_path)])) == record
    log_text = "".join(written[str(log_path)])
    assert "llm_fallback=true" in log_text
    assert "llm_error=timeout" in log_text


def test_disabled_runtime_tracer_does_not_call_sink() -> None:
    sink = _FailingTraceSink()
    tracer = RuntimeTracer(enabled=False, sink=sink)

    tracer.write(_trace_record())

    assert sink.called is False


def test_postgres_runtime_builder_buffers_trace_for_transactional_flush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_connection = _FakeConnection()
    fake_stores: list[_RecordingTraceStore] = []

    def fake_connect_postgres() -> _FakeConnection:
        return fake_connection

    def fake_event_store(connection: object) -> _RecordingTraceStore:
        assert connection is fake_connection
        store = _RecordingTraceStore()
        fake_stores.append(store)
        return store

    monkeypatch.setenv(app_main.RUNTIME_MODE_ENV, app_main.POSTGRES_RUNTIME_MODE)
    monkeypatch.delenv(app_main.APPLY_SCHEMA_ENV, raising=False)
    monkeypatch.setattr(app_main, "connect_postgres", fake_connect_postgres)
    monkeypatch.setattr(app_main, "PostgresEventStore", fake_event_store)

    runtime = app_main.build_runtime()

    runtime.action_service.agent_loop._runtime_tracer.write(_trace_record())  # noqa: SLF001

    assert len(fake_stores) == 1
    assert fake_stores[0].records == []
    assert runtime.session_backend is not None
    trace_buffer = runtime.session_backend.action_runtime.trace_buffer
    assert trace_buffer is not None
    assert trace_buffer.drain() == [_trace_record()]


def _trace_record() -> dict[str, object]:
    return {
        "schema_version": 5,
        "trace_id": "trace.001",
        "timestamp": "2026-06-15T00:00:00+00:00",
        "case_id": "case.trace",
        "session_id": "session.trace",
        "turn_id": 1,
        "action_type": "talk",
        "target_agent_id": "butler",
        "agent_backend": "openai",
        "model": "gpt-test",
        "duration_ms": 12,
        "context_tokens_estimated": 100,
        "context_budget_ratio": 0.1,
        "compression_used": False,
        "memory_ids_used": ["memory.001"],
        "memory_projection": {"selected_count": 1},
        "npc_skill_projection": {},
        "tool_calls": [],
        "security_flags": [],
        "intent_type": "refuse",
        "public_speech": "I cannot answer through the LLM backend.",
        "public_speech_source": "npc",
        "director_allowed": True,
        "director_reason_category": None,
        "rule_rejections": [],
        "new_event_types": [],
        "phase_before": "opening",
        "phase_after": "investigation",
        "status": "ok",
        "error_category": "timeout",
        "llm_fallback_used": True,
        "llm_error_type": "timeout",
        "llm_error_message_sanitized": "LLM provider timed out",
        "schema_validation_errors": [
            {
                "loc": ["speech"],
                "error_type": "missing",
                "message_sanitized": "field required",
            },
        ],
        "player_text_hash": "sha256:test",
        "player_text_length": 15,
        "claim_hash": None,
        "evidence_ids": [],
    }


def _fallback_intent() -> AgentIntent:
    return AgentIntent(
        speech="I cannot answer through the LLM backend.",
        intent=AgentIntentType.REFUSE,
        proposed_actions=[],
        llm_error=LLMErrorSummary(
            backend="openai",
            error_type=LLMErrorType.TIMEOUT,
            error_message_sanitized="LLM provider timed out",
            fallback_used=True,
            schema_validation_errors=[
                LLMSchemaValidationError(
                    loc=["speech"],
                    error_type="missing",
                    message_sanitized="field required",
                ),
            ],
        ),
    )


class _RecordingTraceStore:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def append_runtime_trace(self, record: dict[str, object]) -> str:
        self.records.append(record)
        return str(record["trace_id"])


class _FakeConnection:
    def close(self) -> None:
        pass


class _FakeAppendFile:
    def __init__(self, writes: list[str]) -> None:
        self._writes = writes

    def __enter__(self) -> _FakeAppendFile:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def write(self, value: str) -> int:
        self._writes.append(value)
        return len(value)


class _FailingTraceSink:
    def __init__(self) -> None:
        self.called = False

    def write(self, record: dict[str, object]) -> None:
        self.called = True
        raise AssertionError("disabled tracer must not call sink")
