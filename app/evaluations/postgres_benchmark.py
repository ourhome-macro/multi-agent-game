from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from app.agents.memory import MemoryStoreQuery
from app.cases.loader import CaseLoader
from app.domain.models import EventType, NarrativeState, SessionState, WorldEvent
from app.runtime.database import apply_schema, connect_postgres
from app.storage.postgres import (
    ConnectionLike,
    IdempotencyConflictError,
    PostgresEventStore,
    PostgresMemoryStore,
    PostgresSessionStore,
    StaleSessionSequenceError,
)

TEST_DATABASE_ENV = "AGENT_TEST_DATABASE_URL"
PRODUCTION_DATABASE_ENV = "AGENT_DATABASE_URL"
ALLOW_DB_ENV = "AGENT_POSTGRES_BENCHMARK_ALLOW_DB"
DEFAULT_CASE_PATH = Path("cases/fake_case_001")


class BenchmarkSafetyError(RuntimeError):
    pass


class BenchmarkSequenceConflict(RuntimeError):
    pass


class BenchmarkIdempotencyConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class PercentileStats:
    count: int
    min_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "min_ms": self.min_ms,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "max_ms": self.max_ms,
        }


@dataclass(frozen=True)
class BenchmarkConfig:
    mode: Literal["stub", "postgres"] = "stub"
    profile: Literal["dry", "small"] = "dry"
    sessions: int = 1
    concurrency: int = 1
    actions_per_session: int = 1
    memory_queries_per_session: int = 1
    memory_seed_count: int = 3
    events_per_action: int = 2
    traces_per_action: int = 1
    database_url: str | None = None
    case_path: Path = DEFAULT_CASE_PATH
    apply_schema: bool = False

    @classmethod
    def for_profile(
        cls,
        profile: Literal["dry", "small"],
        *,
        mode: Literal["stub", "postgres"] = "stub",
        database_url: str | None = None,
        case_path: Path = DEFAULT_CASE_PATH,
        apply_schema: bool = False,
    ) -> BenchmarkConfig:
        if profile == "small":
            return cls(
                mode=mode,
                profile=profile,
                sessions=4,
                concurrency=2,
                actions_per_session=4,
                memory_queries_per_session=3,
                memory_seed_count=8,
                database_url=database_url,
                case_path=case_path,
                apply_schema=apply_schema,
            )
        return cls(
            mode=mode,
            profile=profile,
            database_url=database_url,
            case_path=case_path,
            apply_schema=apply_schema,
        )


@dataclass(frozen=True)
class AppendResult:
    event_count: int
    trace_count: int
    replayed: bool = False


@dataclass(frozen=True)
class BenchmarkSession:
    id: str
    case_id: str
    phase: str

    def to_session_state(self) -> SessionState:
        return SessionState(
            id=self.id,
            case_id=self.case_id,
            narrative=NarrativeState(phase=self.phase),
            relationships={},
        )


@dataclass(frozen=True)
class SessionBenchmarkResult:
    session_id: str
    append_latency_ms: tuple[float, ...]
    memory_query_latency_ms: tuple[float, ...]
    memory_query_candidate_counts: tuple[int, ...]
    action_attempt_count: int
    committed_action_count: int
    idempotent_replay_count: int
    idempotency_conflict_count: int
    sequence_conflict_count: int


@dataclass(frozen=True)
class BenchmarkSummary:
    mode: str
    profile: str
    session_count: int
    concurrency: int
    action_attempt_count: int
    committed_action_count: int
    idempotent_replay_count: int
    idempotency_conflict_count: int
    sequence_conflict_count: int
    event_count: int
    trace_count: int
    memory_query_count: int
    memory_query_candidate_count: int
    memory_query_candidate_count_max: int
    total_duration_ms: float
    append_latency: PercentileStats
    memory_query_latency: PercentileStats

    def to_dict(self) -> dict[str, object]:
        average_candidates = 0.0
        if self.memory_query_count:
            average_candidates = round(
                self.memory_query_candidate_count / self.memory_query_count,
                3,
            )
        return {
            "mode": self.mode,
            "profile": self.profile,
            "session_count": self.session_count,
            "concurrency": self.concurrency,
            "action_attempt_count": self.action_attempt_count,
            "committed_action_count": self.committed_action_count,
            "idempotent_replay_count": self.idempotent_replay_count,
            "idempotency_conflict_count": self.idempotency_conflict_count,
            "sequence_conflict_count": self.sequence_conflict_count,
            "event_count": self.event_count,
            "trace_count": self.trace_count,
            "memory_query_count": self.memory_query_count,
            "memory_query_candidate_count": self.memory_query_candidate_count,
            "memory_query_candidate_count_avg": average_candidates,
            "memory_query_candidate_count_max": self.memory_query_candidate_count_max,
            "total_duration_ms": self.total_duration_ms,
            "append_latency_ms": self.append_latency.to_dict(),
            "memory_query_latency_ms": self.memory_query_latency.to_dict(),
        }


