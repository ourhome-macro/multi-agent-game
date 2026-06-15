from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.models import EventType, NarrativeState, SessionState, WorldEvent
from app.storage.postgres import (
    IdempotencyConflictError,
    PostgresEventStore,
    StaleSessionSequenceError,
    request_hash_for_events,
)


def test_schema_defines_runtime_persistence_tables_and_constraints() -> None:
    schema_sql = Path("app/storage/schema.sql").read_text(encoding="utf-8")

    for table_name in (
        "app_sessions",
        "world_events",
        "memory_snapshots",
        "memory_operations",
        "character_impressions",
        "character_fact_awareness",
        "runtime_traces",
        "idempotency_keys",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in schema_sql

    assert "UNIQUE (session_id, sequence)" in schema_sql
    assert "PRIMARY KEY (session_id, idempotency_key)" in schema_sql
    assert "REFERENCES world_events(session_id, id)" in schema_sql
    assert "CHECK (array_length(source_event_ids, 1) IS NOT NULL)" in schema_sql
    assert "operation IN ('create', 'reinforce', 'revise', 'supersede', 'archive')" in schema_sql


def test_append_locks_session_allocates_sequence_and_writes_projection() -> None:
    session = _session()
    memory_event = _event(
        event_id="event.memory.snapshot",
        event_type=EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
        payload={
            "memory_id": "memory.player.desk",
            "rule_id": "memory_rule.test",
            "memory_type": "episodic",
            "memory_scope": "npc_private",
            "memory_layer": "working",
            "subject_id": "player",
            "owner_character_id": "butler",
            "visible_to_character_ids": ["butler"],
            "content": "The player found the scratched drawer.",
            "source_event_ids": ["event.player.inspect"],
            "source_memory_ids": [],
            "salience": 0.8,
            "confidence": 1.0,
            "visibility": "private",
            "metadata": {},
            "operation": "create",
        },
    )
    connection = _FakeConnection(case_id=session.case_id, current_sequence=3)

    stored = PostgresEventStore(connection).append(session, [memory_event])

    assert [item.sequence for item in stored] == [4]
    assert connection.commit_count == 1
    assert connection.rollback_count == 0
    assert connection.current_sequence == 4
    assert connection.world_event_rows[0]["sequence"] == 4
    assert connection.world_event_rows[0]["type"] == "agent_memory_snapshot.updated"
    assert connection.query_log[0].startswith("SELECT current_sequence")
    assert any("INSERT INTO memory_snapshots" in query for query in connection.query_log)
    assert any("INSERT INTO memory_operations" in query for query in connection.query_log)


def test_idempotency_key_replays_existing_events_without_second_insert() -> None:
    session = _session()
    events = [
        _event(
            event_id="event.player.inspect",
            event_type=EventType.PLAYER_INSPECTED,
            payload={"target_id": "desk"},
        ),
        _event(
            event_id="event.clue.discovered",
            event_type=EventType.CLUE_DISCOVERED,
            payload={"clue_id": "scratched_drawer"},
            caused_by_event_id="event.player.inspect",
        ),
    ]
    request_hash = request_hash_for_events(events)
    connection = _FakeConnection(case_id=session.case_id, current_sequence=0)
    store = PostgresEventStore(connection)

    first = store.append(
        session,
        events,
        idempotency_key="action-001",
        request_hash=request_hash,
    )
    second = store.append(
        session,
        events,
        idempotency_key="action-001",
        request_hash=request_hash,
    )

    assert [item.sequence for item in first] == [1, 2]
    assert [item.sequence for item in second] == [1, 2]
    assert [item.event.id for item in second] == [event.id for event in events]
    assert connection.world_event_insert_count == 2
    assert connection.idempotency_rows[("session.postgres", "action-001")][
        "response_event_ids"
    ] == ["event.player.inspect", "event.clue.discovered"]


def test_idempotency_key_rejects_different_request_hash() -> None:
    session = _session()
    event = _event(
        event_id="event.player.inspect",
        event_type=EventType.PLAYER_INSPECTED,
        payload={"target_id": "desk"},
    )
    connection = _FakeConnection(case_id=session.case_id, current_sequence=0)
    store = PostgresEventStore(connection)
    store.append(session, [event], idempotency_key="action-001", request_hash="sha256:first")

    with pytest.raises(IdempotencyConflictError):
        store.append(
            session,
            [event],
            idempotency_key="action-001",
            request_hash="sha256:second",
        )


def test_append_rejects_stale_expected_sequence_before_insert() -> None:
    session = _session()
    event = _event(
        event_id="event.player.inspect",
        event_type=EventType.PLAYER_INSPECTED,
        payload={"target_id": "desk"},
    )
    connection = _FakeConnection(case_id=session.case_id, current_sequence=7)

    with pytest.raises(StaleSessionSequenceError):
        PostgresEventStore(connection).append(
            session,
            [event],
            expected_current_sequence=6,
        )

    assert connection.rollback_count == 1
    assert connection.world_event_insert_count == 0
    assert connection.current_sequence == 7


def _session() -> SessionState:
    return SessionState(
        id="session.postgres",
        case_id="case.postgres",
        narrative=NarrativeState(phase="opening"),
        relationships={},
    )


def _event(
    *,
    event_id: str,
    event_type: EventType,
    payload: dict[str, object],
    caused_by_event_id: str | None = None,
) -> WorldEvent:
    return WorldEvent(
        id=event_id,
        case_id="case.postgres",
        session_id="session.postgres",
        actor_id="test",
        type=event_type,
        payload=payload,
        caused_by_event_id=caused_by_event_id,
        created_at="2026-06-15T00:00:00+00:00",
    )


class _FakeConnection:
    def __init__(self, *, case_id: str, current_sequence: int) -> None:
        self.case_id = case_id
        self.current_sequence = current_sequence
        self.cursor_obj = _FakeCursor(self)
        self.commit_count = 0
        self.rollback_count = 0
        self.world_event_rows: list[dict[str, object]] = []
        self.idempotency_rows: dict[tuple[str, str], dict[str, object]] = {}
        self.query_log: list[str] = []
        self.world_event_insert_count = 0

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.pending_result: list[dict[str, object]] = []

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        normalized_query = _normalize_sql(query)
        self.connection.query_log.append(normalized_query)
        params = params or ()

        if normalized_query.startswith("SELECT current_sequence"):
            self.pending_result = [
                {
                    "current_sequence": self.connection.current_sequence,
                    "case_id": self.connection.case_id,
                }
            ]
            return

        if normalized_query.startswith("SELECT request_hash"):
            key = (str(params[0]), str(params[1]))
            row = self.connection.idempotency_rows.get(key)
            self.pending_result = [row] if row is not None else []
            return

        if normalized_query.startswith("INSERT INTO idempotency_keys"):
            key = (str(params[0]), str(params[1]))
            self.connection.idempotency_rows[key] = {
                "request_hash": str(params[2]),
                "response_event_ids": list(params[3]),  # type: ignore[arg-type]
                "committed_at": None,
            }
            self.pending_result = []
            return

        if normalized_query.startswith("UPDATE idempotency_keys"):
            key = (str(params[1]), str(params[2]))
            self.connection.idempotency_rows[key]["response_event_ids"] = list(
                params[0]  # type: ignore[arg-type]
            )
            self.connection.idempotency_rows[key]["committed_at"] = datetime.now(UTC)
            self.pending_result = []
            return

        if normalized_query.startswith("INSERT INTO world_events"):
            row = _world_event_row_from_params(params)
            self.connection.world_event_rows.append(row)
            self.connection.world_event_insert_count += 1
            self.pending_result = []
            return

        if normalized_query.startswith("UPDATE app_sessions"):
            self.connection.current_sequence = int(params[0])
            self.pending_result = []
            return

        if normalized_query.startswith("SELECT id, case_id, session_id"):
            session_id = str(params[0])
            event_ids = {str(item) for item in params[1]} if len(params) > 1 else None
            rows = [
                row
                for row in self.connection.world_event_rows
                if row["session_id"] == session_id
                and (event_ids is None or str(row["id"]) in event_ids)
            ]
            self.pending_result = sorted(rows, key=lambda row: int(row["sequence"]))
            return

        self.pending_result = []

    def fetchone(self) -> dict[str, object] | None:
        if not self.pending_result:
            return None
        return self.pending_result[0]

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.pending_result)


def _world_event_row_from_params(params: tuple[object, ...]) -> dict[str, object]:
    return {
        "id": str(params[0]),
        "session_id": str(params[1]),
        "case_id": str(params[2]),
        "sequence": int(params[3]),
        "actor_id": str(params[4]),
        "type": str(params[5]),
        "payload": json.loads(str(params[6])),
        "caused_by_event_id": params[7],
        "idempotency_key": params[8],
        "created_at": params[9],
        "schema_version": int(params[10]),
    }


def _normalize_sql(query: str) -> str:
    return " ".join(query.split())
