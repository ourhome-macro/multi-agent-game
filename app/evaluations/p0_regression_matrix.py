from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]

P0Dimension = Literal[
    "memory",
    "director",
    "action_intake",
    "deduction",
    "provider",
]
ActionIntakeStatus = Literal["accepted", "ambiguous", "rejected"]


@dataclass(frozen=True)
class P0MemoryExpectation:
    expected_memory_ids: tuple[str, ...] = ()
    forbidden_memory_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return _payload(
            expected_memory_ids=self.expected_memory_ids,
            forbidden_memory_ids=self.forbidden_memory_ids,
        )


@dataclass(frozen=True)
class P0DirectorExpectation:
    expected_allowed: bool | None = None
    allowed_world_info_ids: tuple[str, ...] = ()
    forbidden_world_info_ids: tuple[str, ...] = ()
    allowed_claim_ids: tuple[str, ...] = ()
    forbidden_claim_ids: tuple[str, ...] = ()
    expected_block_reason_contains: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return _payload(
            expected_allowed=self.expected_allowed,
            allowed_world_info_ids=self.allowed_world_info_ids,
            forbidden_world_info_ids=self.forbidden_world_info_ids,
            allowed_claim_ids=self.allowed_claim_ids,
            forbidden_claim_ids=self.forbidden_claim_ids,
            expected_block_reason_contains=self.expected_block_reason_contains,
        )


@dataclass(frozen=True)
class P0ActionIntakeExpectation:
    expected_status: ActionIntakeStatus
    expected_action_type: str | None = None
    expected_target_id: str | None = None
    expected_subject_id: str | None = None
    expected_clue_id: str | None = None
    expected_claim_id: str | None = None
    expected_missing_slots: tuple[str, ...] | None = None
    expected_reason_contains: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return _payload(
            expected_status=self.expected_status,
            expected_action_type=self.expected_action_type,
            expected_target_id=self.expected_target_id,
            expected_subject_id=self.expected_subject_id,
            expected_clue_id=self.expected_clue_id,
            expected_claim_id=self.expected_claim_id,
            expected_missing_slots=self.expected_missing_slots,
            expected_reason_contains=self.expected_reason_contains,
        )


@dataclass(frozen=True)
class P0DeductionExpectation:
    expected_accepted: bool
    expected_claim_id: str | None = None
    expected_result: str | None = None
    expected_reject_code: str | None = None
    expected_missing_evidence: tuple[str, ...] | None = None
    expected_missing_world_info: tuple[str, ...] | None = None

    def to_payload(self) -> dict[str, object]:
        return _payload(
            expected_accepted=self.expected_accepted,
            expected_claim_id=self.expected_claim_id,
            expected_result=self.expected_result,
            expected_reject_code=self.expected_reject_code,
            expected_missing_evidence=self.expected_missing_evidence,
            expected_missing_world_info=self.expected_missing_world_info,
        )


@dataclass(frozen=True)
class P0RegressionCase:
    case_id: str
    phase: str
    input_text: str
    memory: P0MemoryExpectation | None = None
    director: P0DirectorExpectation | None = None
    action_intake: P0ActionIntakeExpectation | None = None
    deduction: P0DeductionExpectation | None = None
    entry_id: str | None = None
    notes: str = ""

    @property
    def stable_id(self) -> str:
        if self.entry_id:
            return self.entry_id
        return f"{self.case_id}:{self.phase}:{_slug(self.input_text)}"

    @property
    def expected_dimensions(self) -> tuple[P0Dimension, ...]:
        dimensions: list[P0Dimension] = []
        if self.memory is not None:
            dimensions.append("memory")
        if self.director is not None:
            dimensions.append("director")
        if self.action_intake is not None:
            dimensions.append("action_intake")
        if self.deduction is not None:
            dimensions.append("deduction")
        return tuple(dimensions)

    def expected_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.memory is not None:
            payload["memory"] = self.memory.to_payload()
        if self.director is not None:
            payload["director"] = self.director.to_payload()
        if self.action_intake is not None:
            payload["action_intake"] = self.action_intake.to_payload()
        if self.deduction is not None:
            payload["deduction"] = self.deduction.to_payload()
        return payload


@dataclass(frozen=True)
class P0MemoryActual:
    retrieved_memory_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return _payload(retrieved_memory_ids=self.retrieved_memory_ids)