class BenchmarkBackend(Protocol):
    def create_session(self, session_index: int) -> BenchmarkSession:
        ...

    def seed_memory(self, session: BenchmarkSession, count: int) -> None:
        ...

    def load_current_sequence(self, session: BenchmarkSession) -> int:
        ...

    def append_action(
        self,
        session: BenchmarkSession,
        *,
        action_index: int,
        expected_sequence: int,
        idempotency_key: str,
        request_hash: str,
        events_per_action: int,
        traces_per_action: int,
    ) -> AppendResult:
        ...

    def query_memory_candidates(self, session: BenchmarkSession, query_index: int) -> int:
        ...

    def count_events(self, session_ids: Sequence[str]) -> int:
        ...

    def count_traces(self, session_ids: Sequence[str]) -> int:
        ...

    def close(self) -> None:
        ...


def calculate_percentile_stats(values: Sequence[float]) -> PercentileStats:
    if not values:
        return PercentileStats(
            count=0,
            min_ms=0.0,
            p50_ms=0.0,
            p95_ms=0.0,
            p99_ms=0.0,
            max_ms=0.0,
        )
    ordered = sorted(values)
    return PercentileStats(
        count=len(ordered),
        min_ms=_round_ms(ordered[0]),
        p50_ms=_round_ms(_nearest_rank(ordered, 50)),
        p95_ms=_round_ms(_nearest_rank(ordered, 95)),
        p99_ms=_round_ms(_nearest_rank(ordered, 99)),
        max_ms=_round_ms(ordered[-1]),
    )


def resolve_benchmark_database_url(
    explicit_url: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    environment = env or os.environ
    gate = environment.get(ALLOW_DB_ENV, "")
    if gate.casefold() not in {"1", "true", "yes"}:
        raise BenchmarkSafetyError(
            f"{ALLOW_DB_ENV}=1 is required before any PostgreSQL benchmark connects."
        )
    if explicit_url:
        if explicit_url == environment.get(PRODUCTION_DATABASE_ENV):
            raise BenchmarkSafetyError(
                f"Explicit --database-url matches {PRODUCTION_DATABASE_ENV}; refusing "
                "to benchmark the production runtime database."
            )
        return explicit_url
    test_url = environment.get(TEST_DATABASE_ENV)
    if test_url:
        return test_url
    if environment.get(PRODUCTION_DATABASE_ENV):
        raise BenchmarkSafetyError(
            f"{PRODUCTION_DATABASE_ENV} is intentionally ignored by this benchmark. "
            f"Set {TEST_DATABASE_ENV} or pass --database-url for a non-production database."
        )
    raise BenchmarkSafetyError(
        f"{TEST_DATABASE_ENV} is not set. Set it or pass --database-url for a "
        "non-production database."
    )


def run_benchmark(
    config: BenchmarkConfig,
    *,
    backend_factory: Callable[[], BenchmarkBackend] | None = None,
) -> BenchmarkSummary:
    _validate_config(config)
    factory = backend_factory or _default_backend_factory(config)
    started = time.perf_counter()
    results: list[SessionBenchmarkResult] = []

    with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
        futures = [
            executor.submit(_run_session_workload, factory, config, session_index)
            for session_index in range(config.sessions)
        ]
        for future in as_completed(futures):
            results.append(future.result())

    session_ids = [result.session_id for result in results]
    counting_backend = factory()
    try:
        event_count = counting_backend.count_events(session_ids)
        trace_count = counting_backend.count_traces(session_ids)
    finally:
        counting_backend.close()

    total_duration_ms = _elapsed_ms(started)
    append_latencies = [
        latency
        for result in results
        for latency in result.append_latency_ms
    ]
    memory_latencies = [
        latency
        for result in results
        for latency in result.memory_query_latency_ms
    ]
    candidate_counts = [
        count
        for result in results
        for count in result.memory_query_candidate_counts
    ]
    return BenchmarkSummary(
        mode=config.mode,
        profile=config.profile,
        session_count=len(results),
        concurrency=config.concurrency,
        action_attempt_count=sum(result.action_attempt_count for result in results),
        committed_action_count=sum(result.committed_action_count for result in results),
        idempotent_replay_count=sum(result.idempotent_replay_count for result in results),
        idempotency_conflict_count=sum(
            result.idempotency_conflict_count for result in results
        ),
        sequence_conflict_count=sum(result.sequence_conflict_count for result in results),
        event_count=event_count,
        trace_count=trace_count,
        memory_query_count=len(candidate_counts),
        memory_query_candidate_count=sum(candidate_counts),
        memory_query_candidate_count_max=max(candidate_counts, default=0),
        total_duration_ms=_round_ms(total_duration_ms),
        append_latency=calculate_percentile_stats(append_latencies),
        memory_query_latency=calculate_percentile_stats(memory_latencies),
    )


def format_summary(summary: BenchmarkSummary) -> str:
    return json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)
    try:
        summary = run_benchmark(config)
    except BenchmarkSafetyError as exc:
        print(f"PostgreSQL benchmark safety error: {exc}", file=sys.stderr)
        return 2
    print(format_summary(summary))
    return 0


