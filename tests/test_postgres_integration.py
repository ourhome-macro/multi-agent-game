from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents.gateway import AgentGateway
from app.api.routes import create_router
from app.cases.loader import CaseLoader
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    EventType,
    LLMErrorSummary,
    LLMErrorType,
)
from app.runtime.database import connect_postgres, load_dotenv_if_needed
from app.runtime.events import make_event
from app.runtime.postgres_runtime import PostgresActionRuntime, PostgresRuntimeBackend
from app.runtime.schema_admin import (
    apply_postgres_schema,
    check_postgres_schema,
    rebuild_projection_tables,
)
from app.runtime.service import RuntimeContainer, create_runtime
from app.runtime.tracing import RuntimeTraceBuffer, RuntimeTracer
from app.storage.postgres import PostgresEventStore, PostgresSessionStore, StaleSessionSequenceError

pytestmark = pytest.mark.postgres


def test_postgres_api_persists_actions_recovers_after_runtime_rebuild() -> None:
    _reset_schema()
    runtime = _runtime()
    client = TestClient(_app(runtime))

    session_id = client.post("/sessions", json={"case_id": "fake_case_001"}).json()[
        "session_id"
    ]
    first = client.post(
        f"/sessions/{session_id}/actions",
        headers={"Idempotency-Key": "inspect-desk-001"},
        json={"type": "inspect", "target_id": "desk"},
    )
    assert first.status_code == 200
    assert first.json()["state"]["event_count"] == 8

    runtime.close()
    recovered_runtime = _runtime()
    recovered_client = TestClient(_app(recovered_runtime))
    recovered = recovered_client.get(f"/sessions/{session_id}/state")
    events = recovered_client.get(f"/sessions/{session_id}/events")

    assert recovered.status_code == 200
    assert recovered.json()["event_count"] == 8
    assert recovered.json()["narrative_phase"] == "investigation"
    assert events.status_code == 200
    assert [event["type"] for event in events.json()] == [
        "session.created",
        "player.inspected",
        "clue.discovered",
        "player_knowledge.updated",
        "memory_candidate.created",
        "agent_memory_snapshot.updated",
        "narrative.beat.completed",
        "narrative.phase.changed",
    ]
    recovered_runtime.close()


def test_postgres_api_idempotency_replays_original_response_without_duplicate_events() -> None:
    _reset_schema()
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = client.post("/sessions", json={"case_id": "fake_case_001"}).json()[
        "session_id"
    ]
    request = {
        "headers": {"Idempotency-Key": "inspect-desk-duplicate"},
        "json": {"type": "inspect", "target_id": "desk"},
    }

    first = client.post(f"/sessions/{session_id}/actions", **request)
    second = client.post(f"/sessions/{session_id}/actions", **request)
    events = client.get(f"/sessions/{session_id}/events")

    assert first.status_code == 200
    assert second.status_code == 200
    assert [event["id"] for event in second.json()["new_events"]] == [
        event["id"] for event in first.json()["new_events"]
    ]
    assert len(events.json()) == 8
    runtime.close()


