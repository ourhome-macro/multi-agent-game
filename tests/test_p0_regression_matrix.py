from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.cases.loader import CaseLoader
from app.director.narrative_director import NarrativeDirector
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    CharacterFactStance,
    CharacterInnerContext,
    DisclosureClaim,
    DisclosureMode,
    FactDisclosureStrategy,
    PlayerAction,
    RhetoricTactic,
    SessionState,
)
from app.evaluations.p0_regression_matrix import (
    P0ActionIntakeExpectation,
    P0DeductionExpectation,
    P0DirectorExpectation,
    P0MemoryExpectation,
    P0RegressionActual,
    P0RegressionCase,
    action_intake_actual_from_route_result,
    deduction_actual_from_result,
    director_actual_from_decision,
    evaluate_p0_regression_matrix,
    load_p0_regression_matrix,
    memory_actual_from_ids,
)
from app.rules.deduction import DeductionEvaluator
from app.runtime.service import RuntimeContainer, create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_p0_regression_matrix_validates_all_p0_dimensions_without_llm() -> None:
    actual_by_id = _actuals_from_deterministic_components()
    entries = [
        P0RegressionCase(
            entry_id="p0.memory.allow_deny",
            case_id="fake_case_001",
            phase="opening",
            input_text="ask butler about drawer pressure",
            memory=P0MemoryExpectation(
                expected_memory_ids=("memory.butler.drawer",),
                forbidden_memory_ids=("memory.niece.private_timeline",),
            ),
        ),
        P0RegressionCase(
            entry_id="p0.director.allow_hint",
            case_id="fake_case_001",
            phase="opening",
            input_text="butler gives a constrained hint",
            director=P0DirectorExpectation(
                expected_allowed=True,
                allowed_world_info_ids=("will_swapped",),
                allowed_claim_ids=("will_swapped:hint",),
            ),
        ),
        P0RegressionCase(
            entry_id="p0.director.deny_full",
            case_id="fake_case_001",
            phase="opening",
            input_text="butler attempts full reveal of locked will fact",
            director=P0DirectorExpectation(
                expected_allowed=False,
                forbidden_world_info_ids=("will_swapped",),
                forbidden_claim_ids=("will_swapped:full",),
                expected_block_reason_contains=("attempted full reveal",),
            ),
        ),
        P0RegressionCase(
            entry_id="p0.action.ambiguous",
            case_id="fake_case_001",
            phase="opening",
            input_text="ask the doctor about that thing",
            action_intake=P0ActionIntakeExpectation(
                expected_status="ambiguous",
                expected_missing_slots=("target", "subject"),
                expected_reason_contains=("ambiguous_route",),
            ),
        ),
        P0RegressionCase(
            entry_id="p0.action.reject_unknown",
            case_id="fake_case_001",
            phase="opening",
            input_text="inspect the rocket launcher",
            action_intake=P0ActionIntakeExpectation(
                expected_status="rejected",
                expected_reason_contains=("unknown_hotspot",),
            ),
        ),
        P0RegressionCase(
            entry_id="p0.deduction.accept",
            case_id="fake_case_001",
            phase="reveal",
            input_text="accuse butler with the full evidence set",
            deduction=P0DeductionExpectation(
                expected_accepted=True,
                expected_claim_id="butler_moved_key",
                expected_result="correct",
            ),
        ),
        P0RegressionCase(
            entry_id="p0.deduction.reject",
            case_id="fake_case_001",
            phase="reveal",
            input_text="accuse butler with only one clue",
            deduction=P0DeductionExpectation(
                expected_accepted=False,
                expected_claim_id="butler_moved_key",
                expected_reject_code="missing_required_evidence",
                expected_missing_evidence=("dustless_frame", "torn_note"),
                expected_missing_world_info=(),
            ),
        ),
    ]

    report = evaluate_p0_regression_matrix(
        entries=entries,
        actual_provider=lambda entry: actual_by_id[entry.stable_id],
    )

    report.assert_passed()


def test_p0_regression_matrix_failure_message_identifies_case_phase_input_expected_actual() -> None:
    entry = P0RegressionCase(
        entry_id="p0.memory.failure_fixture",
        case_id="fake_case_001",
        phase="opening",
        input_text="ask butler about private niece timeline",
        memory=P0MemoryExpectation(
            expected_memory_ids=("memory.butler.drawer",),
            forbidden_memory_ids=("memory.niece.private_timeline",),
        ),
        notes="failure text must be actionable in CI",
    )
    report = evaluate_p0_regression_matrix(
        entries=[entry],
        actual_provider=lambda _entry: P0RegressionActual(
            memory=memory_actual_from_ids(["memory.niece.private_timeline"])
        ),
    )

    assert not report.passed
    failure = report.failures[0]
    assert failure.entry_id == "p0.memory.failure_fixture"
    assert failure.case_id == "fake_case_001"
    assert failure.phase == "opening"
    assert failure.input_text == "ask butler about private niece timeline"

    with pytest.raises(AssertionError) as exc:
        report.assert_passed()
    message = str(exc.value)
    assert "p0.memory.failure_fixture" in message
    assert "case_id=fake_case_001" in message
    assert "phase=opening" in message
    assert "input='ask butler about private niece timeline'" in message
    assert "expected=" in message
    assert "actual=" in message
    assert "memory.butler.drawer" in message
    assert "memory.niece.private_timeline" in message


