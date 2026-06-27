# Memory Retrieval Golden Query Set

## Purpose

The memory retrieval golden query set is a deterministic regression gate for
NPC memory recall. It checks whether a given phase, target NPC, and structured
player action retrieves the expected memory ids within `k`, while excluding
forbidden or noisy ids.

This is not an LLM response-quality benchmark. It only covers retrieval and
projection inputs. LLM output still cannot mutate world state, clue state,
relationship state, or narrative phase.

## Fixture Shape

The minimal fixture lives at:

```text
tests/fixtures/memory_golden/minimal.json
```

Top-level fields:

- `memory_snapshots`: local in-memory corpus. Each entry is validated as an
  `AgentMemorySnapshot`.
- `golden_cases`: query cases. Each case uses the required fields below.

Each golden case must contain exactly:

```json
{
  "case_id": "memory_golden_minimal",
  "phase": "opening",
  "target_id": "jiang_yanhui",
  "action": {
    "type": "ask_about",
    "subject_type": "clue",
    "subject_id": "empty_capsules",
    "text": "Ask Jiang about empty capsule shells."
  },
  "k": 3,
  "expected_include": [
    "memory.golden.jiang.empty_capsules.strategy"
  ],
  "expected_exclude": [
    "memory.golden.shen.empty_capsules.episodic"
  ]
}
```

`target_id` is top-level and is merged into the `PlayerAction` by the test
loader. Keeping it out of `action` avoids ambiguous ownership between the golden
case and the action payload.

## Metrics

For each golden case, the test builds a `SessionState` from the fixture corpus
and calls:

```python
MemoryRetriever(max_results=k).retrieve(case=case, session=session, action=action)
```

The current metrics are:

- `Recall@K`: `expected_include` ids found in the retrieved top `k`, divided by
  the number of `expected_include` ids.
- `missing_ids`: expected ids absent from top `k`.
- `forbidden_false_positives`: `expected_exclude` ids present in top `k`.
- `noise_ids`: retrieved top `k` ids not listed in `expected_include`.

Pass condition for the minimal set:

- `Recall@K == 1.0`
- `missing_ids == []`
- `forbidden_false_positives == []`
- `noise_ids == []`

This deliberately makes the first fixture a strict precision gate. Future
fixtures can add explicit allow-lists if a case needs supporting memories beyond
the core expected ids.

## Production Boundary

The golden set must preserve the existing memory safety boundaries:

- Target visibility, memory scope, phase, source provenance, and forbidden-fact
  filters remain hard gates before recall quality is considered.
- Other NPC private memories and `director_audit` memories must not enter normal
  NPC retrieval.
- Phase-locked reconstruction memories must stay out of earlier phases.
- Forbidden truth anchors must remain excluded even when the query baits the
  matching terms.

The test intentionally uses an in-memory session and does not depend on an
external database. It is a small regression harness for retrieval behavior, not
a replacement for runtime scenario tests.

## Verification

Run:

```powershell
py -3.12 -m pytest tests\test_memory_golden_retrieval.py
```
