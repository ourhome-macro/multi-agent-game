# Quality Hardening Phase 1 Summary - 2026-06-16

## Scope

This phase implements the first production-facing quality hardening pass after
PostgreSQL schema hardening. It covers four tracks:

1. Mist Clock Manor deviation scenarios.
2. Real LLM shadow eval entrypoints and drift reports.
3. PostgreSQL benchmark/smoke runner.
4. Local semantic memory retrieval scorer and matrix expansion.

The common boundary remains unchanged: LLM output cannot directly mutate world
state, clues, relationships, narrative phase, or memory snapshots. All gameplay
state changes still flow through `WorldEvent` and replayable rule systems.

## Deviation Scenarios

Added five deterministic `mist_clock_manor` deviation paths:

- `deviation_wrong_accusation_before_reconstruction.yaml`
- `deviation_ask_wrong_npc_about_wine.yaml`
- `deviation_repeat_present_same_clue.yaml`
- `deviation_out_of_order_medicine_probe.yaml`
- `deviation_direct_spoiler_probe.yaml`

The scenario discovery layer now supports arbitrary patterns through
`discover_scenarios(...)`; the tests run all `deviation_*.yaml` files for the
case. These scenarios verify wrong target, repeated clue presentation, out-of-
order evidence, premature accusation, and direct spoiler probing.

Backtrack status: the runtime already supports returning to a previously skipped
configured hotspot and discovering its predeclared clues. It does not yet support
conditional same-hotspot backtrack unlocks. That follow-up must be implemented
as Rule Engine configuration that releases predeclared clue IDs and emits normal
`clue.discovered` / `player_knowledge.updated` events.

Detailed note:

- `doc/evaluations/mist-clock-manor-deviation-scenarios-phase1-2026-06-16.md`

## LLM Shadow Eval

The shadow eval module now has a module CLI:

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --redteam
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --benchmark safety
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --drift --runs 20
```

The default backend is still stub. Real LLM calls require the explicit shadow
gate and real backend configuration. Public reports remain sanitized and do not
write player raw text, LLM raw text, private character text, forbidden terms, or
prompt bodies.

Detailed note:

- `doc/evaluations/llm-shadow-eval-v0.md`

## PostgreSQL Benchmark

Added a safe benchmark/smoke runner:

```powershell
py -3.12 -m app.scripts.postgres_benchmark --mode stub --profile dry
```

PostgreSQL mode is gated:

```powershell
$env:AGENT_TEST_DATABASE_URL = "postgresql://agent_test:***@localhost:5432/agent_test"
$env:AGENT_POSTGRES_BENCHMARK_ALLOW_DB = "1"
py -3.12 -m app.scripts.postgres_benchmark --mode postgres --profile dry --apply-schema
```

The benchmark refuses to use `AGENT_DATABASE_URL` by default and rejects an
explicit URL that exactly matches `AGENT_DATABASE_URL`. Output is summarized as
p50/p95/p99 latency, event count, trace count, memory query count, candidate
count, idempotency replay count, idempotency conflict count, and sequence
conflict count.

Detailed note:

- `doc/evaluations/postgres-benchmark-phase1-2026-06-16.md`

## Semantic Memory Retrieval

Added an opt-in local semantic scorer:

- `LocalSemanticEmbeddingScorer`
- `build_local_semantic_embedding_scorer(...)`

The default `MemoryRetriever` still uses the noop embedding scorer. Semantic
scoring only runs after hard filters accept a candidate; it cannot fetch extra
memories, bypass visibility, bypass phase, or override forbidden-fact checks.

The memory matrix now covers synonym and Chinese-variant phrasing for
`empty_capsules`, while preserving the same expected and forbidden memory ID
sets.

Detailed note:

- `doc/evaluations/semantic-memory-retrieval-phase1-2026-06-16.md`

## Verification

Targeted tests:

```powershell
py -3.12 -m pytest -q tests\test_standard_scenario_discovery.py tests\test_mist_clock_manor_scenario.py tests\test_llm_shadow_eval.py tests\test_postgres_benchmark.py tests\test_memory_retrieval_matrix.py tests\test_memory_retrieval_quality.py
```

Result:

```text
52 passed
```

Static check:

```powershell
py -3.12 -m ruff check app\evaluations\llm_shadow_eval.py scripts\run_llm_shadow_eval.py app\evaluations\postgres_benchmark.py app\scripts\postgres_benchmark.py app\agents\memory_retrieval.py app\agents\memory.py tests\test_llm_shadow_eval.py tests\test_postgres_benchmark.py tests\test_memory_retrieval_matrix.py tests\test_memory_retrieval_quality.py tests\test_standard_scenario_discovery.py tests\test_mist_clock_manor_scenario.py
```

Result:

```text
All checks passed.
```

Full test suite:

```powershell
py -3.12 -m pytest -q
```

Result:

```text
543 passed
```

## Remaining Work

- Implement conditional same-hotspot backtrack unlocks as rule-owned configured
  clue releases.
- Run real LLM shadow eval with actual API credentials and review drift reports.
- Run PostgreSQL benchmark against a disposable test database and record p95/p99.
- Treat pgvector as a later backend swap only after matrix and hard-filter
  invariants remain stable.
