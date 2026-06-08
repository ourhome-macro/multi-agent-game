from __future__ import annotations

import pytest

from app.runtime.action_router import ActionClassifier, ActionRouteStatus, ClassifiedAction


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("我检查药盒", ClassifiedAction.INSPECT),
        ("查看药盒", ClassifiedAction.INSPECT),
        ("看看药盒里有什么", ClassifiedAction.INSPECT),
        ("调查药柜里的药盒", ClassifiedAction.INSPECT),
        ("检查配电箱", ClassifiedAction.INSPECT),
        ("看看电闸有没有问题", ClassifiedAction.INSPECT),
        ("我找江医生聊聊", ClassifiedAction.TALK),
        ("和江医生对话", ClassifiedAction.TALK),
        ("我想跟江言晖说话", ClassifiedAction.TALK),
        ("去问问江医生现在怎么看", ClassifiedAction.TALK),
        ("我问江医生空胶囊的事情", ClassifiedAction.ASK_ABOUT),
        ("我想问江医生关于空胶囊", ClassifiedAction.ASK_ABOUT),
        ("我质问江医生空胶囊是不是他动过", ClassifiedAction.ASK_ABOUT),
        ("把空胶囊给江医生看", ClassifiedAction.PRESENT_CLUE),
        ("我拿空胶囊给江医生", ClassifiedAction.PRESENT_CLUE),
        ("我拿出空胶囊质问江医生", ClassifiedAction.PRESENT_CLUE),
        ("我让江医生看看空胶囊", ClassifiedAction.PRESENT_CLUE),
        ("我指控江医生造成了共同死亡链", ClassifiedAction.ACCUSE),
        ("我认为江医生是凶手", ClassifiedAction.ACCUSE),
        ("凶手是江医生", ClassifiedAction.ACCUSE),
        ("江医生导致了共同死亡链", ClassifiedAction.ACCUSE),
    ],
)
def test_action_classifier_recognizes_action_type(
    raw_text: str,
    expected: ClassifiedAction,
) -> None:
    result = ActionClassifier().classify(raw_text)

    assert result.status == ActionRouteStatus.RESOLVED
    assert result.action == expected


@pytest.mark.parametrize(
    "raw_text",
    [
        "我先检查药盒，再去问江医生空胶囊",
        "我检查配电箱，然后把空胶囊给江医生看",
        "我去书房看看门锁，再回来指控江医生",
        "我一边问江医生，一边把空胶囊给他看",
    ],
)
def test_action_classifier_rejects_multiple_actions(raw_text: str) -> None:
    result = ActionClassifier().classify(raw_text)

    assert result.status == ActionRouteStatus.NEEDS_CLARIFICATION
    assert result.reason == "multiple_actions_detected"
    assert result.action is None


@pytest.mark.parametrize(
    "raw_text",
    [
        "我不觉得江医生是凶手",
        "我不认为江医生是凶手",
        "我不指控江医生",
        "我没有要指控江医生",
    ],
)
def test_action_classifier_does_not_turn_negation_into_accuse(raw_text: str) -> None:
    result = ActionClassifier().classify(raw_text)

    assert result.action != ClassifiedAction.ACCUSE


def test_action_classifier_returns_unknown_for_unrecognized_input() -> None:
    result = ActionClassifier().classify("这里好像有点奇怪")

    assert result.status == ActionRouteStatus.UNKNOWN
    assert result.action is None