def _run_session_workload(
    backend_factory: Callable[[], BenchmarkBackend],
    config: BenchmarkConfig,
    session_index: int,
) -> SessionBenchmarkResult:
    backend = backend_factory()
    append_latencies: list[float] = []
    memory_latencies: list[float] = []
    candidate_counts: list[int] = []
    action_attempt_count = 0
    committed_action_count = 0
    idempotent_replay_count = 0
    idempotency_conflict_count = 0
    sequence_conflict_count = 0
    try:
        session = backend.create_session(session_index)
        backend.seed_memory(session, config.memory_seed_count)

        for action_index in range(config.actions_per_session):
            key = f"bench-s{session_index}-a{action_index}"
            request_hash = f"sha256:bench-s{session_index}-a{action_index}"
            sequence = backend.load_current_sequence(session)

            result, latency = _timed_append(
                backend,
                session,
                action_index=action_index,
                expected_sequence=sequence,
                idempotency_key=key,
                request_hash=request_hash,
                events_per_action=config.events_per_action,
                traces_per_action=config.traces_per_action,
            )
            append_latencies.append(latency)
            action_attempt_count += 1
            if not result.replayed:
                committed_action_count += 1

            replayed, latency = _timed_append(
                backend,
                session,
                action_index=action_index,
                expected_sequence=sequence,
                idempotency_key=key,
                request_hash=request_hash,
                events_per_action=config.events_per_action,
                traces_per_action=config.traces_per_action,
            )
            append_latencies.append(latency)
            action_attempt_count += 1
            if replayed.replayed:
                idempotent_replay_count += 1

            if action_index == 0:
                started = time.perf_counter()
                try:
                    backend.append_action(
                        session,
                        action_index=action_index,
                        expected_sequence=backend.load_current_sequence(session),
                        idempotency_key=key,
                        request_hash=f"{request_hash}-conflict",
                        events_per_action=config.events_per_action,
                        traces_per_action=config.traces_per_action,
                    )
                except BenchmarkIdempotencyConflict:
                    idempotency_conflict_count += 1
                    append_latencies.append(_elapsed_ms(started))
                action_attempt_count += 1

        stale_sequence = backend.load_current_sequence(session)
        sequence_key = f"bench-s{session_index}-sequence-primer"
        _, latency = _timed_append(
            backend,
            session,
            action_index=config.actions_per_session + 1,
            expected_sequence=stale_sequence,
            idempotency_key=sequence_key,
            request_hash=f"sha256:{sequence_key}",
            events_per_action=config.events_per_action,
            traces_per_action=config.traces_per_action,
        )
        append_latencies.append(latency)
        action_attempt_count += 1
        committed_action_count += 1

        started = time.perf_counter()
        try:
            backend.append_action(
                session,
                action_index=config.actions_per_session + 2,
                expected_sequence=stale_sequence,
                idempotency_key=f"bench-s{session_index}-sequence-conflict",
                request_hash=f"sha256:bench-s{session_index}-sequence-conflict",
                events_per_action=config.events_per_action,
                traces_per_action=config.traces_per_action,
            )
        except BenchmarkSequenceConflict:
            sequence_conflict_count += 1
            append_latencies.append(_elapsed_ms(started))
        action_attempt_count += 1

        for query_index in range(config.memory_queries_per_session):
            started = time.perf_counter()
            candidate_count = backend.query_memory_candidates(session, query_index)
            memory_latencies.append(_elapsed_ms(started))
            candidate_counts.append(candidate_count)

        return SessionBenchmarkResult(
            session_id=session.id,
            append_latency_ms=tuple(append_latencies),
            memory_query_latency_ms=tuple(memory_latencies),
            memory_query_candidate_counts=tuple(candidate_counts),
            action_attempt_count=action_attempt_count,
            committed_action_count=committed_action_count,
            idempotent_replay_count=idempotent_replay_count,
            idempotency_conflict_count=idempotency_conflict_count,
            sequence_conflict_count=sequence_conflict_count,
        )
    finally:
        backend.close()


