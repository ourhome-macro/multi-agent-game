from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, SubjectType
from app.runtime.action_router import ActionRouter, ActionRouteStatus
from scripts.run_terminal_mvp import parse_player_command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


@pytest.fixture()
def router() -> ActionRouter:
    return ActionRouter(CaseLoader().load(CASE_DIR))


ROUTER_CASES = [
    ("我检查药盒", ActionType.INSPECT, None, "medicine_box"),
    ("查看药盒", ActionType.INSPECT, None, "medicine_box"),
    ("看看药盒里有什么", ActionType.INSPECT, None, "medicine_box"),
    ("检查一下药瓶", ActionType.INSPECT, None, "medicine_box"),
    ("调查药柜里的药盒", ActionType.INSPECT, None, "medicine_box"),
    ("检查配电箱", ActionType.INSPECT, None, "breaker_box"),
    ("看看电闸有没有问题", ActionType.INSPECT, None, "breaker_box"),
    ("调查电箱", ActionType.INSPECT, None, "breaker_box"),
    ("查看断路器", ActionType.INSPECT, None, "breaker_box"),
    ("我找江医生聊聊", ActionType.TALK, "jiang_yanhui", None),
    ("和江医生对话", ActionType.TALK, "jiang_yanhui", None),
    ("我想跟江言晖说话", ActionType.TALK, "jiang_yanhui", None),
    ("去问问江医生现在怎么看", ActionType.TALK, "jiang_yanhui", None),
    ("我想看看江医生会说什么", ActionType.TALK, "jiang_yanhui", None),
    ("我问江医生空胶囊的事情", ActionType.ASK_ABOUT, "jiang_yanhui", "empty_capsules"),
    ("我想问江医生关于空胶囊", ActionType.ASK_ABOUT, "jiang_yanhui", "empty_capsules"),
    ("我质问江医生空胶囊是不是他动过", ActionType.ASK_ABOUT, "jiang_yanhui", "empty_capsules"),
    ("我问江医生药盒为什么是空的", ActionType.ASK_ABOUT, "jiang_yanhui", "empty_capsules"),
    ("把空胶囊给江医生看", ActionType.PRESENT_CLUE, "jiang_yanhui", "empty_capsules"),
    ("我拿空胶囊给江医生", ActionType.PRESENT_CLUE, "jiang_yanhui", "empty_capsules"),
    ("我拿出空胶囊质问江医生", ActionType.PRESENT_CLUE, "jiang_yanhui", "empty_capsules"),
    ("我让江医生看看空胶囊", ActionType.PRESENT_CLUE, "jiang_yanhui", "empty_capsules"),
    ("我把药盒递给江医生", ActionType.PRESENT_CLUE, "jiang_yanhui", "empty_capsules"),
    ("我指控江医生造成了共同死亡链", ActionType.ACCUSE, "jiang_yanhui", "shared_death_chain"),
    ("我怀疑江医生造成了共同死亡链", ActionType.ACCUSE, "jiang_yanhui", "shared_death_chain"),
    ("凶手是江医生", ActionType.ACCUSE, "jiang_yanhui", "shared_death_chain"),
    ("江医生导致了共同死亡链", ActionType.ACCUSE, "jiang_yanhui", "shared_death_chain"),
    ("我认为林栖迟在红酒里下毒", ActionType.ACCUSE, "lin_qichi", "lin_poisoned_lu"),
]


@pytest.mark.parametrize(
    ("raw_text", "action_type", "target_id", "object_id"),
    ROUTER_CASES,
)
def test_router_maps_natural_language_to_player_action(
    router: ActionRouter,
    raw_text: str,
    action_type: ActionType,
    target_id: str | None,
    object_id: str | None,
) -> None:
    result = router.route(raw_text)

    assert result.status == ActionRouteStatus.RESOLVED
    assert result.action is not None
    assert result.action.type == action_type
    assert result.action.text == raw_text if action_type != ActionType.INSPECT else True
    if target_id is not None:
        assert result.action.target_id == target_id
    if action_type == ActionType.INSPECT:
        assert result.action.target_id == object_id
    elif action_type == ActionType.ASK_ABOUT:
        assert result.action.subject_type == SubjectType.CLUE
        assert result.action.subject_id == object_id
    elif action_type == ActionType.PRESENT_CLUE:
        assert result.action.clue_id == object_id
    elif action_type == ActionType.ACCUSE:
        assert result.action.claim_id == object_id


@pytest.mark.parametrize(
    "raw_text",
    [
        "我问江医生",
        "去问问江医生现在怎么看",
        "我跟江医生聊聊",
    ],
)
def test_router_treats_ask_without_subject_as_talk(
    router: ActionRouter,
    raw_text: str,
) -> None:
    result = router.route(raw_text)

    assert result.status == ActionRouteStatus.RESOLVED
    assert result.action is not None
    assert result.action.type == ActionType.TALK
    assert result.action.target_id == "jiang_yanhui"


def test_router_prefers_present_clue_when_showing_and_questioning_overlap(
    router: ActionRouter,
) -> None:
    result = router.route("我拿出空胶囊质问江医生")

    assert result.status == ActionRouteStatus.RESOLVED
    assert result.action is not None
    assert result.action.type == ActionType.PRESENT_CLUE
    assert result.action.target_id == "jiang_yanhui"
    assert result.action.clue_id == "empty_capsules"


def test_router_handles_negated_accusation_without_accusing(router: ActionRouter) -> None:
    result = router.route("我不觉得江医生是凶手")

    assert result.status == ActionRouteStatus.RESOLVED
    assert result.action is not None
    assert result.action.type == ActionType.TALK
    assert result.action.target_id == "jiang_yanhui"


def test_terminal_parser_accepts_natural_language_when_case_is_provided() -> None:
    case = CaseLoader().load(CASE_DIR)
    parsed = parse_player_command("我问江医生关于空胶囊的事情", case=case)

    assert parsed.action is not None
    assert parsed.command == "natural_language"
    assert parsed.action.type == ActionType.ASK_ABOUT
    assert parsed.action.target_id == "jiang_yanhui"
    assert parsed.action.subject_id == "empty_capsules"


def test_terminal_mvp_accepts_natural_language_input_sequence(tmp_path: Path) -> None:
    trace_jsonl = tmp_path / "trace.jsonl"
    trace_log = tmp_path / "trace.log"
    commands = "我检查药盒\n我问江医生关于空胶囊的事情\nquit\n"

    result = subprocess.run(
        [
            sys.executable,
            "scripts\\run_terminal_mvp.py",
            "--case-id",
            "mist_clock_manor",
            "--trace-jsonl",
            str(trace_jsonl),
            "--trace-log",
            str(trace_log),
        ],
        cwd=PROJECT_ROOT,
        input=commands,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "needs clarification" not in result.stdout
    assert result.stdout.count("accepted=true") == 2
    assert '"action_type": "ask_about"' in trace_jsonl.read_text(encoding="utf-8")
