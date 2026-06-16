from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, EventType, PlayerAction, SessionState
from app.rules.deduction import DeductionEvaluator
from app.runtime.service import RuntimeContainer, create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_deduction_evaluator_accepts_complete_claim() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_all_required_clues(runtime, session)
    action = PlayerAction(
        type=ActionType.ACCUSE,
        target_id="butler",
        claim_id="butler_moved_key",
        evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
    )

    result = DeductionEvaluator().evaluate(case=case, session=session, action=action)

    assert result.accepted is True
    assert result.matched_claim == "butler_moved_key"
    assert result.matched_required_evidence == [
        "dustless_frame",
        "scratched_drawer",
        "torn_note",
    ]
    assert result.missing_evidence == []
    assert result.missing_world_info == []
    assert result.phase_allowed is True
    assert result.target_matches is True
    assert result.result == "correct"
    assert result.reject_code is None


def test_deduction_evaluator_reports_missing_required_evidence() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_all_required_clues(runtime, session)
    action = PlayerAction(
        type=ActionType.ACCUSE,
        target_id="butler",
        claim_id="butler_moved_key",
        evidence_clue_ids=["scratched_drawer"],
    )

    result = DeductionEvaluator().evaluate(case=case, session=session, action=action)

    assert result.accepted is False
    assert result.reject_code == "missing_required_evidence"
    assert result.matched_claim == "butler_moved_key"
    assert result.matched_required_evidence == ["scratched_drawer"]
    assert result.missing_evidence == ["dustless_frame", "torn_note"]
    assert result.missing_world_info == []
    assert result.phase_allowed is True
    assert result.target_matches is True
    assert result.result is None


def test_deduction_evaluator_reports_missing_world_info() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_all_required_clues(runtime, session)
    session.player_knowledge["player_knowledge.portrait_was_moved"].world_info_id = None
    action = PlayerAction(
        type=ActionType.ACCUSE,
        target_id="butler",
        claim_id="butler_moved_key",
        evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
    )

    result = DeductionEvaluator().evaluate(case=case, session=session, action=action)

    assert result.accepted is False
    assert result.reject_code == "missing_required_world_info"
    assert result.missing_player_knowledge is None
    assert result.missing_world_info == ["portrait_was_moved"]
    assert result.phase_allowed is True
    assert result.target_matches is True


def test_deduction_evaluator_reports_phase_not_allowed() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    action = PlayerAction(
        type=ActionType.ACCUSE,
        target_id="butler",
        claim_id="butler_moved_key",
        evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
    )

    result = DeductionEvaluator().evaluate(case=case, session=session, action=action)

    assert result.accepted is False
    assert result.reject_code == "phase_not_allowed"
    assert result.matched_claim == "butler_moved_key"
    assert result.phase_allowed is False
    assert result.target_matches is True
    assert result.missing_evidence == []
    assert result.missing_world_info == [
        "desk_forced_open",
        "portrait_was_moved",
        "secret_meeting_note_exists",
    ]


def test_deduction_evaluator_reports_target_mismatch() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    action = PlayerAction(
        type=ActionType.ACCUSE,
        target_id="butler",
        claim_id="niece_staged_meeting",
        evidence_clue_ids=["torn_note"],
    )

    result = DeductionEvaluator().evaluate(case=case, session=session, action=action)

    assert result.accepted is False
    assert result.reject_code == "target_mismatch"
    assert result.matched_claim == "niece_staged_meeting"
    assert result.target_matches is False
    assert result.result is None


def test_deduction_evaluator_and_apply_accuse_share_acceptance_semantics() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _discover_all_required_clues(runtime, session)
    action = PlayerAction(
        type=ActionType.ACCUSE,
        target_id="butler",
        claim_id="butler_moved_key",
        evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
    )

    result = DeductionEvaluator().evaluate(case=case, session=session, action=action)
    events = runtime.rule_engine.apply_accuse(case=case, session=session, action=action)

    assert result.accepted is True
    assert [event.type for event in events] == [
        EventType.PLAYER_ACCUSED,
        EventType.ACCUSATION_EVALUATED,
    ]
    assert events[1].payload["result"] == result.result
    assert events[1].payload["matched_required_evidence"] == result.matched_required_evidence
    assert events[1].payload["missing_required_evidence"] == result.missing_evidence


def _discover_all_required_clues(runtime: RuntimeContainer, session: SessionState) -> None:
    for target_id in ("desk", "portrait", "carpet"):
        runtime.action_service.handle(
            session=session,
            action=PlayerAction(type=ActionType.INSPECT, target_id=target_id),
        )