def test_postgres_api_rejects_reused_idempotency_key_with_different_action() -> None:
    _reset_schema()
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = client.post("/sessions", json={"case_id": "fake_case_001"}).json()[
        "session_id"
    ]

    first = client.post(
        f"/sessions/{session_id}/actions",
        headers={"Idempotency-Key": "action-conflict"},
        json={"type": "inspect", "target_id": "desk"},
    )
    second = client.post(
        f"/sessions/{session_id}/actions",
        headers={"Idempotency-Key": "action-conflict"},
        json={"type": "inspect", "target_id": "portrait"},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "different request" in second.json()["detail"]
    runtime.close()


def test_postgres_event_store_rejects_stale_sequence_after_concurrent_append() -> None:
    _reset_schema()
    case = CaseLoader().load(Path("cases/fake_case_001"))
    connection_a = connect_postgres(_test_database_url())
    connection_b = connect_postgres(_test_database_url())
    store_a = PostgresEventStore(connection_a)
    store_b = PostgresEventStore(connection_b)
    session_store = PostgresSessionStore(connection_a, event_store=store_a)
    session = session_store.create(case)

    event_a = make_event(
        case_id=session.case_id,
        session_id=session.id,
        actor_id="test",
        event_type=EventType.PLAYER_INSPECTED,
        payload={"target_id": "desk"},
    )
    event_b = make_event(
        case_id=session.case_id,
        session_id=session.id,
        actor_id="test",
        event_type=EventType.PLAYER_INSPECTED,
        payload={"target_id": "portrait"},
    )

    store_a.append(session, [event_a], expected_current_sequence=1)
    with pytest.raises(StaleSessionSequenceError):
        store_b.append(session, [event_b], expected_current_sequence=1)

    assert [item.sequence for item in store_a.load_stored(session.id)] == [1, 2]
    connection_a.close()
    connection_b.close()


def test_postgres_projection_tables_follow_world_events() -> None:
    _reset_schema()
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = client.post("/sessions", json={"case_id": "fake_case_001"}).json()[
        "session_id"
    ]

    response = client.post(
        f"/sessions/{session_id}/actions",
        headers={"Idempotency-Key": f"inspect-desk-{uuid4()}"},
        json={"type": "inspect", "target_id": "desk"},
    )

    assert response.status_code == 200
    with connect_postgres(_test_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_sequence, narrative_phase FROM app_sessions WHERE id = %s",
                (session_id,),
            )
            session_row = cursor.fetchone()
            cursor.execute(
                "SELECT count(*) AS count FROM world_events WHERE session_id = %s",
                (session_id,),
            )
            event_count = cursor.fetchone()["count"]
            cursor.execute(
                "SELECT count(*) AS count FROM memory_snapshots WHERE session_id = %s",
                (session_id,),
            )
            memory_count = cursor.fetchone()["count"]
            cursor.execute(
                "SELECT operation FROM memory_operations WHERE session_id = %s",
                (session_id,),
            )
            operations = [row["operation"] for row in cursor.fetchall()]

    assert session_row == {"current_sequence": 8, "narrative_phase": "investigation"}
    assert event_count == 8
    assert memory_count == 1
    assert operations == ["create"]
    runtime.close()


def test_postgres_projection_tables_can_be_rebuilt_from_world_events() -> None:
    _reset_schema()
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = client.post("/sessions", json={"case_id": "fake_case_001"}).json()[
        "session_id"
    ]

    response = client.post(
        f"/sessions/{session_id}/actions",
        headers={"Idempotency-Key": f"inspect-desk-rebuild-{uuid4()}"},
        json={"type": "inspect", "target_id": "desk"},
    )
    assert response.status_code == 200

    with connect_postgres(_test_database_url()) as connection:
        rebuild = rebuild_projection_tables(connection, dry_run=False)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS count FROM memory_snapshots WHERE session_id = %s",
                (session_id,),
            )
            memory_count = cursor.fetchone()["count"]
            cursor.execute(
                "SELECT operation FROM memory_operations WHERE session_id = %s",
                (session_id,),
            )
            operations = [row["operation"] for row in cursor.fetchall()]

    assert rebuild.executed is True
    assert rebuild.replayed_events == 8
    assert memory_count == 1
    assert operations == ["create"]
    runtime.close()


