from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from app.agents.context import build_agent_context
from app.agents.memory import MemoryRetriever
from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.domain.models import (
    AgentContext,
    AgentMemorySnapshot,
    CasePackage,
    PlayerAction,
    SessionState,
)

EvaluationSource = Literal["retriever", "agent_context"]


@dataclass(frozen=True)
class MemoryRetrievalMatrixEntry:
    case_id: str
    phase: str
    action: PlayerAction
    target_id: str
    expected_memory_ids: tuple[str, ...]
    forbidden_memory_ids: tuple[str, ...]
    subject: str | None = None
    clue: str | None = None
    claim: str | None = None
    notes: str = ""
    entry_id: str | None = None

    @property
    def stable_id(self) -> str:
        if self.entry_id:
            return self.entry_id
        focus = self.subject or self.clue or self.claim or "general"
        return f"{self.case_id}:{self.phase}:{self.target_id}:{self.action.type.value}:{focus}"


@dataclass(frozen=True)
class MemoryRetrievalMatrixFailure:
    entry_id: str
    case_id: str
    phase: str
    target_id: str
    source: EvaluationSource
    missing_expected_memory_ids: tuple[str, ...] = ()
    retrieved_forbidden_memory_ids: tuple[str, ...] = ()
    retrieved_memory_ids: tuple[str, ...] = ()
    notes: str = ""

    @property
    def message(self) -> str:
        parts = [
            f"{self.entry_id} failed for {self.source}",
            f"phase={self.phase}",
            f"target={self.target_id}",
        ]
        if self.missing_expected_memory_ids:
            parts.append(
                "missing="
                + ",".join(self.missing_expected_memory_ids)
            )
        if self.retrieved_forbidden_memory_ids:
            parts.append(
                "forbidden="
                + ",".join(self.retrieved_forbidden_memory_ids)
            )
        parts.append("retrieved=" + ",".join(self.retrieved_memory_ids))
        if self.notes:
            parts.append(f"notes={self.notes}")
        return "; ".join(parts)


@dataclass(frozen=True)
class MemoryRetrievalMatrixEntryResult:
    entry: MemoryRetrievalMatrixEntry
    source: EvaluationSource
    retrieved_memory_ids: tuple[str, ...]
    missing_expected_memory_ids: tuple[str, ...] = ()
    retrieved_forbidden_memory_ids: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            not self.missing_expected_memory_ids
            and not self.retrieved_forbidden_memory_ids
        )

    def failure(self) -> MemoryRetrievalMatrixFailure | None:
        if self.passed:
            return None
        return MemoryRetrievalMatrixFailure(
            entry_id=self.entry.stable_id,
            case_id=self.entry.case_id,
            phase=self.entry.phase,
            target_id=self.entry.target_id,
            source=self.source,
            missing_expected_memory_ids=self.missing_expected_memory_ids,
            retrieved_forbidden_memory_ids=self.retrieved_forbidden_memory_ids,
            retrieved_memory_ids=self.retrieved_memory_ids,
            notes=self.entry.notes,
        )


@dataclass(frozen=True)
class MemoryRetrievalMatrixReport:
    source: EvaluationSource
    results: tuple[MemoryRetrievalMatrixEntryResult, ...] = field(default_factory=tuple)

    @property
    def failures(self) -> tuple[MemoryRetrievalMatrixFailure, ...]:
        return tuple(
            failure
            for result in self.results
            for failure in [result.failure()]
            if failure is not None
        )

    @property
    def passed(self) -> bool:
        return not self.failures

    def assert_passed(self) -> None:
        failures = self.failures
        if failures:
            raise AssertionError("\n".join(failure.message for failure in failures))


MemorySnapshotProvider = Callable[
    [MemoryRetrievalMatrixEntry, CasePackage, SessionState],
    Sequence[AgentMemorySnapshot],
]


def evaluate_memory_retrieval_matrix(
    *,
    entries: Iterable[MemoryRetrievalMatrixEntry],
    case: CasePackage,
    session: SessionState,
    source: EvaluationSource = "retriever",
    retriever: MemoryRetriever | None = None,
    retrieval_plan: MemoryRetrievalPlan | None = None,
    context: AgentContext | None = None,
    snapshot_provider: MemorySnapshotProvider | None = None,
) -> MemoryRetrievalMatrixReport:
    evaluator = MemoryRetrievalMatrixEvaluator(
        case=case,
        session=session,
        source=source,
        retriever=retriever,
        retrieval_plan=retrieval_plan,
        context=context,
        snapshot_provider=snapshot_provider,
    )
    return evaluator.evaluate(entries)


