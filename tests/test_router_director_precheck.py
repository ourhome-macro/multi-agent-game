from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.director.narrative_director import NarrativeDirector
from app.domain.models import ActionType, EventType, PlayerAction, SubjectType
from app.runtime.action_router import ActionRouter, ActionRouteStatus
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


def test_director_precheck_blocks_undiscovered_clue_from_routed_ask_about() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    routed = ActionRouter(case).route("我问江医生空胶囊是不是他动过")

    assert routed.status == ActionRouteStatus.RESOLVED
    assert routed.action is not None

    decision = NarrativeDirector().precheck_player_action(case, session, routed.action)

    assert decision.allowed is False
    assert decision.reason == "subject_not_discovered"


def test_rule_engine_still_rejects_undiscovered_clue_as_authority() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    routed = ActionRouter(case).route("我问江医生空胶囊是不是他动过")
    assert routed.action is not None

    response = runtime.action_service.handle(session=session, action=routed.action)

    assert response.accepted is False
    assert response.new_events[0].type == EventType.RULE_REJECTED
    assert response.new_events[0].payload["reason"] == "subject clue has not been discovered"


def test_director_precheck_allows_discovered_clue_ask_about() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="medicine_box"),
    )
    routed = ActionRouter(case).route("我问江医生空胶囊是不是他动过")
    assert routed.action is not None

    decision = NarrativeDirector().precheck_player_action(case, session, routed.action)

    assert decision.allowed is True


def test_director_precheck_blocks_presenting_undiscovered_clue() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    routed = ActionRouter(case).route("把空胶囊给江医生看")
    assert routed.action is not None

    decision = NarrativeDirector().precheck_player_action(case, session, routed.action)

    assert decision.allowed is False
    assert decision.reason == "clue_not_discovered"


def test_director_precheck_blocks_claim_before_available_phase() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    routed = ActionRouter(case).route("我指控江医生造成了共同死亡链")
    assert routed.action is not None

    decision = NarrativeDirector().precheck_player_action(case, session, routed.action)

    assert decision.allowed is False
    assert decision.reason == "claim_not_available"


def test_director_precheck_blocks_premature_generic_accusation() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    action = PlayerAction(
        type=ActionType.ACCUSE,
        target_id="jiang_yanhui",
        claim_id="shared_death_chain",
        evidence_clue_ids=[],
        text="凶手是不是你",
    )

    decision = NarrativeDirector().precheck_player_action(case, session, action)

    assert decision.allowed is False
    assert decision.reason == "claim_not_available"


def test_director_precheck_accepts_non_clue_subjects() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    action = PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id="jiang_yanhui",
        subject_type=SubjectType.CHARACTER,
        subject_id="lin_qichi",
        text="我问江医生林栖迟的事情",
    )

    decision = NarrativeDirector().precheck_player_action(case, session, action)

    assert decision.allowed is True
