from __future__ import annotations

import json

import pytest

from app.evaluations.postgres_benchmark import (
    ALLOW_DB_ENV,
    PRODUCTION_DATABASE_ENV,
    TEST_DATABASE_ENV,
    BenchmarkConfig,
    BenchmarkSafetyError,
    calculate_percentile_stats,
    format_summary,
    resolve_benchmark_database_url,
    run_benchmark,
)


def test_percentile_stats_use_nearest_rank_and_keep_empty_summary_stable() -> None:
    empty = calculate_percentile_stats([])
    stats = calculate_percentile_stats([100.0, 1.0, 10.0, 50.0, 5.0])

    assert empty.to_dict() == {
        "count": 0,
        "min_ms": 0.0,
        "p50_ms": 0.0,
        "p95_ms": 0.0,
        "p99_ms": 0.0,
        "max_ms": 0.0,
    }
    assert stats.to_dict() == {
        "count": 5,
        "min_ms": 1.0,
        "p50_ms": 10.0,
        "p95_ms": 100.0,
        "p99_ms": 100.0,
        "max_ms": 100.0,
    }


def test_database_url_resolution_requires_explicit_gate() -> None:
    env = {
        TEST_DATABASE_ENV: "postgresql://agent_test:secret@localhost:5432/agent_test",
    }

    with pytest.raises(BenchmarkSafetyError, match=ALLOW_DB_ENV):
        resolve_benchmark_database_url(env=env)


def test_database_url_resolution_uses_test_url_and_ignores_production_url() -> None:
    env = {
        ALLOW_DB_ENV: "1",
        TEST_DATABASE_ENV: "postgresql://agent_test:secret@localhost:5432/agent_test",
        PRODUCTION_DATABASE_ENV: "postgresql://agent_prod:secret@prod:5432/agent",
    }

    assert (
        resolve_benchmark_database_url(env=env)
        == "postgresql://agent_test:secret@localhost:5432/agent_test"
    )


def test_database_url_resolution_rejects_default_production_database_url() -> None:
    production_url = "postgresql://agent_prod:secret@prod:5432/agent"
    env = {
        ALLOW_DB_ENV: "1",
        PRODUCTION_DATABASE_ENV: production_url,
    }

    with pytest.raises(BenchmarkSafetyError, match=PRODUCTION_DATABASE_ENV) as exc_info:
        resolve_benchmark_database_url(env=env)
    assert production_url not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


def test_database_url_resolution_rejects_explicit_url_matching_production_url() -> None:
    production_url = "postgresql://agent_prod:secret@prod:5432/agent"
    env = {
        ALLOW_DB_ENV: "1",
        TEST_DATABASE_ENV: "postgresql://agent_test:secret@localhost:5432/agent_test",
        PRODUCTION_DATABASE_ENV: production_url,
    }

    with pytest.raises(BenchmarkSafetyError, match="matches AGENT_DATABASE_URL") as exc_info:
        resolve_benchmark_database_url(production_url, env=env)
    assert production_url not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


def test_stub_benchmark_outputs_required_phase_one_summary_fields() -> None:
    summary = run_benchmark(
        BenchmarkConfig(
            mode="stub",
            profile="dry",
            sessions=2,
            concurrency=2,
            actions_per_session=2,
            memory_queries_per_session=2,
            memory_seed_count=3,
            events_per_action=2,
            traces_per_action=1,
        )
    )
    rendered = json.loads(format_summary(summary))
    rendered_text = format_summary(summary)

    assert rendered["mode"] == "stub"
    assert rendered["event_count"] == 20
    assert rendered["trace_count"] == 6
    assert rendered["memory_query_count"] == 4
    assert rendered["memory_query_candidate_count"] == 24
    assert rendered["memory_query_candidate_count_max"] == 6
    assert rendered["committed_action_count"] == 6
    assert rendered["idempotent_replay_count"] == 4
    assert rendered["idempotency_conflict_count"] == 2
    assert rendered["sequence_conflict_count"] == 2
    assert rendered["append_latency_ms"]["p50_ms"] >= 0.0
    assert rendered["append_latency_ms"]["p95_ms"] >= 0.0
    assert rendered["append_latency_ms"]["p99_ms"] >= 0.0
    assert rendered["memory_query_latency_ms"]["p95_ms"] >= 0.0
    assert "postgresql://" not in rendered_text
    assert "secret" not in rendered_text


def test_postgres_mode_does_not_fall_back_to_agent_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ALLOW_DB_ENV, "1")
    monkeypatch.setenv(
        PRODUCTION_DATABASE_ENV,
        "postgresql://agent_prod:secret@prod:5432/agent",
    )
    monkeypatch.delenv(TEST_DATABASE_ENV, raising=False)

    with pytest.raises(BenchmarkSafetyError, match=PRODUCTION_DATABASE_ENV):
        run_benchmark(
            BenchmarkConfig(
                mode="postgres",
                profile="dry",
                sessions=1,
                concurrency=1,
                actions_per_session=1,
                memory_queries_per_session=1,
            )
        )
