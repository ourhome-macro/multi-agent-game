# Semantic Memory Retrieval Phase 1 - 2026-06-16

## Scope

Phase 1 adds a local, injectable semantic scorer for memory retrieval. It is a
scoring component only, not a storage backend and not a vector index.

The production boundary is strict:

- Scope, layer, target visibility, phase, source provenance, retrieval plan, and
  forbidden-fact filters run before any semantic score is computed.
- The scorer cannot fetch extra memories and cannot bypass store-level filters.
- The default `MemoryRetriever` still uses `NoopEmbeddingScorer`; semantic
  scoring is opt-in by dependency injection.
- Trace projection continues to record memory ids and metadata only. Memory
  content is not written to runtime trace.
- LLM output still cannot mutate memory snapshots or world state.

## Implementation

New code:

- `LocalSemanticEmbeddingScorer` in `app/agents/memory_retrieval.py`
- `build_local_semantic_embedding_scorer(...)` in `app/agents/memory.py`

The scorer uses a deterministic local alias table. It maps concept aliases such
as `empty_capsules`, `empty capsules`, `medicine clue`, `药箱`, `药壳子`, and
`空药囊` into shared token sets, then scores overlap between the player query
and an already-authorized memory snapshot haystack.

This deliberately avoids external network calls and avoids pgvector. The result
is a first-stage recall improvement for synonym and Chinese-variant phrasing
without changing the authorization model.

## Matrix Updates

`tests/test_memory_retrieval_matrix.py` now covers:

- Existing `empty_capsules` English/id phrasing.
- Chinese variant phrasing around `药箱`, `空药囊`, and `心脏药`.
- A forbidden-case query that mentions director-audit and another NPC's capsule
  memory while keeping the expected set empty and forbidden set unchanged.

The expected and forbidden memory id sets remain stable:

- Expected Jiang typed memories:
  - `memory.player.belief.jiang_yanhui.empty_capsules`
  - `memory.player.relationship.jiang_yanhui.empty_capsules`
  - `memory.player.strategy.jiang_yanhui.empty_capsules`
- Forbidden ordinary NPC memories:
  - `memory.player.presented_clue.shen_zhaoye.empty_capsules`
  - `memory.player.director_blocked.jiang_yanhui.jiang_yanhui_mechanism`

## Quality Coverage

`tests/test_memory_retrieval_quality.py` now proves:

- Default retrieval does not drift: synonym-only recall is absent without an
  injected semantic scorer.
- Injected local semantic scoring recalls the safe medicine-clue memory from a
  Chinese synonym query.
- Director audit scope, other-NPC private visibility, future phase, and archival
  hard filters still exclude semantic matches before scoring.
- Forbidden memory content stays out of retrieval even when semantic aliases
  match the query and another safe semantic match is available.

## Future Work

pgvector remains a later phase. Before introducing pgvector:

1. Keep the same hard-filter contract in SQL and in application verification.
2. Preserve a deterministic fallback scorer for local tests.
3. Run the memory retrieval matrix before and after the backend swap.
4. Add benchmark coverage separately; do not treat vector recall as permission.