@dataclass(frozen=True)
class P0DirectorActual:
    allowed: bool | None
    allowed_world_info_ids: tuple[str, ...] = ()
    blocked_world_info_ids: tuple[str, ...] = ()
    allowed_claim_ids: tuple[str, ...] = ()
    blocked_claim_ids: tuple[str, ...] = ()
    block_reason: str | None = None

    def to_payload(self) -> dict[str, object]:
        return _payload(
            allowed=self.allowed,
            allowed_world_info_ids=self.allowed_world_info_ids,
            blocked_world_info_ids=self.blocked_world_info_ids,
            allowed_claim_ids=self.allowed_claim_ids,
            blocked_claim_ids=self.blocked_claim_ids,
            block_reason=self.block_reason,
        )


@dataclass(frozen=True)
class P0ActionIntakeActual:
    status: ActionIntakeStatus
    action_type: str | None = None
    target_id: str | None = None
    subject_id: str | None = None
    clue_id: str | None = None
    claim_id: str | None = None
    missing_slots: tuple[str, ...] = ()
    reason: str | None = None

    def to_payload(self) -> dict[str, object]:
        return _payload(
            status=self.status,
            action_type=self.action_type,
            target_id=self.target_id,
            subject_id=self.subject_id,
            clue_id=self.clue_id,
            claim_id=self.claim_id,
            missing_slots=self.missing_slots,
            reason=self.reason,
        )


@dataclass(frozen=True)
class P0DeductionActual:
    accepted: bool
    claim_id: str | None = None
    result: str | None = None
    reject_code: str | None = None
    missing_evidence: tuple[str, ...] = ()
    missing_world_info: tuple[str, ...] = ()
    matched_required_evidence: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return _payload(
            accepted=self.accepted,
            claim_id=self.claim_id,
            result=self.result,
            reject_code=self.reject_code,
            missing_evidence=self.missing_evidence,
            missing_world_info=self.missing_world_info,
            matched_required_evidence=self.matched_required_evidence,
        )


@dataclass(frozen=True)
class P0RegressionActual:
    memory: P0MemoryActual | None = None
    director: P0DirectorActual | None = None
    action_intake: P0ActionIntakeActual | None = None
    deduction: P0DeductionActual | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.memory is not None:
            payload["memory"] = self.memory.to_payload()
        if self.director is not None:
            payload["director"] = self.director.to_payload()
        if self.action_intake is not None:
            payload["action_intake"] = self.action_intake.to_payload()
        if self.deduction is not None:
            payload["deduction"] = self.deduction.to_payload()
        return payload


@dataclass(frozen=True)
class P0RegressionFailure:
    entry_id: str
    case_id: str
    phase: str
    input_text: str
    dimension: P0Dimension
    details: tuple[str, ...]
    expected: Mapping[str, object]
    actual: Mapping[str, object]
    notes: str = ""

    @property
    def message(self) -> str:
        parts = [
            f"{self.entry_id} failed [{self.dimension}]",
            f"case_id={self.case_id}",
            f"phase={self.phase}",
            f"input={self.input_text!r}",
            "details=" + ",".join(self.details),
            "expected=" + _json(self.expected),
            "actual=" + _json(self.actual),
        ]
        if self.notes:
            parts.append(f"notes={self.notes}")
        return "; ".join(parts)