def _timed_append(
    backend: BenchmarkBackend,
    session: BenchmarkSession,
    *,
    action_index: int,
    expected_sequence: int,
    idempotency_key: str,
    request_hash: str,
    events_per_action: int,
    traces_per_action: int,
) -> tuple[AppendResult, float]:
    started = time.perf_counter()
    result = backend.append_action(
        session,
        action_index=action_index,
        expected_sequence=expected_sequence,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        events_per_action=events_per_action,
        traces_per_action=traces_per_action,
    )
    return result, _elapsed_ms(started)


class StubBenchmarkBackend:
    def __init__(self, state: _StubBenchmarkState) -> None:
        self._state = state

    def create_session(self, session_index: int) -> BenchmarkSession:
        session_id = f"stub-session-{session_index}-{uuid4()}"
        session = BenchmarkSession(
            id=session_id,
            case_id="benchmark.stub.case",
            phase="opening",
        )
        self._state.create_session(session)
        return session

    def seed_memory(self, session: BenchmarkSession, count: int) -> None:
        self._state.seed_memory(session.id, count)

    def load_current_sequence(self, session: BenchmarkSession) -> int:
        return self._state.current_sequence(session.id)

    def append_action(
        self,
        session: BenchmarkSession,
        *,
        action_index: int,
        expected_sequence: int,
        idempotency_key: str,
        request_hash: str,
        events_per_action: int,
        traces_per_action: int,
    ) -> AppendResult:
        _ = action_index
        return self._state.append_action(
            session.id,
            expected_sequence=expected_sequence,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            events_per_action=events_per_action,
            traces_per_action=traces_per_action,
        )

    def query_memory_candidates(self, session: BenchmarkSession, query_index: int) -> int:
        _ = query_index
        return self._state.memory_candidate_count(session.id)

    def count_events(self, session_ids: Sequence[str]) -> int:
        return self._state.count_events(session_ids)

    def count_traces(self, session_ids: Sequence[str]) -> int:
        return self._state.count_traces(session_ids)

    def close(self) -> None:
        return None


