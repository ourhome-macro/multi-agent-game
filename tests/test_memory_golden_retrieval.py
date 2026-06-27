from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.agents.memory import MemoryRetriever
from app.domain.models import (
    AgentMemorySnapshot,
    CaseMeta,
    CasePackage,
    CharacterConfig,
    ClueConfig,
    ForbiddenFactConfig,
    NarrativeState,
    PlayerAction,
    SceneConfig,
    SessionState,
    WorldInfoConfig,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "memory_golden" / "minimal.json"
REQUIRED_GOLDEN_FIELDS = frozenset(
    {
        "case_id",
        "phase",
        "target_id",
        "action",
        "k",
        "expected_include",
        "expected_exclude",
    }
)


@dataclass(frozen=True)
class GoldenRetrievalResult:
    case_id: str
    phase: str
    target_id: str
    k: int
    retrieved_ids: tuple[str, ...]
    expected_include: tuple[str, ...]
    expected_exclude: tuple[str, ...]

    @property
    def recall_at_k(self) -> float:
        if not self.expected_include:
            return 1.0
        retrieved = set(self.retrieved_ids[: self.k])
        expected = set(self.expected_include)
        return len(retrieved & expected) / len(expected)

    @property
    def missing_ids(self) -> tuple[str, ...]:
        retrieved = set(self.retrieved_ids[: self.k])
        return tuple(memory_id for memory_id in self.expected_include if memory_id not in retrieved)

    @property
    def forbidden_false_positives(self) -> tuple[str, ...]:
        retrieved = set(self.retrieved_ids[: self.k])
        return tuple(memory_id for memory_id in self.expected_exclude if memory_id in retrieved)

    @property
    def noise_ids(self) -> tuple[str, ...]:
        expected = set(self.expected_include)
        return tuple(
            memory_id
            for memory_id in self.retrieved_ids[: self.k]
            if memory_id not in expected
        )

    @property
    def passed(self) -> bool:
        return (
            self.recall_at_k == 1.0
            and not self.missing_ids
            and not self.forbidden_false_positives
            and not self.noise_ids
        )

    @property
    def failure_message(self) -> str:
        return (
            f"{self.case_id}:{self.phase}:{self.target_id}: "
            f"Recall@{self.k}={self.recall_at_k:.3f}; "
            f"missing={list(self.missing_ids)}; "
            f"forbidden_false_positives={list(self.forbidden_false_positives)}; "
            f"noise={list(self.noise_ids)}; "
            f"retrieved={list(self.retrieved_ids)}"
        )


def test_memory_golden_fixture_schema_is_explicit() -> None:
    payload = _load_fixture()
    memories = _memory_snapshots(payload)
    memory_ids = {memory.memory_id for memory in memories}
    golden_cases = _golden_cases(payload)

    assert golden_cases, "golden query set must contain at least one case"
    for golden_case in golden_cases:
        missing_fields = REQUIRED_GOLDEN_FIELDS - set(golden_case)
        assert not missing_fields, f"golden case is missing fields: {sorted(missing_fields)}"
        assert set(golden_case) == REQUIRED_GOLDEN_FIELDS
        assert _positive_int(golden_case["k"], "k") >= len(
            _string_tuple(golden_case["expected_include"], "expected_include")
        )

        action_payload = _mapping(golden_case["action"], "action")
        assert "target_id" not in action_payload
        _action(golden_case)

        expected_include = _string_tuple(golden_case["expected_include"], "expected_include")
        expected_exclude = _string_tuple(golden_case["expected_exclude"], "expected_exclude")
        assert not (set(expected_include) & set(expected_exclude))
        assert set(expected_include) <= memory_ids
        assert set(expected_exclude) <= memory_ids


def test_memory_golden_query_set_retrieval_metrics() -> None:
    payload = _load_fixture()
    case = _case_package()
    memories = _memory_snapshots(payload)
    golden_cases = _golden_cases(payload)

    results = tuple(
        _evaluate_golden_case(case, memories, golden_case)
        for golden_case in golden_cases
    )
    macro_recall_at_k = sum(result.recall_at_k for result in results) / len(results)

    assert macro_recall_at_k == 1.0
    failures = [result.failure_message for result in results if not result.passed]
    assert not failures, "\n".join(failures)


def _evaluate_golden_case(
    case: CasePackage,
    memories: tuple[AgentMemorySnapshot, ...],
    golden_case: Mapping[str, object],
) -> GoldenRetrievalResult:
    case_id = _non_empty_string(golden_case["case_id"], "case_id")
    if case_id != case.meta.id:
        raise AssertionError(f"golden case {case_id} does not match fixture case {case.meta.id}")
    phase = _non_empty_string(golden_case["phase"], "phase")
    target_id = _non_empty_string(golden_case["target_id"], "target_id")
    k = _positive_int(golden_case["k"], "k")
    action = _action(golden_case)
    session = _session(case_id=case_id, phase=phase, memories=memories)

    retrieved = MemoryRetriever(max_results=k).retrieve(
        case=case,
        session=session,
        action=action,
    )

    return GoldenRetrievalResult(
        case_id=case_id,
        phase=phase,
        target_id=target_id,
        k=k,
        retrieved_ids=tuple(memory.memory_id for memory in retrieved),
        expected_include=_string_tuple(golden_case["expected_include"], "expected_include"),
        expected_exclude=_string_tuple(golden_case["expected_exclude"], "expected_exclude"),
    )


def _load_fixture() -> Mapping[str, object]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("memory golden fixture must be a JSON object")
    return payload


def _golden_cases(payload: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw_cases = payload.get("golden_cases")
    if not isinstance(raw_cases, list):
        raise AssertionError("memory golden fixture must define golden_cases as a list")
    cases: list[Mapping[str, object]] = []
    for item in raw_cases:
        if not isinstance(item, dict):
            raise AssertionError("each memory golden case must be an object")
        cases.append(item)
    return tuple(cases)


def _memory_snapshots(payload: Mapping[str, object]) -> tuple[AgentMemorySnapshot, ...]:
    raw_memories = payload.get("memory_snapshots")
    if not isinstance(raw_memories, list):
        raise AssertionError("memory golden fixture must define memory_snapshots as a list")
    return tuple(AgentMemorySnapshot.model_validate(item) for item in raw_memories)


def _action(golden_case: Mapping[str, object]) -> PlayerAction:
    target_id = _non_empty_string(golden_case["target_id"], "target_id")
    action_payload = dict(_mapping(golden_case["action"], "action"))
    return PlayerAction.model_validate({**action_payload, "target_id": target_id})


def _session(
    *,
    case_id: str,
    phase: str,
    memories: tuple[AgentMemorySnapshot, ...],
) -> SessionState:
    return SessionState(
        id=f"session.memory_golden.{phase}",
        case_id=case_id,
        narrative=NarrativeState(phase=phase),
        relationships={},
        memory_snapshots={memory.memory_id: memory for memory in memories},
    )


def _case_package() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id="memory_golden_minimal",
            title="Memory Golden Minimal",
            initial_phase="opening",
        ),
        world_info=[
            WorldInfoConfig(
                id="heart_medicine_replaced",
                title="heart medicine replaced",
                description="The heart prescription was tampered with before dinner.",
                aliases=[
                    "heart medicine",
                    "medicine box pressure",
                    "medicine bottle",
                    "prescription tampering",
                    "empty capsule shells",
                ],
                claim_patterns=["heart medicine was replaced"],
            )
        ],
        characters=[
            CharacterConfig(id="jiang_yanhui", display_name="Jiang Yanhui", public_role="doctor"),
            CharacterConfig(id="shen_zhaoye", display_name="Shen Zhaoye", public_role="heir"),
        ],
        scenes=[SceneConfig(id="study", name="Study")],
        clues=[
            ClueConfig(
                id="empty_capsules",
                title="empty capsules",
                description="Empty capsule shells from the medicine box.",
                reveals_world_info=["heart_medicine_replaced"],
                key=True,
            ),
            ClueConfig(
                id="delayed_lock_marks",
                title="delayed lock marks",
                description="Delayed marks on the study lock.",
                key=True,
            ),
        ],
        forbidden_facts=[
            ForbiddenFactConfig(
                id="fact.killer_identity",
                text="true killer is the butler",
                blocked_terms=["true killer is the butler", "butler poisoned the victim"],
            )
        ],
    )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"{field_name} must be an object")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AssertionError(f"{field_name} must be a list")
    return tuple(_non_empty_string(item, field_name) for item in value)


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AssertionError(f"{field_name} must be a non-empty string")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise AssertionError(f"{field_name} must be a positive integer")
    return value
