# PostgreSQL Benchmark Phase 1

## Scope

This phase adds a safe smoke/benchmark runner for the PostgreSQL-backed runtime
persistence path. It focuses on first-order operational signals:

- concurrent session workloads
- idempotency replay
- sequence conflict rejection
- memory candidate query latency
- event and runtime trace counts

The benchmark is intentionally small by default. It is a smoke tool, not a
capacity claim.

## Safety Boundary

PostgreSQL is the authoritative persistence layer for runtime events. The
benchmark must never accidentally target the production runtime database.

Rules enforced by `app.evaluations.postgres_benchmark`:

- default mode is `stub`; no database connection is opened
- PostgreSQL mode requires `AGENT_POSTGRES_BENCHMARK_ALLOW_DB=1`
- PostgreSQL mode uses `AGENT_TEST_DATABASE_URL` by default
- `AGENT_DATABASE_URL` is ignored for benchmark resolution
- if an explicit `--database-url` exactly matches `AGENT_DATABASE_URL`, the run
  is rejected
- summaries do not print database URLs, usernames, hosts, or passwords

## Default Smoke

Run without a database:

```powershell
py -3.12 -m app.scripts.postgres_benchmark --mode stub --profile dry
```

The output is JSON and includes:

- `append_latency_ms.p50_ms`
- `append_latency_ms.p95_ms`
- `append_latency_ms.p99_ms`
- `memory_query_latency_ms.p50_ms`
- `memory_query_latency_ms.p95_ms`
- `memory_query_latency_ms.p99_ms`
- `event_count`
- `trace_count`
- `memory_query_candidate_count`
- `memory_query_candidate_count_avg`
- `memory_query_candidate_count_max`
- `idempotent_replay_count`
- `idempotency_conflict_count`
- `sequence_conflict_count`

## PostgreSQL Smoke

Use a disposable or local test database only:

```powershell
$env:AGENT_TEST_DATABASE_URL = "postgresql://agent_test:***@localhost:5432/agent_test"
$env:AGENT_POSTGRES_BENCHMARK_ALLOW_DB = "1"
py -3.12 -m app.scripts.postgres_benchmark --mode postgres --profile dry --apply-schema
```

Use `--apply-schema` only for an empty or disposable database. It applies the
runtime schema but does not drop existing data.

For a slightly broader local run:

```powershell
$env:AGENT_POSTGRES_BENCHMARK_ALLOW_DB = "1"
py -3.12 -m app.scripts.postgres_benchmark --mode postgres --profile small
```

An explicit non-production URL is allowed, but still requires the gate:

```powershell
$env:AGENT_POSTGRES_BENCHMARK_ALLOW_DB = "1"
py -3.12 -m app.scripts.postgres_benchmark `
  --mode postgres `
  --profile dry `
  --database-url "postgresql://agent_test:***@localhost:5432/agent_test"
```

Do not put real credentials in committed docs, shell history snippets, or issue
comments.

## Current Limitations

- The workload uses deterministic synthetic events and trace records.
- It measures persistence mechanics and memory projection query candidate count,
  not full LLM latency.
- It does not reset schema or delete data; use a disposable database when
  comparing runs.
- It reports latency from the runner process, so numbers include Python overhead.

## Test Command

```powershell
py -3.12 -m pytest tests\test_postgres_benchmark.py
```
