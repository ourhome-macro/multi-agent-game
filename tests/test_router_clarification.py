from __future__ import annotations

from pathlib import Path

import pytest

from app.cases.loader import CaseLoader
from app.runtime.action_router import ActionRouter, ActionRouteStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


@pytest.fixture()
def router() -> ActionRouter:
    return ActionRouter(CaseLoader().load(CASE_DIR))


@pytest.mark.parametrize(
    ("raw_text", "missing_slots"),
    [
        ("我问医生那个东西", {"target", "subject"}),
        ("我问医生药的事", {"target", "subject"}),
        ("我把那个东西给江医生看", {"clue"}),
        ("我问他空胶囊", {"target"}),
        ("我看看那个地方", {"target"}),
        ("我调查一下现场", {"target"}),
        ("我找那个人聊聊", {"target"}),
        ("我出示空胶囊", {"target"}),
        ("把线索给江医生看", {"clue"}),
    ],
)
def test_router_requests_clarification_for_ambiguous_input(
    router: ActionRouter,
    raw_text: str,
    missing_slots: set[str],
) -> None:
    result = router.route(raw_text)

    assert result.status == ActionRouteStatus.NEEDS_CLARIFICATION
    assert result.needs_clarification is True
    assert set(result.missing_slots) == missing_slots
    assert result.action is None


@pytest.mark.parametrize(
    "raw_text",
    [
        "我先检查药盒，再去问江医生空胶囊",
        "我检查配电箱，然后把空胶囊给江医生看",
        "我去书房看看门锁，再回来指控江医生",
        "我一边问江医生，一边把空胶囊给他看",
    ],
)
def test_router_rejects_multiple_actions(router: ActionRouter, raw_text: str) -> None:
    result = router.route(raw_text)

    assert result.status == ActionRouteStatus.NEEDS_CLARIFICATION
    assert result.reason == "multiple_actions_detected"
    assert result.missing_slots == ["action"]
    assert result.action is None


@pytest.mark.parametrize(
    ("raw_text", "reason"),
    [
        ("我检查火箭发射器", "unknown_hotspot"),
        ("我问张三空胶囊的事", "unknown_target"),
        ("我把不存在的钥匙给江医生看", "unknown_clue"),
        ("我指控猫是凶手", "unknown_target"),
        ("我调查月球基地", "unknown_hotspot"),
    ],
)
def test_router_reports_unknown_entities(
    router: ActionRouter,
    raw_text: str,
    reason: str,
) -> None:
    result = router.route(raw_text)

    assert result.status == ActionRouteStatus.UNKNOWN
    assert result.reason == reason
    assert result.action is None
