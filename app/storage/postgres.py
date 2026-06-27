from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
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

if TYPE_CHECKING:
    from app.agents.memory import MemoryStoreQuery

DEFAULT_SCHEMA_VERSION = 1
MAX_MEMORY_QUERY_PREFILTER_TERMS = 24
DEFAULT_MEMORY_TRIGRAM_SIMILARITY_THRESHOLD = 0.35


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
        runtime_traces: Sequence[dict[str, object]] = (),
    ) -> list[StoredWorldEvent]:
        if not events and not runtime_traces:
            return []
        if events:
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
                if stored:
                    self._update_session_projection(
                        cursor,
                        session,
                        stored[-1].sequence,
                        narrative_phase=_narrative_phase_after_events(session, events),
                    )
                    self._append_runtime_traces_locked(
                        cursor,
                        session_id=session.id,
                        records=runtime_traces,
                        action_event_id=_first_action_event_id(events),
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
                self._insert_runtime_trace(cursor, record, trace_id=trace_id)
        return trace_id

    def _append_runtime_traces_locked(
        self,
        cursor: CursorLike,
        *,
        session_id: str,
        records: Sequence[dict[str, object]],
        action_event_id: str | None,
    ) -> None:
        for record in records:
            trace_id = str(record.get("trace_id") or uuid4())
            enriched = {
                **record,
                "session_id": record.get("session_id") or session_id,
                "action_event_id": record.get("action_event_id") or action_event_id,
            }
            if enriched["action_event_id"] is None:
                enriched.pop("action_event_id")
            self._insert_runtime_trace(cursor, enriched, trace_id=trace_id)

    def _insert_runtime_trace(
        self,
        cursor: CursorLike,
        record: dict[str, object],
        *,
        trace_id: str,
    ) -> None:
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


class PostgresMemoryStore:
    """Read-side candidate store for AgentMemorySnapshot retrieval.

    This is deliberately a first-stage recall over the existing projection table. The
    authoritative visibility/source/phase/plan/forbidden checks still live in
    MemoryRetriever.
    """

    backend_name = "postgres"

    def __init__(
        self,
        connection: ConnectionLike,
        *,
        enable_trigram_prefilter: bool = False,
        trigram_similarity_threshold: float = DEFAULT_MEMORY_TRIGRAM_SIMILARITY_THRESHOLD,
    ) -> None:
        if not 0.0 <= trigram_similarity_threshold <= 1.0:
            raise ValueError("trigram_similarity_threshold must be between 0.0 and 1.0")
        self._connection = connection
        self._enable_trigram_prefilter = enable_trigram_prefilter
        self._trigram_similarity_threshold = trigram_similarity_threshold

    def fetch_candidates(
        self,
        *,
        session: SessionState,
        query: MemoryStoreQuery,
    ) -> list[AgentMemorySnapshot]:
        _ = session
        clauses = ["session_id = %s"]
        params: list[object] = [query.session_id]

        if query.scopes:
            clauses.append("memory_scope = ANY(%s)")
            params.append(list(query.scopes))
        if query.layers:
            clauses.append("memory_layer = ANY(%s)")
            params.append(list(query.layers))
        if query.memory_types:
            clauses.append("memory_type = ANY(%s)")
            params.append(list(query.memory_types))
        if query.enforce_target_visibility:
            clauses.append(
                """
                (
                    (
                        memory_scope IN ('case', 'session')
                        AND (
                            cardinality(visible_to_character_ids) = 0
                            OR owner_character_id = %s
                            OR %s = ANY(visible_to_character_ids)
                        )
                    )
                    OR (
                        memory_scope IN ('npc_private', 'scene_shared')
                        AND (
                            owner_character_id = %s
                            OR %s = ANY(visible_to_character_ids)
                        )
                    )
                )
                """
            )
            params.extend(
                [
                    query.target_id,
                    query.target_id,
                    query.target_id,
                    query.target_id,
                ]
            )
        clauses.append(
            """
            (
                NOT (metadata ? 'phase_id')
                OR metadata->>'phase_id' = %s
            )
            """
        )
        params.append(query.phase)
        clauses.append(
            """
            (
                NOT (metadata ? 'phase_ids')
                OR metadata->'phase_ids' ? %s
            )
            """
        )
        params.append(query.phase)
        query_terms = _memory_query_prefilter_terms(query)
        if query_terms:
            trigram_sql = ""
            if self._enable_trigram_prefilter:
                trigram_sql = """
                       OR word_similarity(query_term.term, content) >= %s
                       OR word_similarity(query_term.term, memory_id) >= %s
                       OR word_similarity(query_term.term, metadata::text) >= %s
                       OR EXISTS (
                           SELECT 1
                           FROM unnest(
                               COALESCE(source_event_ids, ARRAY[]::text[])
                               || COALESCE(source_memory_ids, ARRAY[]::text[])
                           ) AS fuzzy_source_ref(value)
                           WHERE word_similarity(
                               query_term.term,
                               fuzzy_source_ref.value
                           ) >= %s
                       )
                """
            clauses.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM unnest(%s::text[]) AS query_term(term)
                    WHERE memory_id ILIKE ('%%' || query_term.term || '%%')
                       OR content ILIKE ('%%' || query_term.term || '%%')
                       OR EXISTS (
                           SELECT 1
                           FROM unnest(
                               COALESCE(source_event_ids, ARRAY[]::text[])
                               || COALESCE(source_memory_ids, ARRAY[]::text[])
                           ) AS source_ref(value)
                           WHERE source_ref.value ILIKE ('%%' || query_term.term || '%%')
                       )
                       OR metadata::text ILIKE ('%%' || query_term.term || '%%')
                       OR metadata ? query_term.term
                       OR (metadata->'topic_tags') ? query_term.term
                       OR (metadata->'adjacent_clue_ids') ? query_term.term
                       OR (metadata->'reveals_world_info') ? query_term.term
                       OR to_tsvector(
                           'simple',
                           concat_ws(
                               ' ',
                               memory_id,
                               content,
                               array_to_string(
                                   COALESCE(source_event_ids, ARRAY[]::text[]),
                                   ' '
                               ),
                               array_to_string(
                                   COALESCE(source_memory_ids, ARRAY[]::text[]),
                                   ' '
                               ),
                               metadata::text
                           )
                       ) @@ plainto_tsquery('simple', query_term.term)
                       {trigram_sql}
                )
                """
            )
            params.append(list(query_terms))
            if self._enable_trigram_prefilter:
                params.extend([self._trigram_similarity_threshold] * 4)

        sql = f"""
            SELECT
                memory_id, rule_id, memory_type, memory_scope, memory_layer,
                last_operation, subject_id, owner_character_id, visible_to_character_ids,
                content, source_event_ids, source_memory_ids, salience, confidence,
                visibility, metadata, last_updated_event_id, created_at, updated_at
            FROM memory_snapshots
            WHERE {" AND ".join(f"({clause})" for clause in clauses)}
            ORDER BY updated_at DESC, memory_id
        """
        with _transaction(self._connection):
            with _cursor(self._connection) as cursor:
                cursor.execute(sql, tuple(params))
                return [_memory_snapshot_from_row(row) for row in cursor.fetchall()]


def _memory_query_prefilter_terms(query: MemoryStoreQuery) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    raw_terms = (*query.query_anchors, *query.query_tokens)
    for item in raw_terms:
        term = " ".join(str(item).casefold().split())
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= MAX_MEMORY_QUERY_PREFILTER_TERMS:
            break
    return tuple(terms)


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


def _memory_snapshot_from_row(row: Any) -> AgentMemorySnapshot:
    return AgentMemorySnapshot(
        memory_id=str(_row_get(row, "memory_id", 0)),
        rule_id=_optional_text(_row_get(row, "rule_id", 1)),
        memory_type=str(_row_get(row, "memory_type", 2)),
        memory_scope=str(_row_get(row, "memory_scope", 3)),
        memory_layer=str(_row_get(row, "memory_layer", 4)),
        last_operation=_row_get(row, "last_operation", 5),
        subject_id=_optional_text(_row_get(row, "subject_id", 6)),
        owner_character_id=_optional_text(_row_get(row, "owner_character_id", 7)),
        visible_to_character_ids=_string_list(
            _row_get(row, "visible_to_character_ids", 8)
        ),
        content=str(_row_get(row, "content", 9)),
        source_event_ids=_string_list(_row_get(row, "source_event_ids", 10)),
        source_memory_ids=_string_list(_row_get(row, "source_memory_ids", 11)),
        salience=float(_row_get(row, "salience", 12)),
        confidence=float(_row_get(row, "confidence", 13)),
        visibility=str(_row_get(row, "visibility", 14)),
        metadata=_json_object(_row_get(row, "metadata", 15)),
        last_updated_event_id=str(_row_get(row, "last_updated_event_id", 16)),
        created_at=_datetime_to_iso(_row_get(row, "created_at", 17)),
        updated_at=_datetime_to_iso(_row_get(row, "updated_at", 18)),
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


def _first_action_event_id(events: Sequence[WorldEvent]) -> str | None:
    for event in events:
        if event.actor_id == "player":
            return event.id
    return events[0].id if events else None


def _memory_operation_from_event(event: WorldEvent) -> MemoryOperation:
    return normalize_memory_operation(
        event.payload.get("operation") or event.payload.get("last_operation")
    )