def test_p0_regression_matrix_loads_yaml_entries() -> None:
    entries = load_p0_regression_matrix(
        PROJECT_ROOT / "tests" / "fixtures" / "p0_regression_matrix.yaml"
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry.stable_id == "p0.loaded.case"
    assert entry.expected_dimensions == (
        "memory",
        "director",
        "action_intake",
        "deduction",
    )
    assert entry.memory is not None
    assert entry.memory.expected_memory_ids == ("memory.butler.drawer",)
    assert entry.director is not None
    assert entry.director.expected_allowed is False
    assert entry.action_intake is not None
    assert entry.action_intake.expected_missing_slots == ("target",)
    assert entry.deduction is not None
    assert entry.deduction.expected_reject_code == "missing_required_evidence"


def _actuals_from_deterministic_components() -> dict[str, P0RegressionActual]:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    context = _butler_context(session)
    director = NarrativeDirector()
    allow_decision = director.validate(
        case,
        session.narrative,
        AgentIntent(
            speech="I can only point around the document problem.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim("will_swapped", DisclosureMode.HINT)],
        ),
        context,
    )
    deny_decision = director.validate(
        case,
        session.narrative,
        AgentIntent(
            speech="I should not reveal the full will fact.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim("will_swapped", DisclosureMode.FULL)],
        ),
        context,
    )

    reveal_session = runtime.session_store.create(case)
    reveal_session.narrative.phase = "reveal"
    _discover_all_required_clues(runtime, reveal_session)
    accept_result = DeductionEvaluator().evaluate(
        case=case,
        session=reveal_session,
        action=PlayerAction(
            type=ActionType.ACCUSE,
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
        ),
    )
    reject_result = DeductionEvaluator().evaluate(
        case=case,
        session=reveal_session,
        action=PlayerAction(
            type=ActionType.ACCUSE,
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer"],
        ),
    )

    return {
        "p0.memory.allow_deny": P0RegressionActual(
            memory=memory_actual_from_ids(["memory.butler.drawer"])
        ),
        "p0.director.allow_hint": P0RegressionActual(
            director=director_actual_from_decision(
                allow_decision,
                requested_world_info_ids=["will_swapped"],
                requested_claim_ids=["will_swapped:hint"],
            )
        ),
        "p0.director.deny_full": P0RegressionActual(
            director=director_actual_from_decision(
                deny_decision,
                requested_world_info_ids=["will_swapped"],
                requested_claim_ids=["will_swapped:full"],
            )
        ),
        "p0.action.ambiguous": P0RegressionActual(
            action_intake=action_intake_actual_from_route_result(
                _RouteResult(
                    status="needs_clarification",
                    action=None,
                    missing_slots=["target", "subject"],
                    reason="ambiguous_route",
                )
            )
        ),
        "p0.action.reject_unknown": P0RegressionActual(
            action_intake=action_intake_actual_from_route_result(
                _RouteResult(
                    status="unknown",
                    action=None,
                    missing_slots=[],
                    reason="unknown_hotspot",
                )
            )
        ),
        "p0.deduction.accept": P0RegressionActual(
            deduction=deduction_actual_from_result(accept_result)
        ),
        "p0.deduction.reject": P0RegressionActual(
            deduction=deduction_actual_from_result(reject_result)
        ),
    }


def _butler_context(session: SessionState) -> AgentContext:
    return AgentContext(
        case_id="fake_case_001",
        session_id=session.id,
        target_agent_id="butler",
        current_phase=session.narrative.phase,
        player_action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="probe will disclosure",
        ),
        inner_context=CharacterInnerContext(
            character_id="butler",
            fact_disclosure_strategies=[
                FactDisclosureStrategy(
                    world_info_id="will_swapped",
                    stance=CharacterFactStance.KNOWS,
                    allowed_modes=[DisclosureMode.HINT],
                    forbidden_modes=[DisclosureMode.FULL],
                    rhetoric_tactics=[RhetoricTactic.SHIFT_FOCUS],
                    source_awareness_id="test.awareness.butler.will_swapped",
                )
            ],
        ),
    )


def _claim(world_info_id: str, mode: DisclosureMode) -> DisclosureClaim:
    return DisclosureClaim(
        world_info_id=world_info_id,
        mode=mode,
        tactic=RhetoricTactic.SHIFT_FOCUS,
    )


def _discover_all_required_clues(runtime: RuntimeContainer, session: SessionState) -> None:
    for target_id in ("desk", "portrait", "carpet"):
        runtime.action_service.handle(
            session=session,
            action=PlayerAction(type=ActionType.INSPECT, target_id=target_id),
        )


@dataclass(frozen=True)
class _RouteResult:
    status: str
    action: object | None
    missing_slots: list[str] = field(default_factory=list)
    reason: str | None = None