class PostgresBenchmarkBackend:
    def __init__(
        self,
        *,
        database_url: str,
        case_path: Path,
        should_apply_schema: bool,
    ) -> None:
        self._connection = connect_postgres(database_url)
        if should_apply_schema:
            apply_schema(self._connection)
        self._case = CaseLoader().load(case_path)
        self._event_store = PostgresEventStore(self._connection)
        self._session_store = PostgresSessionStore(
            self._connection,
            event_store=self._event_store,
        )
        self._memory_store = PostgresMemoryStore(self._connection)

    def create_session(self, session_index: int) -> BenchmarkSession:
        _ = session_index
        session = self._session_store.create(self._case)
        return BenchmarkSession(
            id=session.id,
            case_id=session.case_id,
            phase=session.narrative.phase,
        )

    def seed_memory(self, session: BenchmarkSession, count: int) -> None:
        if count <= 0:
            return
        state = session.to_session_state()
        expected_sequence = self.load_current_sequence(session)
        events = [
            _memory_snapshot_event(
                session=session,
                memory_id=f"benchmark.seed.{index}.{uuid4()}",
                content=f"Benchmark seed memory {index} for the scratched desk drawer.",
                event_suffix=f"seed.{index}",
                action_event_id=None,
            )
            for index in range(count)
        ]
        self._event_store.append(
            state,
            events,
            idempotency_key=f"benchmark-seed-{session.id}",
            request_hash=f"sha256:benchmark-seed-{session.id}-{count}",
            expected_current_sequence=expected_sequence,
        )

    def load_current_sequence(self, session: BenchmarkSession) -> int:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_sequence FROM app_sessions WHERE id = %s",
                (session.id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise KeyError(f"Unknown benchmark session: {session.id}")
        return int(row["current_sequence"])

    def append_action(
        self,
        session: BenchmarkSession,
        *,
        action_index: int,
        expected_sequence: int,
        idempotency_key: str,
        request_hash: str,
        events_per_action: int,
        traces_per_action: int,
    ) -> AppendResult:
        events = _action_events(
            session=session,
            action_index=action_index,
            events_per_action=events_per_action,
        )
        traces = [
            _runtime_trace_record(
                session=session,
                action_index=action_index,
                trace_index=trace_index,
            )
            for trace_index in range(traces_per_action)
        ]
        try:
            replayed = self._event_store.load_idempotent_response(
                session_id=session.id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        except IdempotencyConflictError as exc:
            raise BenchmarkIdempotencyConflict(str(exc)) from exc
        if replayed is not None:
            return AppendResult(event_count=len(replayed), trace_count=0, replayed=True)
        try:
            stored = self._event_store.append(
                session.to_session_state(),
                events,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expected_current_sequence=expected_sequence,
                runtime_traces=traces,
            )
        except IdempotencyConflictError as exc:
            raise BenchmarkIdempotencyConflict(str(exc)) from exc
        except StaleSessionSequenceError as exc:
            raise BenchmarkSequenceConflict(str(exc)) from exc
        return AppendResult(
            event_count=len(stored),
            trace_count=traces_per_action,
        )

    def query_memory_candidates(self, session: BenchmarkSession, query_index: int) -> int:
        _ = query_index
        candidates = self._memory_store.fetch_candidates(
            session=session.to_session_state(),
            query=MemoryStoreQuery(
                session_id=session.id,
                target_id="butler",
                phase=session.phase,
                enforce_target_visibility=True,
                scopes=("npc_private",),
                layers=("working",),
                memory_types=("episodic",),
            ),
        )
        return len(candidates)

    def count_events(self, session_ids: Sequence[str]) -> int:
        return _count_rows(self._connection, "world_events", session_ids)

    def count_traces(self, session_ids: Sequence[str]) -> int:
        return _count_rows(self._connection, "runtime_traces", session_ids)

    def close(self) -> None:
        self._connection.close()


@dataclass
class _StubSessionRow:
    current_sequence: int = 1
    event_count: int = 1
    trace_count: int = 0
    memory_count: int = 0
    idempotency: dict[str, tuple[str, int]] | None = None
    lock: threading.Lock | None = None

    def __post_init__(self) -> None:
        if self.idempotency is None:
            self.idempotency = {}
        if self.lock is None:
            self.lock = threading.Lock()


class _StubBenchmarkState:
    def __init__(self) -> None:
        self._sessions: dict[str, _StubSessionRow] = {}
        self._lock = threading.Lock()

    def create_session(self, session: BenchmarkSession) -> None:
        with self._lock:
            self._sessions[session.id] = _StubSessionRow()

    def seed_memory(self, session_id: str, count: int) -> None:
        row = self._row(session_id)
        assert row.lock is not None
        with row.lock:
            row.current_sequence += count
            row.event_count += count
            row.memory_count += count

    def current_sequence(self, session_id: str) -> int:
        row = self._row(session_id)
        assert row.lock is not None
        with row.lock:
            return row.current_sequence

    def append_action(
        self,
        session_id: str,
        *,
        expected_sequence: int,
        idempotency_key: str,
        request_hash: str,
        events_per_action: int,
        traces_per_action: int,
    ) -> AppendResult:
        row = self._row(session_id)
        assert row.idempotency is not None
        assert row.lock is not None
        with row.lock:
            stored = row.idempotency.get(idempotency_key)
            if stored is not None:
                stored_hash, stored_event_count = stored
                if stored_hash != request_hash:
                    raise BenchmarkIdempotencyConflict(
                        "Idempotency key was reused with a different request."
                    )
                return AppendResult(
                    event_count=stored_event_count,
                    trace_count=0,
                    replayed=True,
                )
            if row.current_sequence != expected_sequence:
                raise BenchmarkSequenceConflict(
                    "Session event stream advanced before append."
                )

            row.current_sequence += events_per_action
            row.event_count += events_per_action
            row.trace_count += traces_per_action
            row.memory_count += max(0, events_per_action - 1)
            row.idempotency[idempotency_key] = (request_hash, events_per_action)
            return AppendResult(event_count=events_per_action, trace_count=traces_per_action)

    def memory_candidate_count(self, session_id: str) -> int:
        row = self._row(session_id)
        assert row.lock is not None
        with row.lock:
            return row.memory_count

    def count_events(self, session_ids: Sequence[str]) -> int:
        return sum(self._row(session_id).event_count for session_id in session_ids)

    def count_traces(self, session_ids: Sequence[str]) -> int:
        return sum(self._row(session_id).trace_count for session_id in session_ids)

    def _row(self, session_id: str) -> _StubSessionRow:
        with self._lock:
            return self._sessions[session_id]


def _default_backend_factory(config: BenchmarkConfig) -> Callable[[], BenchmarkBackend]:
    if config.mode == "stub":
        state = _StubBenchmarkState()
        return lambda: StubBenchmarkBackend(state)

    database_url = resolve_benchmark_database_url(config.database_url)

    def factory() -> BenchmarkBackend:
        return PostgresBenchmarkBackend(
            database_url=database_url,
            case_path=config.case_path,
            should_apply_schema=config.apply_schema,
        )

    return factory


def _action_events(
    *,
    session: BenchmarkSession,
    action_index: int,
    events_per_action: int,
) -> list[WorldEvent]:
    event_count = max(1, events_per_action)
    inspected = _world_event(
        session=session,
        actor_id="player",
        event_type=EventType.PLAYER_INSPECTED,
        payload={
            "target_id": "desk",
            "benchmark_action_index": action_index,
        },
    )
    events = [inspected]
    for offset in range(1, event_count):
        events.append(
            _memory_snapshot_event(
                session=session,
                memory_id=f"benchmark.action.{action_index}.{offset}.{uuid4()}",
                content=(
                    "Benchmark memory: player inspected the desk and asked about "
                    "the scratched drawer."
                ),
                event_suffix=f"action.{action_index}.{offset}",
                action_event_id=inspected.id,
            )
        )
    return events


def _memory_snapshot_event(
    *,
    session: BenchmarkSession,
    memory_id: str,
    content: str,
    event_suffix: str,
    action_event_id: str | None,
) -> WorldEvent:
    event_id = f"benchmark.memory.{event_suffix}.{uuid4()}"
    return _world_event(
        session=session,
        event_id=event_id,
        actor_id="system",
        event_type=EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
        payload={
            "memory_id": memory_id,
            "rule_id": "benchmark.memory.seed",
            "memory_type": "episodic",
            "memory_scope": "npc_private",
            "memory_layer": "working",
            "subject_id": "player",
            "owner_character_id": "butler",
            "visible_to_character_ids": ["butler"],
            "content": content,
            "source_event_ids": [action_event_id or event_id],
            "source_memory_ids": [],
            "salience": 0.5,
            "confidence": 1.0,
            "visibility": "private",
            "metadata": {
                "phase_ids": ["opening", "investigation"],
                "non_authoritative": True,
            },
            "operation": "create",
        },
    )


def _world_event(
    *,
    session: BenchmarkSession,
    actor_id: str,
    event_type: EventType,
    payload: dict[str, object],
    event_id: str | None = None,
) -> WorldEvent:
    return WorldEvent(
        id=event_id or f"benchmark.event.{uuid4()}",
        case_id=session.case_id,
        session_id=session.id,
        actor_id=actor_id,
        type=event_type,
        payload=payload,
        created_at="2026-06-16T00:00:00+00:00",
    )


def _runtime_trace_record(
    *,
    session: BenchmarkSession,
    action_index: int,
    trace_index: int,
) -> dict[str, object]:
    return {
        "schema_version": 5,
        "trace_id": f"benchmark.trace.{session.id}.{action_index}.{trace_index}.{uuid4()}",
        "timestamp": "2026-06-16T00:00:00+00:00",
        "case_id": session.case_id,
        "session_id": session.id,
        "turn_id": action_index,
        "action_type": "inspect",
        "target_agent_id": "butler",
        "agent_backend": "benchmark-stub",
        "duration_ms": 1,
        "memory_projection": {
            "candidate_count": 0,
            "benchmark": True,
        },
        "director_allowed": True,
        "public_speech_source": "none",
        "security_flags": [],
        "status": "ok",
    }


def _count_rows(
    connection: ConnectionLike,
    table_name: Literal["world_events", "runtime_traces"],
    session_ids: Sequence[str],
) -> int:
    if not session_ids:
        return 0
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) AS count FROM {table_name} WHERE session_id = ANY(%s)",
            (list(session_ids),),
        )
        row = cursor.fetchone()
    return int(row["count"])


