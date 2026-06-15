from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from app.domain.models import (
    AgentMemorySnapshot,
    CasePackage,
    CharacterFactAwarenessState,
    CharacterImpression,
    EventType,
    MemoryOperation,
    NarrativeState,
    RelationshipState,
    SessionState,
    WorldEvent,
    normalize_memory_operation,
    serialize_memory_operation,
)
from app.rules.engine import relationship_key
from app.runtime.character_fact_awareness import build_initial_character_fact_awareness
from app.runtime.events import make_event
from app.runtime.replay import replay_events

DEFAULT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StoredWorldEvent:
    event: WorldEvent
    sequence: int
    schema_version: int = DEFAULT_SCHEMA_VERSION


class PostgresPersistenceError(RuntimeError):
    pass


class UnknownSessionError(PostgresPersistenceError):
    pass


class IdempotencyConflictError(PostgresPersistenceError):
    pass


class IdempotencyInProgressError(PostgresPersistenceError):
    pass


class StaleSessionSequenceError(PostgresPersistenceError):
    pass


class CursorLike(Protocol):
    def execute(self, query: str, params: Sequence[object] | None = None) -> Any:
        ...

    def fetchone(self) -> Any:
        ...

    def fetchall(self) -> Sequence[Any]:
        ...


class ConnectionLike(Protocol):
    def cursor(self) -> Any:
        ...

    def commit(self) -> Any:
        ...

    def rollback(self) -> Any:
        ...