@dataclass(frozen=True)
class P0RegressionCaseResult:
    entry: P0RegressionCase
    actual: P0RegressionActual
    failures: tuple[P0RegressionFailure, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class P0RegressionReport:
    results: tuple[P0RegressionCaseResult, ...] = field(default_factory=tuple)

    @property
    def failures(self) -> tuple[P0RegressionFailure, ...]:
        return tuple(failure for result in self.results for failure in result.failures)

    @property
    def passed(self) -> bool:
        return not self.failures

    def assert_passed(self) -> None:
        failures = self.failures
        if failures:
            raise AssertionError("\n".join(failure.message for failure in failures))


P0ActualProvider = Callable[[P0RegressionCase], P0RegressionActual]


def evaluate_p0_regression_matrix(
    *,
    entries: Iterable[P0RegressionCase],
    actual_provider: P0ActualProvider,
) -> P0RegressionReport:
    results: list[P0RegressionCaseResult] = []
    for entry in entries:
        if not entry.expected_dimensions:
            raise ValueError(f"{entry.stable_id} must define at least one expectation")
        try:
            actual = actual_provider(entry)
        except Exception as exc:  # pragma: no cover - defensive reporting path
            failure = P0RegressionFailure(
                entry_id=entry.stable_id,
                case_id=entry.case_id,
                phase=entry.phase,
                input_text=entry.input_text,
                dimension="provider",
                details=(f"actual_provider_error={type(exc).__name__}: {exc}",),
                expected=entry.expected_payload(),
                actual={"provider_error": f"{type(exc).__name__}: {exc}"},
                notes=entry.notes,
            )
            results.append(
                P0RegressionCaseResult(
                    entry=entry,
                    actual=P0RegressionActual(),
                    failures=(failure,),
                )
            )
            continue
        results.append(
            P0RegressionCaseResult(
                entry=entry,
                actual=actual,
                failures=_evaluate_entry(entry, actual),
            )
        )
    return P0RegressionReport(results=tuple(results))


def load_p0_regression_matrix(path: Path) -> tuple[P0RegressionCase, ...]:
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        raw_payload = json.loads(raw_text)
    else:
        raw_payload = yaml.safe_load(raw_text)
    if not isinstance(raw_payload, list):
        raise ValueError("P0 regression matrix file must contain a list of entries")
    return tuple(p0_regression_case_from_mapping(item) for item in raw_payload)


def p0_regression_case_from_mapping(payload: Mapping[str, object]) -> P0RegressionCase:
    case_id = _string(payload.get("case_id"), "case_id")
    phase = _string(payload.get("phase"), "phase")
    input_text = _string(payload.get("input_text", payload.get("input")), "input_text")
    return P0RegressionCase(
        case_id=case_id,
        phase=phase,
        input_text=input_text,
        memory=_memory_expectation_from_mapping(payload.get("memory")),
        director=_director_expectation_from_mapping(payload.get("director")),
        action_intake=_action_expectation_from_mapping(payload.get("action_intake")),
        deduction=_deduction_expectation_from_mapping(payload.get("deduction")),
        entry_id=_optional_string(payload.get("entry_id")),
        notes=_optional_string(payload.get("notes")) or "",
    )


def memory_actual_from_ids(memory_ids: Iterable[str]) -> P0MemoryActual:
    return P0MemoryActual(retrieved_memory_ids=tuple(memory_ids))


def director_actual_from_decision(
    decision: object,
    *,
    requested_world_info_ids: Iterable[str] = (),
    requested_claim_ids: Iterable[str] = (),
) -> P0DirectorActual:
    allowed = bool(_required_attr(decision, "allowed"))
    world_info_ids = tuple(requested_world_info_ids)
    claim_ids = tuple(requested_claim_ids)
    blocked_world_info_id = (
        getattr(decision, "world_info_id", None)
        or getattr(decision, "blocked_fact_id", None)
    )
    if allowed:
        return P0DirectorActual(
            allowed=True,
            allowed_world_info_ids=world_info_ids,
            allowed_claim_ids=claim_ids,
            block_reason=getattr(decision, "reason", None),
        )
    blocked_world_info_ids = (blocked_world_info_id,) if blocked_world_info_id else world_info_ids
    return P0DirectorActual(
        allowed=False,
        blocked_world_info_ids=blocked_world_info_ids,
        blocked_claim_ids=claim_ids,
        block_reason=getattr(decision, "reason", None),
    )


def action_intake_actual_from_route_result(route_result: object) -> P0ActionIntakeActual:
    raw_status = _enum_value(getattr(route_result, "status", None))
    if raw_status == "resolved":
        status: ActionIntakeStatus = "accepted"
    elif raw_status == "needs_clarification":
        status = "ambiguous"
    else:
        status = "rejected"

    action = getattr(route_result, "action", None)
    return P0ActionIntakeActual(
        status=status,
        action_type=_enum_value(getattr(action, "type", None)) if action is not None else None,
        target_id=getattr(action, "target_id", None) if action is not None else None,
        subject_id=getattr(action, "subject_id", None) if action is not None else None,
        clue_id=getattr(action, "clue_id", None) if action is not None else None,
        claim_id=getattr(action, "claim_id", None) if action is not None else None,
        missing_slots=tuple(getattr(route_result, "missing_slots", ()) or ()),
        reason=getattr(route_result, "reason", None),
    )


def deduction_actual_from_result(result: object) -> P0DeductionActual:
    return P0DeductionActual(
        accepted=bool(_required_attr(result, "accepted")),
        claim_id=getattr(result, "matched_claim", None),
        result=getattr(result, "result", None),
        reject_code=getattr(result, "reject_code", None),
        missing_evidence=tuple(getattr(result, "missing_evidence", ()) or ()),
        missing_world_info=tuple(getattr(result, "missing_world_info", ()) or ()),
        matched_required_evidence=tuple(
            getattr(result, "matched_required_evidence", ()) or ()
        ),
    )


def _evaluate_entry(
    entry: P0RegressionCase,
    actual: P0RegressionActual,
) -> tuple[P0RegressionFailure, ...]:
    failures: list[P0RegressionFailure] = []
    if entry.memory is not None:
        failures.extend(_compare_memory(entry, entry.memory, actual.memory))
    if entry.director is not None:
        failures.extend(_compare_director(entry, entry.director, actual.director))
    if entry.action_intake is not None:
        failures.extend(
            _compare_action_intake(entry, entry.action_intake, actual.action_intake)
        )
    if entry.deduction is not None:
        failures.extend(_compare_deduction(entry, entry.deduction, actual.deduction))
    return tuple(failures)


def _compare_memory(
    entry: P0RegressionCase,
    expected: P0MemoryExpectation,
    actual: P0MemoryActual | None,
) -> tuple[P0RegressionFailure, ...]:
    if actual is None:
        return (
            _failure(
                entry,
                "memory",
                ("actual_memory_missing",),
                expected.to_payload(),
                {},
            ),
        )
    retrieved = set(actual.retrieved_memory_ids)
    missing = tuple(
        memory_id for memory_id in expected.expected_memory_ids if memory_id not in retrieved
    )
    forbidden = tuple(
        memory_id for memory_id in expected.forbidden_memory_ids if memory_id in retrieved
    )
    details: list[str] = []
    if missing:
        details.append("missing_memory_ids=" + ",".join(missing))
    if forbidden:
        details.append("retrieved_forbidden_memory_ids=" + ",".join(forbidden))
    if not details:
        return ()
    return (
        _failure(
            entry,
            "memory",
            tuple(details),
            expected.to_payload(),
            actual.to_payload(),
        ),
    )


def _compare_director(
    entry: P0RegressionCase,
    expected: P0DirectorExpectation,
    actual: P0DirectorActual | None,
) -> tuple[P0RegressionFailure, ...]:
    if actual is None:
        return (
            _failure(
                entry,
                "director",
                ("actual_director_missing",),
                expected.to_payload(),
                {},
            ),
        )
    details: list[str] = []
    if expected.expected_allowed is not None and actual.allowed != expected.expected_allowed:
        details.append(
            f"allowed expected={expected.expected_allowed} actual={actual.allowed}"
        )
    details.extend(
        _missing_details(
            label="missing_allowed_world_info_ids",
            expected=expected.allowed_world_info_ids,
            actual=actual.allowed_world_info_ids,
        )
    )
    details.extend(
        _blocked_details(
            label="world_info",
            expected_blocked=expected.forbidden_world_info_ids,
            actual_allowed=actual.allowed_world_info_ids,
            actual_blocked=actual.blocked_world_info_ids,
        )
    )
    details.extend(
        _missing_details(
            label="missing_allowed_claim_ids",
            expected=expected.allowed_claim_ids,
            actual=actual.allowed_claim_ids,
        )
    )
    details.extend(
        _blocked_details(
            label="claim",
            expected_blocked=expected.forbidden_claim_ids,
            actual_allowed=actual.allowed_claim_ids,
            actual_blocked=actual.blocked_claim_ids,
        )
    )
    block_reason = actual.block_reason or ""
    for expected_text in expected.expected_block_reason_contains:
        if expected_text not in block_reason:
            details.append(
                "missing_block_reason_text="
                + expected_text
                + f" actual_reason={block_reason!r}"
            )
    if not details:
        return ()
    return (
        _failure(
            entry,
            "director",
            tuple(details),
            expected.to_payload(),
            actual.to_payload(),
        ),
    )


def _compare_action_intake(
    entry: P0RegressionCase,
    expected: P0ActionIntakeExpectation,
    actual: P0ActionIntakeActual | None,
) -> tuple[P0RegressionFailure, ...]:
    if actual is None:
        return (
            _failure(
                entry,
                "action_intake",
                ("actual_action_intake_missing",),
                expected.to_payload(),
                {},
            ),
        )
    details: list[str] = []
    _append_if_mismatch(details, "status", expected.expected_status, actual.status)
    _append_if_mismatch(
        details,
        "action_type",
        expected.expected_action_type,
        actual.action_type,
    )
    _append_if_mismatch(details, "target_id", expected.expected_target_id, actual.target_id)
    _append_if_mismatch(
        details,
        "subject_id",
        expected.expected_subject_id,
        actual.subject_id,
    )
    _append_if_mismatch(details, "clue_id", expected.expected_clue_id, actual.clue_id)
    _append_if_mismatch(details, "claim_id", expected.expected_claim_id, actual.claim_id)
    if expected.expected_missing_slots is not None and set(
        expected.expected_missing_slots
    ) != set(actual.missing_slots):
        details.append(
            "missing_slots expected="
            + ",".join(expected.expected_missing_slots)
            + " actual="
            + ",".join(actual.missing_slots)
        )
    reason = actual.reason or ""
    for expected_text in expected.expected_reason_contains:
        if expected_text not in reason:
            details.append(
                "missing_reason_text="
                + expected_text
                + f" actual_reason={reason!r}"
            )
    if not details:
        return ()
    return (
        _failure(
            entry,
            "action_intake",
            tuple(details),
            expected.to_payload(),
            actual.to_payload(),
        ),
    )


def _compare_deduction(
    entry: P0RegressionCase,
    expected: P0DeductionExpectation,
    actual: P0DeductionActual | None,
) -> tuple[P0RegressionFailure, ...]:
    if actual is None:
        return (
            _failure(
                entry,
                "deduction",
                ("actual_deduction_missing",),
                expected.to_payload(),
                {},
            ),
        )
    details: list[str] = []
    if expected.expected_accepted != actual.accepted:
        details.append(
            f"accepted expected={expected.expected_accepted} actual={actual.accepted}"
        )
    _append_if_mismatch(details, "claim_id", expected.expected_claim_id, actual.claim_id)
    _append_if_mismatch(details, "result", expected.expected_result, actual.result)
    _append_if_mismatch(
        details,
        "reject_code",
        expected.expected_reject_code,
        actual.reject_code,
    )
    if expected.expected_missing_evidence is not None and tuple(
        expected.expected_missing_evidence
    ) != actual.missing_evidence:
        details.append(
            "missing_evidence expected="
            + ",".join(expected.expected_missing_evidence)
            + " actual="
            + ",".join(actual.missing_evidence)
        )
    if expected.expected_missing_world_info is not None and tuple(
        expected.expected_missing_world_info
    ) != actual.missing_world_info:
        details.append(
            "missing_world_info expected="
            + ",".join(expected.expected_missing_world_info)
            + " actual="
            + ",".join(actual.missing_world_info)
        )
    if not details:
        return ()
    return (
        _failure(
            entry,
            "deduction",
            tuple(details),
            expected.to_payload(),
            actual.to_payload(),
        ),
    )


def _failure(
    entry: P0RegressionCase,
    dimension: P0Dimension,
    details: tuple[str, ...],
    expected: Mapping[str, object],
    actual: Mapping[str, object],
) -> P0RegressionFailure:
    return P0RegressionFailure(
        entry_id=entry.stable_id,
        case_id=entry.case_id,
        phase=entry.phase,
        input_text=entry.input_text,
        dimension=dimension,
        details=details,
        expected=expected,
        actual=actual,
        notes=entry.notes,
    )


def _missing_details(
    *,
    label: str,
    expected: tuple[str, ...],
    actual: tuple[str, ...],
) -> tuple[str, ...]:
    actual_set = set(actual)
    missing = tuple(item for item in expected if item not in actual_set)
    if not missing:
        return ()
    return (label + "=" + ",".join(missing),)


def _blocked_details(
    *,
    label: str,
    expected_blocked: tuple[str, ...],
    actual_allowed: tuple[str, ...],
    actual_blocked: tuple[str, ...],
) -> tuple[str, ...]:
    details: list[str] = []
    allowed_set = set(actual_allowed)
    blocked_set = set(actual_blocked)
    allowed_forbidden = tuple(item for item in expected_blocked if item in allowed_set)
    unblocked_forbidden = tuple(item for item in expected_blocked if item not in blocked_set)
    if allowed_forbidden:
        details.append(f"allowed_forbidden_{label}_ids=" + ",".join(allowed_forbidden))
    if unblocked_forbidden:
        details.append(f"unblocked_forbidden_{label}_ids=" + ",".join(unblocked_forbidden))
    return tuple(details)


def _append_if_mismatch(
    details: list[str],
    field_name: str,
    expected: str | None,
    actual: str | None,
) -> None:
    if expected is not None and expected != actual:
        details.append(f"{field_name} expected={expected!r} actual={actual!r}")


def _memory_expectation_from_mapping(value: object) -> P0MemoryExpectation | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("P0 memory expectation must be a mapping")
    return P0MemoryExpectation(
        expected_memory_ids=_string_tuple(value.get("expected_memory_ids")),
        forbidden_memory_ids=_string_tuple(value.get("forbidden_memory_ids")),
    )


def _director_expectation_from_mapping(value: object) -> P0DirectorExpectation | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("P0 director expectation must be a mapping")
    return P0DirectorExpectation(
        expected_allowed=_optional_bool(value.get("expected_allowed")),
        allowed_world_info_ids=_string_tuple(value.get("allowed_world_info_ids")),
        forbidden_world_info_ids=_string_tuple(value.get("forbidden_world_info_ids")),
        allowed_claim_ids=_string_tuple(value.get("allowed_claim_ids")),
        forbidden_claim_ids=_string_tuple(value.get("forbidden_claim_ids")),
        expected_block_reason_contains=_string_tuple(
            value.get("expected_block_reason_contains")
        ),
    )


def _action_expectation_from_mapping(
    value: object,
) -> P0ActionIntakeExpectation | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("P0 action_intake expectation must be a mapping")
    return P0ActionIntakeExpectation(
        expected_status=_action_status(value.get("expected_status")),
        expected_action_type=_optional_string(value.get("expected_action_type")),
        expected_target_id=_optional_string(value.get("expected_target_id")),
        expected_subject_id=_optional_string(value.get("expected_subject_id")),
        expected_clue_id=_optional_string(value.get("expected_clue_id")),
        expected_claim_id=_optional_string(value.get("expected_claim_id")),
        expected_missing_slots=_optional_string_tuple(value.get("expected_missing_slots")),
        expected_reason_contains=_string_tuple(value.get("expected_reason_contains")),
    )


def _deduction_expectation_from_mapping(
    value: object,
) -> P0DeductionExpectation | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("P0 deduction expectation must be a mapping")
    expected_accepted = value.get("expected_accepted")
    if not isinstance(expected_accepted, bool):
        raise ValueError("P0 deduction expectation requires expected_accepted")
    return P0DeductionExpectation(
        expected_accepted=expected_accepted,
        expected_claim_id=_optional_string(value.get("expected_claim_id")),
        expected_result=_optional_string(value.get("expected_result")),
        expected_reject_code=_optional_string(value.get("expected_reject_code")),
        expected_missing_evidence=_optional_string_tuple(
            value.get("expected_missing_evidence")
        ),
        expected_missing_world_info=_optional_string_tuple(
            value.get("expected_missing_world_info")
        ),
    )


def _action_status(value: object) -> ActionIntakeStatus:
    if value not in {"accepted", "ambiguous", "rejected"}:
        raise ValueError("P0 action_intake expected_status is invalid")
    return value  # type: ignore[return-value]


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("P0 optional bool fields must be bool")
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"P0 regression matrix entry requires {field_name}")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("P0 optional string fields must be strings")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("P0 string tuple fields must be lists")
    return tuple(_string(item, "list item") for item in value)


def _optional_string_tuple(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _string_tuple(value)


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", value)
    if enum_value is None:
        return None
    return str(enum_value)


def _required_attr(target: object, field_name: str) -> object:
    return getattr(target, field_name)


def _payload(**items: object) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in items.items():
        if value is None:
            continue
        if isinstance(value, tuple):
            payload[key] = list(value)
        else:
            payload[key] = value
    return payload


def _json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _slug(value: str) -> str:
    compact = "".join(char if char.isalnum() else "_" for char in value.strip().lower())
    return "_".join(part for part in compact.split("_") if part)[:80] or "input"