def test_postgres_runtime_persists_llm_trace_payload() -> None:
    _reset_schema()
    runtime = _runtime(agent_gateway=AgentGateway(mock_agent=_FallbackAgent()))
    client = TestClient(_app(runtime))
    session_id = client.post("/sessions", json={"case_id": "fake_case_001"}).json()[
        "session_id"
    ]

    response = client.post(
        f"/sessions/{session_id}/actions",
        headers={"Idempotency-Key": f"talk-trace-{uuid4()}"},
        json={"type": "talk", "target_id": "butler", "text": "Where were you?"},
    )

    assert response.status_code == 200
    assert response.json()["llm_fallback_used"] is True
    with connect_postgres(_test_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT backend, target_character_id, action_event_id, llm_error_type, payload
                FROM runtime_traces
                WHERE session_id = %s
                """,
                (session_id,),
            )
            rows = cursor.fetchall()

    assert len(rows) == 1
    trace = rows[0]
    payload = trace["payload"]
    assert trace["backend"] == "mock"
    assert trace["target_character_id"] == "butler"
    assert trace["action_event_id"] in {
        event["id"]
        for event in response.json()["new_events"]
        if event["type"] == "player.talked"
    }
    assert trace["llm_error_type"] == "timeout"
    assert payload["llm_fallback_used"] is True
    assert payload["action_event_id"] == trace["action_event_id"]
    assert payload["llm_error_type"] == "timeout"
    assert payload["llm_error_message_sanitized"] == "LLM provider request timed out"
    runtime.close()


def test_postgres_trace_is_not_persisted_when_action_append_hits_stale_sequence() -> None:
    _reset_schema()
    case = CaseLoader().load(Path("cases/fake_case_001"))
    connection_a = connect_postgres(_test_database_url())
    connection_b = connect_postgres(_test_database_url())
    store_a = PostgresEventStore(connection_a)
    store_b = PostgresEventStore(connection_b)
    session_store = PostgresSessionStore(connection_a, event_store=store_a)
    session = session_store.create(case)

    event_a = make_event(
        case_id=session.case_id,
        session_id=session.id,
        actor_id="test",
        event_type=EventType.PLAYER_INSPECTED,
        payload={"target_id": "desk"},
    )
    event_b = make_event(
        case_id=session.case_id,
        session_id=session.id,
        actor_id="player",
        event_type=EventType.PLAYER_TALKED,
        payload={"target_id": "butler", "text": "Where were you?"},
    )
    store_a.append(session, [event_a], expected_current_sequence=1)

    with pytest.raises(StaleSessionSequenceError):
        store_b.append(
            session,
            [event_b],
            expected_current_sequence=1,
            runtime_traces=[
                {
                    "schema_version": 5,
                    "trace_id": f"trace-{uuid4()}",
                    "timestamp": "2026-06-15T00:00:00+00:00",
                    "case_id": session.case_id,
                    "session_id": session.id,
                    "turn_id": 1,
                    "action_type": "talk",
                    "target_agent_id": "butler",
                    "agent_backend": "mock",
                    "director_allowed": True,
                    "memory_projection": {},
                    "npc_skill_projection": {},
                    "error_category": "timeout",
                    "llm_error_type": "timeout",
                    "llm_fallback_used": True,
                }
            ],
        )

    with connection_a.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS count FROM runtime_traces WHERE session_id = %s",
            (session.id,),
        )
        trace_count = cursor.fetchone()["count"]

    assert trace_count == 0
    connection_a.close()
    connection_b.close()


def test_dotenv_loader_does_not_override_existing_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_TEST_DATABASE_URL", "postgresql://existing")

    load_dotenv_if_needed()

    assert os.environ["AGENT_TEST_DATABASE_URL"] == "postgresql://existing"


def _runtime(agent_gateway: AgentGateway | None = None) -> RuntimeContainer:
    case = CaseLoader().load(Path("cases/fake_case_001"))
    connection = connect_postgres(_test_database_url())
    event_store = PostgresEventStore(connection)
    trace_buffer = RuntimeTraceBuffer()
    container = create_runtime(
        [case],
        agent_gateway=agent_gateway,
        runtime_tracer=RuntimeTracer(sink=trace_buffer),
    )
    session_store = PostgresSessionStore(connection, event_store=event_store)
    return replace(
        container,
        session_backend=PostgresRuntimeBackend(
            case_store=container.case_store,
            session_store=session_store,
            event_store=event_store,
            action_runtime=PostgresActionRuntime(
                event_store=event_store,
                action_service=container.action_service,
                trace_buffer=trace_buffer,
            ),
            connection=connection,
        ),
    )


def _reset_schema() -> None:
    connection = connect_postgres(_test_database_url())
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public CASCADE")
            cursor.execute("CREATE SCHEMA public")
            cursor.execute("GRANT USAGE, CREATE ON SCHEMA public TO agent_app")
    result = apply_postgres_schema(connection)
    assert result.ok, result.message
    assert check_postgres_schema(connection).ok
    connection.close()


def _test_database_url() -> str:
    load_dotenv_if_needed()
    value = os.getenv("AGENT_TEST_DATABASE_URL")
    if not value:
        pytest.skip("AGENT_TEST_DATABASE_URL is not configured")
    return value


def _app(runtime: RuntimeContainer) -> object:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_router(lambda: runtime))
    return app


class _FallbackAgent:
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