class PostgresEventStore:
    """Append-only event store backed by PostgreSQL.

    The domain WorldEvent intentionally remains free of storage sequencing. This store
    allocates session-local sequence numbers inside the database transaction and returns
    them as StoredWorldEvent metadata.
    """

    def __init__(
        self,
        connection: ConnectionLike,
        *,
        schema_version: int = DEFAULT_SCHEMA_VERSION,
    ) -> None:
        self._connection = connection
        self._schema_version = schema_version

    def append(
        self,
        session: SessionState,
        events: Sequence[WorldEvent],
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        expected_current_sequence: int | None = None,
    ) -> list[StoredWorldEvent]:
        if not events:
            return []
        _validate_event_batch(session, events)
        effective_hash = request_hash or request_hash_for_events(events)

        with _transaction(self._connection):
            with _cursor(self._connection) as cursor:
                current_sequence = self._lock_session(cursor, session)
                if idempotency_key is not None:
                    replayed = self._claim_or_replay_idempotency_key(
                        cursor,
                        session_id=session.id,
                        idempotency_key=idempotency_key,
                        request_hash=effective_hash,
                    )
                    if replayed is not None:
                        return replayed
                if (
                    expected_current_sequence is not None
                    and current_sequence != expected_current_sequence
                ):
                    raise StaleSessionSequenceError(
                        "Session event stream advanced from "
                        f"{expected_current_sequence} to {current_sequence}"
                    )

                stored = self._append_locked(
                    cursor,
                    session=session,
                    events=events,
                    starting_sequence=current_sequence + 1,
                    idempotency_key=idempotency_key,
                )
                self._update_session_projection(
                    cursor,
                    session,
                    stored[-1].sequence,
                    narrative_phase=_narrative_phase_after_events(session, events),
                )
                if idempotency_key is not None:
                    self._commit_idempotency_key(
                        cursor,
                        session_id=session.id,
                        idempotency_key=idempotency_key,
                        response_event_ids=[item.event.id for item in stored],
                    )
                return stored

    def load(self, session_id: str) -> list[WorldEvent]:
        with _transaction(self._connection):
            with _cursor(self._connection) as cursor:
                cursor.execute(
                    """
                    SELECT id, case_id, session_id, actor_id, type, payload,
                           caused_by_event_id, created_at, sequence, schema_version
                    FROM world_events
                    WHERE session_id = %s
                    ORDER BY sequence
                    """,
                    (session_id,),
                )
                return [_event_from_row(row) for row in cursor.fetchall()]

    def load_stored(self, session_id: str) -> list[StoredWorldEvent]:
        with _transaction(self._connection):
            with _cursor(self._connection) as cursor:
                cursor.execute(
                    """
                    SELECT id, case_id, session_id, actor_id, type, payload,
                           caused_by_event_id, created_at, sequence, schema_version
                    FROM world_events
                    WHERE session_id = %s
                    ORDER BY sequence
                    """,
                    (session_id,),
                )
                return [_stored_event_from_row(row) for row in cursor.fetchall()]

    def load_idempotent_response(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> list[StoredWorldEvent] | None:
        with _transaction(self._connection):
            with _cursor(self._connection) as cursor:
                cursor.execute(
                    """
                    SELECT request_hash, response_event_ids, committed_at
                    FROM idempotency_keys
                    WHERE session_id = %s AND idempotency_key = %s
                    """,
                    (session_id, idempotency_key),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                stored_hash = str(_row_get(row, "request_hash", 0))
                if stored_hash != request_hash:
                    raise IdempotencyConflictError(
                        f"Idempotency key {idempotency_key!r} was reused "
                        "with a different request"
                    )
                response_event_ids = _string_list(_row_get(row, "response_event_ids", 1))
                if not response_event_ids:
                    raise IdempotencyInProgressError(
                        f"Idempotency key {idempotency_key!r} exists without committed events"
                    )
                return self._load_by_ids(cursor, session_id, response_event_ids)

    def append_runtime_trace(self, record: dict[str, object]) -> str:
        trace_id = str(record.get("trace_id") or uuid4())
        with _transaction(self._connection):
            with _cursor(self._connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO runtime_traces (
                        id, session_id, action_event_id, target_character_id, backend,
                        memory_projection, director_decision, llm_error_type, payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                    """,
                    (
                        trace_id,
                        str(record["session_id"]),
                        _optional_text(record.get("action_event_id")),
                        _optional_text(record.get("target_agent_id")),
                        str(record.get("agent_backend") or record.get("backend") or "unknown"),
                        _json_dumps(record.get("memory_projection") or {}),
                        _json_dumps(_director_decision_from_trace(record)),
                        _optional_text(record.get("error_category")),
                        _json_dumps(record),
                    ),
                )
        return trace_id

    def _lock_session(self, cursor: CursorLike, session: SessionState) -> int:
        cursor.execute(
            """
            SELECT current_sequence, case_id
            FROM app_sessions
            WHERE id = %s
            FOR UPDATE
            """,
            (session.id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise UnknownSessionError(f"Unknown session_id: {session.id}")
        case_id = str(_row_get(row, "case_id", 1))
        if case_id != session.case_id:
            raise PostgresPersistenceError(
                f"Session {session.id} belongs to case {case_id}, not {session.case_id}"
            )
        return int(_row_get(row, "current_sequence", 0))

    def _claim_or_replay_idempotency_key(
        self,
        cursor: CursorLike,
        *,
        session_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> list[StoredWorldEvent] | None:
        cursor.execute(
            """
            SELECT request_hash, response_event_ids, committed_at
            FROM idempotency_keys
            WHERE session_id = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (session_id, idempotency_key),
        )
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                """
                INSERT INTO idempotency_keys (
                    session_id, idempotency_key, request_hash, response_event_ids
                )
                VALUES (%s, %s, %s, %s)
                """,
                (session_id, idempotency_key, request_hash, []),
            )
            return None

        stored_hash = str(_row_get(row, "request_hash", 0))
        if stored_hash != request_hash:
            raise IdempotencyConflictError(
                f"Idempotency key {idempotency_key!r} was reused with a different request"
            )
        response_event_ids = _string_list(_row_get(row, "response_event_ids", 1))
        if not response_event_ids:
            raise IdempotencyInProgressError(
                f"Idempotency key {idempotency_key!r} exists without committed events"
            )
        return self._load_by_ids(cursor, session_id, response_event_ids)

    def _append_locked(
        self,
        cursor: CursorLike,
        *,
        session: SessionState,
        events: Sequence[WorldEvent],
        starting_sequence: int,
        idempotency_key: str | None,
    ) -> list[StoredWorldEvent]:
        stored: list[StoredWorldEvent] = []
        for offset, event in enumerate(events):
            sequence = starting_sequence + offset
            event_payload = event.model_dump(mode="json")
            cursor.execute(
                """
                INSERT INTO world_events (
                    id, session_id, case_id, sequence, actor_id, type, payload,
                    caused_by_event_id, idempotency_key, created_at, schema_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                """,
                (
                    event.id,
                    event.session_id,
                    event.case_id,
                    sequence,
                    event.actor_id,
                    event.type.value,
                    _json_dumps(event_payload["payload"]),
                    event.caused_by_event_id,
                    idempotency_key,
                    _parse_datetime(event.created_at),
                    self._schema_version,
                ),
            )
            stored_event = StoredWorldEvent(
                event=event,
                sequence=sequence,
                schema_version=self._schema_version,
            )
            self._apply_projection(cursor, stored_event)
            stored.append(stored_event)
        return stored

    def _update_session_projection(
        self,
        cursor: CursorLike,
        session: SessionState,
        current_sequence: int,
        *,
        narrative_phase: str | None = None,
    ) -> None:
        cursor.execute(
            """
            UPDATE app_sessions
            SET current_sequence = %s,
                current_version = current_version + 1,
                narrative_phase = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (current_sequence, narrative_phase or session.narrative.phase, session.id),
        )

    def _commit_idempotency_key(
        self,
        cursor: CursorLike,
        *,
        session_id: str,
        idempotency_key: str,
        response_event_ids: list[str],
    ) -> None:
        cursor.execute(
            """
            UPDATE idempotency_keys
            SET response_event_ids = %s,
                committed_at = now()
            WHERE session_id = %s AND idempotency_key = %s
            """,
            (response_event_ids, session_id, idempotency_key),
        )

    def _load_by_ids(
        self,
        cursor: CursorLike,
        session_id: str,
        event_ids: list[str],
    ) -> list[StoredWorldEvent]:
        cursor.execute(
            """
            SELECT id, case_id, session_id, actor_id, type, payload,
                   caused_by_event_id, created_at, sequence, schema_version
            FROM world_events
            WHERE session_id = %s AND id = ANY(%s)
            """,
            (session_id, event_ids),
        )
        events_by_id = {
            item.event.id: item
            for item in (_stored_event_from_row(row) for row in cursor.fetchall())
        }
        return [events_by_id[event_id] for event_id in event_ids if event_id in events_by_id]

    def _apply_projection(self, cursor: CursorLike, stored_event: StoredWorldEvent) -> None:
        event = stored_event.event
        if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED:
            self._upsert_memory_snapshot(cursor, event)
            return
        if event.type == EventType.CHARACTER_IMPRESSION_UPDATED:
            self._upsert_character_impression(cursor, event)
            return
        if event.type == EventType.CHARACTER_FACT_AWARENESS_UPDATED:
            self._upsert_character_fact_awareness(cursor, event)
            return
        if event.type == EventType.NARRATIVE_PHASE_CHANGED:
            phase = str(event.payload.get("phase") or event.payload.get("to_phase") or "")
            if phase:
                cursor.execute(
                    """
                    UPDATE app_sessions
                    SET narrative_phase = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (phase, event.session_id),
                )

    def _upsert_memory_snapshot(self, cursor: CursorLike, event: WorldEvent) -> None:
        snapshot = AgentMemorySnapshot.model_validate(_snapshot_payload_from_event(event))
        cursor.execute(
            """
            INSERT INTO memory_snapshots (
                session_id, memory_id, rule_id, memory_type, memory_scope, memory_layer,
                last_operation, subject_id, owner_character_id, visible_to_character_ids, content,
                source_event_ids, source_memory_ids, salience, confidence, visibility,
                metadata, last_updated_event_id, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s, %s, %s
            )
            ON CONFLICT (session_id, memory_id) DO UPDATE
            SET rule_id = EXCLUDED.rule_id,
                memory_type = EXCLUDED.memory_type,
                memory_scope = EXCLUDED.memory_scope,
                memory_layer = EXCLUDED.memory_layer,
                last_operation = EXCLUDED.last_operation,
                subject_id = EXCLUDED.subject_id,
                owner_character_id = EXCLUDED.owner_character_id,
                visible_to_character_ids = EXCLUDED.visible_to_character_ids,
                content = EXCLUDED.content,
                source_event_ids = EXCLUDED.source_event_ids,
                source_memory_ids = EXCLUDED.source_memory_ids,
                salience = EXCLUDED.salience,
                confidence = EXCLUDED.confidence,
                visibility = EXCLUDED.visibility,
                metadata = EXCLUDED.metadata,
                last_updated_event_id = EXCLUDED.last_updated_event_id,
                updated_at = EXCLUDED.updated_at
            """,
            (
                event.session_id,
                snapshot.memory_id,
                snapshot.rule_id,
                snapshot.memory_type,
                snapshot.memory_scope,
                snapshot.memory_layer,
                serialize_memory_operation(snapshot.last_operation),
                snapshot.subject_id,
                snapshot.owner_character_id,
                list(snapshot.visible_to_character_ids),
                snapshot.content,
                list(snapshot.source_event_ids),
                list(snapshot.source_memory_ids),
                snapshot.salience,
                snapshot.confidence,
                snapshot.visibility,
                _json_dumps(snapshot.metadata),
                event.id,
                _parse_datetime(snapshot.created_at or event.created_at),
                _parse_datetime(snapshot.updated_at or event.created_at),
            ),
        )
        operation = _memory_operation_from_event(event)
        cursor.execute(
            """
            INSERT INTO memory_operations (
                session_id, memory_id, operation, source_event_id, payload
            )
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                event.session_id,
                snapshot.memory_id,
                serialize_memory_operation(operation),
                event.id,
                _json_dumps(event.payload),
            ),
        )

    def _upsert_character_impression(self, cursor: CursorLike, event: WorldEvent) -> None:
        impression = CharacterImpression.model_validate(event.payload)
        cursor.execute(
            """
            INSERT INTO character_impressions (
                session_id, observer_id, target_id, trust, suspicion, fear,
                current_strategy, source_memory_ids, source_event_ids, payload,
                last_updated_event_id, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (session_id, observer_id, target_id) DO UPDATE
            SET trust = EXCLUDED.trust,
                suspicion = EXCLUDED.suspicion,
                fear = EXCLUDED.fear,
                current_strategy = EXCLUDED.current_strategy,
                source_memory_ids = EXCLUDED.source_memory_ids,
                source_event_ids = EXCLUDED.source_event_ids,
                payload = EXCLUDED.payload,
                last_updated_event_id = EXCLUDED.last_updated_event_id,
                updated_at = EXCLUDED.updated_at
            """,
            (
                event.session_id,
                impression.observer_id,
                impression.target_id,
                impression.trust,
                impression.suspicion,
                impression.fear,
                impression.current_strategy,
                list(impression.source_memory_ids),
                list(impression.source_event_ids),
                _json_dumps(impression.model_dump(mode="json")),
                event.id,
                _parse_datetime(event.created_at),
            ),
        )

    def _upsert_character_fact_awareness(self, cursor: CursorLike, event: WorldEvent) -> None:
        awareness = CharacterFactAwarenessState.model_validate(event.payload)
        cursor.execute(
            """
            INSERT INTO character_fact_awareness (
                session_id, awareness_id, character_id, world_info_id, stance, confidence,
                source_type, source_refs, evidence_clue_ids, source_event_ids,
                last_updated_event_id, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id, awareness_id) DO UPDATE
            SET character_id = EXCLUDED.character_id,
                world_info_id = EXCLUDED.world_info_id,
                stance = EXCLUDED.stance,
                confidence = EXCLUDED.confidence,
                source_type = EXCLUDED.source_type,
                source_refs = EXCLUDED.source_refs,
                evidence_clue_ids = EXCLUDED.evidence_clue_ids,
                source_event_ids = EXCLUDED.source_event_ids,
                last_updated_event_id = EXCLUDED.last_updated_event_id,
                updated_at = EXCLUDED.updated_at
            """,
            (
                event.session_id,
                awareness.awareness_id,
                awareness.character_id,
                awareness.world_info_id,
                awareness.stance.value,
                awareness.confidence,
                awareness.source_type.value,
                list(awareness.source_refs),
                list(awareness.evidence_clue_ids),
                list(awareness.source_event_ids),
                event.id,
                _parse_datetime(event.created_at),
            ),
        )


class PostgresSessionStore:
    def __init__(
        self,
        connection: ConnectionLike,
        *,
        event_store: PostgresEventStore | None = None,
    ) -> None:
        self._connection = connection
        self._event_store = event_store or PostgresEventStore(connection)

    def create(self, package: CasePackage) -> SessionState:
        session = SessionState(
            id=str(uuid4()),
            case_id=package.meta.id,
            narrative=NarrativeState(phase=package.meta.initial_phase),
            relationships={
                relationship_key(item.source_id, item.target_id): RelationshipState(
                    **item.model_dump()
                )
                for item in package.relationships
            },
        )
        session.character_fact_awareness = build_initial_character_fact_awareness(package)
        created_event = make_event(
            case_id=session.case_id,
            session_id=session.id,
            actor_id="system",
            event_type=EventType.SESSION_CREATED,
            payload={
                "case_id": package.meta.id,
                "initial_phase": package.meta.initial_phase,
            },
        )

        with _transaction(self._connection):
            with _cursor(self._connection) as cursor:
                cursor.execute(
                    """
                    INSERT INTO app_sessions (
                        id, case_id, current_sequence, current_version, narrative_phase
                    )
                    VALUES (%s, %s, 0, 0, %s)
                    """,
                    (session.id, session.case_id, session.narrative.phase),
                )
                self._event_store._append_locked(
                    cursor,
                    session=session,
                    events=[created_event],
                    starting_sequence=1,
                    idempotency_key=None,
                )
                self._event_store._update_session_projection(cursor, session, 1)

        session.events.append(created_event)
        return session

    def get_case_id(self, session_id: str) -> str:
        with _transaction(self._connection):
            with _cursor(self._connection) as cursor:
                cursor.execute(
                    """
                    SELECT case_id
                    FROM app_sessions
                    WHERE id = %s
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise UnknownSessionError(f"Unknown session_id: {session_id}")
        return str(_row_get(row, "case_id", 0))

    def get(self, session_id: str, package: CasePackage) -> SessionState:
        case_id = self.get_case_id(session_id)
        if case_id != package.meta.id:
            raise PostgresPersistenceError(
                f"Session {session_id} belongs to case {case_id}, not {package.meta.id}"
            )
        events = self._event_store.load(session_id)
        if not events:
            raise PostgresPersistenceError(f"Session {session_id} has no event stream")
        return replay_events(package, events)

    def append_events(
        self,
        session: SessionState,
        events: Sequence[WorldEvent],
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        expected_current_sequence: int | None = None,
    ) -> list[StoredWorldEvent]:
        return self._event_store.append(
            session,
            events,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            expected_current_sequence=expected_current_sequence,
        )


def request_hash_for_events(events: Sequence[WorldEvent]) -> str:
    payload = [event.model_dump(mode="json") for event in events]
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_event_batch(session: SessionState, events: Sequence[WorldEvent]) -> None:
    for event in events:
        if event.session_id != session.id:
            raise PostgresPersistenceError(
                f"Event {event.id} belongs to session {event.session_id}, not {session.id}"
            )
        if event.case_id != session.case_id:
            raise PostgresPersistenceError(
                f"Event {event.id} belongs to case {event.case_id}, not {session.case_id}"
            )


@contextmanager
def _transaction(connection: ConnectionLike) -> Any:
    transaction = getattr(connection, "transaction", None)
    if callable(transaction):
        with transaction():
            yield
        return
    try:
        yield
    except Exception:
        connection.rollback()
        raise
    connection.commit()


@contextmanager
def _cursor(connection: ConnectionLike) -> Any:
    raw_cursor = connection.cursor()
    if hasattr(raw_cursor, "__enter__"):
        with raw_cursor as cursor:
            yield cursor
        return
    try:
        yield raw_cursor
    finally:
        close = getattr(raw_cursor, "close", None)
        if callable(close):
            close()


def _event_from_row(row: Any) -> WorldEvent:
    return _stored_event_from_row(row).event


def _stored_event_from_row(row: Any) -> StoredWorldEvent:
    payload = _row_get(row, "payload", 5)
    event = WorldEvent(
        id=str(_row_get(row, "id", 0)),
        case_id=str(_row_get(row, "case_id", 1)),
        session_id=str(_row_get(row, "session_id", 2)),
        actor_id=str(_row_get(row, "actor_id", 3)),
        type=EventType(str(_row_get(row, "type", 4))),
        payload=_json_object(payload),
        caused_by_event_id=_optional_text(_row_get(row, "caused_by_event_id", 6)),
        created_at=_datetime_to_iso(_row_get(row, "created_at", 7)),
    )
    return StoredWorldEvent(
        event=event,
        sequence=int(_row_get(row, "sequence", 8)),
        schema_version=int(_row_get(row, "schema_version", 9)),
    )


def _row_get(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError):
        return row[index]


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise PostgresPersistenceError("Expected JSON object payload from world_events")


def _datetime_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    return str(value)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return [str(value)]


def _director_decision_from_trace(record: dict[str, object]) -> dict[str, object]:
    return {
        "director_allowed": record.get("director_allowed"),
        "director_reason_category": record.get("director_reason_category"),
        "public_speech_source": record.get("public_speech_source"),
        "security_flags": record.get("security_flags") or [],
    }


def _snapshot_payload_from_event(event: WorldEvent) -> dict[str, object]:
    keys = {
        "memory_id",
        "rule_id",
        "memory_type",
        "memory_scope",
        "memory_layer",
        "subject_id",
        "owner_character_id",
        "visible_to_character_ids",
        "content",
        "source_event_ids",
        "source_memory_ids",
        "salience",
        "confidence",
        "visibility",
        "metadata",
    }
    payload = {key: event.payload[key] for key in keys if key in event.payload}
    payload["last_operation"] = event.payload.get("last_operation") or event.payload.get(
        "operation"
    )
    payload["last_updated_event_id"] = event.id
    payload["created_at"] = event.payload.get("created_at") or event.created_at
    payload["updated_at"] = event.payload.get("updated_at") or event.created_at
    return payload


def _narrative_phase_after_events(
    session: SessionState,
    events: Sequence[WorldEvent],
) -> str:
    phase = session.narrative.phase
    for event in events:
        if event.type == EventType.NARRATIVE_PHASE_CHANGED:
            phase = str(event.payload.get("phase") or event.payload.get("to_phase") or phase)
    return phase


def _memory_operation_from_event(event: WorldEvent) -> MemoryOperation:
    return normalize_memory_operation(
        event.payload.get("operation") or event.payload.get("last_operation")
    )