class MemoryRetrievalMatrixEvaluator:
    def __init__(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source: EvaluationSource = "retriever",
        retriever: MemoryRetriever | None = None,
        retrieval_plan: MemoryRetrievalPlan | None = None,
        context: AgentContext | None = None,
        snapshot_provider: MemorySnapshotProvider | None = None,
    ) -> None:
        self._case = case
        self._session = session
        self._source = source
        self._retriever = retriever or MemoryRetriever(max_results=20)
        self._retrieval_plan = retrieval_plan
        self._context = context
        self._snapshot_provider = snapshot_provider

    def evaluate(
        self,
        entries: Iterable[MemoryRetrievalMatrixEntry],
    ) -> MemoryRetrievalMatrixReport:
        return MemoryRetrievalMatrixReport(
            source=self._source,
            results=tuple(self.evaluate_entry(entry) for entry in entries),
        )

    def evaluate_entry(
        self,
        entry: MemoryRetrievalMatrixEntry,
    ) -> MemoryRetrievalMatrixEntryResult:
        _validate_entry_matches_state(entry, self._case, self._session)
        retrieved_memory_ids = tuple(
            snapshot.memory_id for snapshot in self._retrieve_snapshots(entry)
        )
        retrieved_set = set(retrieved_memory_ids)
        missing_expected = tuple(
            memory_id
            for memory_id in entry.expected_memory_ids
            if memory_id not in retrieved_set
        )
        retrieved_forbidden = tuple(
            memory_id
            for memory_id in entry.forbidden_memory_ids
            if memory_id in retrieved_set
        )
        return MemoryRetrievalMatrixEntryResult(
            entry=entry,
            source=self._source,
            retrieved_memory_ids=retrieved_memory_ids,
            missing_expected_memory_ids=missing_expected,
            retrieved_forbidden_memory_ids=retrieved_forbidden,
        )

    def _retrieve_snapshots(
        self,
        entry: MemoryRetrievalMatrixEntry,
    ) -> Sequence[AgentMemorySnapshot]:
        if self._snapshot_provider is not None:
            return self._snapshot_provider(entry, self._case, self._session)
        if self._source == "retriever":
            return self._retriever.retrieve(
                case=self._case,
                session=self._session,
                action=entry.action,
                plan=self._retrieval_plan,
            )
        if self._source == "agent_context":
            if self._context is not None:
                _validate_context_matches_entry(self._context, entry)
                return self._context.memory_snapshots
            return build_agent_context(
                self._case,
                self._session,
                entry.action,
                retrieval_plan=self._retrieval_plan,
            ).memory_snapshots
        raise ValueError(f"Unsupported memory matrix source: {self._source}")


def load_memory_retrieval_matrix(path: Path) -> tuple[MemoryRetrievalMatrixEntry, ...]:
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        raw_payload = json.loads(raw_text)
    else:
        raw_payload = yaml.safe_load(raw_text)
    if not isinstance(raw_payload, list):
        raise ValueError("Memory retrieval matrix file must contain a list of entries")
    return tuple(memory_matrix_entry_from_mapping(item) for item in raw_payload)


def memory_matrix_entry_from_mapping(
    payload: Mapping[str, object],
) -> MemoryRetrievalMatrixEntry:
    action_payload = payload.get("action")
    if not isinstance(action_payload, Mapping):
        raise ValueError("Memory retrieval matrix entry requires an action mapping")
    target_id = _string(payload.get("target_id"), "target_id")
    action = PlayerAction.model_validate({**dict(action_payload), "target_id": target_id})
    return MemoryRetrievalMatrixEntry(
        case_id=_string(payload.get("case_id"), "case_id"),
        phase=_string(payload.get("phase"), "phase"),
        action=action,
        target_id=target_id,
        subject=_optional_string(payload.get("subject")),
        clue=_optional_string(payload.get("clue")),
        claim=_optional_string(payload.get("claim")),
        expected_memory_ids=_string_tuple(
            payload.get("expected_memory_ids"),
            "expected_memory_ids",
        ),
        forbidden_memory_ids=_string_tuple(
            payload.get("forbidden_memory_ids"),
            "forbidden_memory_ids",
        ),
        notes=_optional_string(payload.get("notes")) or "",
        entry_id=_optional_string(payload.get("entry_id")),
    )


def _validate_entry_matches_state(
    entry: MemoryRetrievalMatrixEntry,
    case: CasePackage,
    session: SessionState,
) -> None:
    if entry.case_id != case.meta.id:
        raise ValueError(
            f"{entry.stable_id} case_id={entry.case_id} does not match {case.meta.id}"
        )
    if entry.case_id != session.case_id:
        raise ValueError(
            f"{entry.stable_id} case_id={entry.case_id} does not match session {session.case_id}"
        )
    if entry.phase != session.narrative.phase:
        raise ValueError(
            f"{entry.stable_id} phase={entry.phase} does not match "
            f"session phase {session.narrative.phase}"
        )
    if entry.target_id != entry.action.target_id:
        raise ValueError(
            f"{entry.stable_id} target_id={entry.target_id} does not match action "
            f"target_id={entry.action.target_id}"
        )


def _validate_context_matches_entry(
    context: AgentContext,
    entry: MemoryRetrievalMatrixEntry,
) -> None:
    if context.case_id != entry.case_id:
        raise ValueError(
            f"{entry.stable_id} context case_id={context.case_id} does not match entry"
        )
    if context.current_phase != entry.phase:
        raise ValueError(
            f"{entry.stable_id} context phase={context.current_phase} does not match entry"
        )
    if context.target_agent_id != entry.target_id:
        raise ValueError(
            f"{entry.stable_id} context target={context.target_agent_id} does not match entry"
        )


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Memory retrieval matrix entry requires {field_name}")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Optional memory retrieval matrix text fields must be strings")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"Memory retrieval matrix field {field_name} must be a list")
    return tuple(_string(item, field_name) for item in value)