def _validate_config(config: BenchmarkConfig) -> None:
    for field_name in (
        "sessions",
        "concurrency",
        "actions_per_session",
        "memory_queries_per_session",
        "events_per_action",
    ):
        value = int(getattr(config, field_name))
        if value <= 0:
            raise ValueError(f"{field_name} must be positive")
    if config.memory_seed_count < 0:
        raise ValueError("memory_seed_count must be non-negative")
    if config.traces_per_action < 0:
        raise ValueError("traces_per_action must be non-negative")
    if config.concurrency > config.sessions:
        raise ValueError("concurrency must not exceed sessions")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase-1 PostgreSQL benchmark/smoke runner for narrative runtime.",
    )
    parser.add_argument("--mode", choices=("stub", "postgres"), default="stub")
    parser.add_argument("--profile", choices=("dry", "small"), default="dry")
    parser.add_argument("--sessions", type=int)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--actions-per-session", type=int)
    parser.add_argument("--memory-queries-per-session", type=int)
    parser.add_argument("--memory-seed-count", type=int)
    parser.add_argument("--events-per-action", type=int)
    parser.add_argument("--traces-per-action", type=int)
    parser.add_argument("--database-url")
    parser.add_argument("--case-path", type=Path, default=DEFAULT_CASE_PATH)
    parser.add_argument("--apply-schema", action="store_true")
    return parser


def _config_from_args(args: argparse.Namespace) -> BenchmarkConfig:
    config = BenchmarkConfig.for_profile(
        args.profile,
        mode=args.mode,
        database_url=args.database_url,
        case_path=args.case_path,
        apply_schema=args.apply_schema,
    )
    overrides = {
        "sessions": args.sessions,
        "concurrency": args.concurrency,
        "actions_per_session": args.actions_per_session,
        "memory_queries_per_session": args.memory_queries_per_session,
        "memory_seed_count": args.memory_seed_count,
        "events_per_action": args.events_per_action,
        "traces_per_action": args.traces_per_action,
    }
    values = {
        field: value
        for field, value in config.__dict__.items()
        if field not in overrides or overrides[field] is None
    }
    values.update({field: value for field, value in overrides.items() if value is not None})
    return BenchmarkConfig(**values)


def _nearest_rank(ordered: Sequence[float], percentile: int) -> float:
    rank = math.ceil((percentile / 100) * len(ordered))
    index = max(0, min(len(ordered) - 1, rank - 1))
    return ordered[index]


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _round_ms(value: float) -> float:
    return round(float(value), 3)


if __name__ == "__main__":
    raise SystemExit(main())
