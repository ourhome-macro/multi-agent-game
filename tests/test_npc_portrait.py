from __future__ import annotations

from pathlib import Path

from app.agents.context import build_agent_context
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, NPCPortraitState, PlayerAction
from app.runtime.memory_derivations import MEDICINE_STRATEGY_ID
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"
EMPTY_CAPSULES = "empty_capsules"
JIANG_RELATIONSHIP_MEMORY = f"memory.player.relationship.{JIANG}.{EMPTY_CAPSULES}"
JIANG_STRATEGY_MEMORY = f"memory.player.strategy.{JIANG}.{EMPTY_CAPSULES}"
JIANG_BELIEF_MEMORY = f"memory.player.belief.{JIANG}.{EMPTY_CAPSULES}"
SHEN_ASK_MEMORY = f"memory.player.asked_about.{SHEN}.clue.{EMPTY_CAPSULES}"


def test_presenting_empty_capsules_updates_jiang_player_portrait_suspicion() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    portrait = session.character_impressions[JIANG]["player"]
    assert isinstance(portrait, NPCPortraitState)
    assert portrait.owner_character_id == JIANG
    assert portrait.subject_id == "player"
    assert portrait.suspicion >= 0.2
    assert portrait.trust <= -0.1
    assert JIANG_RELATIONSHIP_MEMORY in portrait.source_memory_ids


def test_repeated_medicine_questions_set_jiang_current_strategy() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _ask_jiang_about_empty_capsules(runtime, session, "第一次问药物线索")
    _ask_jiang_about_empty_capsules(runtime, session, "继续追问药物线索")

    portrait = session.character_impressions[JIANG]["player"]
    assert portrait.current_strategy == "avoid_medicine_topic"
    assert JIANG_STRATEGY_MEMORY in portrait.source_memory_ids


def test_shen_cannot_see_jiang_player_portrait() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    context = build_agent_context(
        case,
        session,
        PlayerAction(type=ActionType.TALK, target_id=SHEN, text="空胶囊"),
    )

    assert context.portrait_summary is None
    assert context.inner_context is not None
    assert context.inner_context.inner_portraits == []
    serialized_recent_events = " ".join(
        event.model_dump_json() for event in context.recent_events
    )
    assert JIANG_BELIEF_MEMORY not in serialized_recent_events
    assert JIANG_RELATIONSHIP_MEMORY not in serialized_recent_events
    assert JIANG_STRATEGY_MEMORY not in serialized_recent_events
    assert MEDICINE_STRATEGY_ID not in serialized_recent_events


def test_replay_preserves_jiang_player_portrait() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    replayed = replay_events(case, session.events)

    assert replayed.character_impressions[JIANG]["player"] == (
        session.character_impressions[JIANG]["player"]
    )


def test_agent_context_projects_portrait_summary_without_other_npc_private_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _ask_shen_about_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    context = build_agent_context(
        case,
        session,
        PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=JIANG,
            subject_type="clue",
            subject_id=EMPTY_CAPSULES,
        ),
    )

    assert context.portrait_summary is not None
    assert "高度警惕" in context.portrait_summary
    assert EMPTY_CAPSULES not in context.portrait_summary
    assert "memory." not in context.portrait_summary
    assert SHEN_ASK_MEMORY not in {memory.memory_id for memory in context.memory_snapshots}
    assert SHEN_ASK_MEMORY not in {memory.memory_id for memory in context.memory_candidates}


def _discover_empty_capsules(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="medicine_box"),
    )


def _present_empty_capsules_to_jiang(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            text="把空胶囊给江医生看",
        ),
    )


def _ask_jiang_about_empty_capsules(runtime: object, session: object, text: str) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=JIANG,
            subject_type="clue",
            subject_id=EMPTY_CAPSULES,
            text=text,
        ),
    )


def _ask_shen_about_empty_capsules(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=SHEN,
            subject_type="clue",
            subject_id=EMPTY_CAPSULES,
            text="我问沈照夜空胶囊",
        ),
    )
