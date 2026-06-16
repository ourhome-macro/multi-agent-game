from __future__ import annotations

import json
from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, CasePackage, PlayerAction, SubjectType
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


def test_case_loader_loads_mist_clock_manor_npc_skills() -> None:
    case = CaseLoader().load(CASE_DIR)

    skills_by_id = {skill.id: skill for skill in case.npc_skills}

    assert set(skills_by_id) == {
        "jiang_lock_boundary",
        "jiang_capsule_boundary",
        "qi_tape_boundary",
        "lin_wine_boundary",
        "shen_power_boundary",
        "shen_study_lock_boundary",
        "shen_old_case_boundary",
    }
    for skill in skills_by_id.values():
        assert skill.owner_character_ids
        assert skill.triggers.action_types
        assert skill.unlock_conditions.required_player_knowledge
        assert skill.disclosure.world_info_ids
        assert skill.disclosure.max_mode.value == "hint"
        assert skill.disclosure.allowed_tactics
        assert skill.disclosure.safe_fragment_refs
        assert skill.memory.max_items is not None
        assert skill.proposed_action_policy.max_relationship_delta

    _assert_safe_fragment_refs_are_bound_to_world_info(case)


def test_mist_clock_manor_key_actions_select_expected_npc_skills() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)

    _inspect_all(
        runtime,
        session,
        [
            "study_lock",
            "tape_recorder",
            "medicine_box",
            "wine_table",
            "breaker_box",
            "tower_backup_line",
            "editing_lamp",
            "medicine_drawer_liner",
            "archive_case",
        ],
    )

    assert _selected_skill_ids(
        runtime,
        case,
        session,
        target_id="jiang_yanhui",
        clue_id="empty_capsules",
    ) == ["jiang_capsule_boundary"]
    assert _selected_skill_ids(
        runtime,
        case,
        session,
        target_id="qi_yan",
        clue_id="echo_tape",
    ) == ["qi_tape_boundary"]
    assert _selected_skill_ids(
        runtime,
        case,
        session,
        target_id="lin_qichi",
        clue_id="bitter_wine",
    ) == ["lin_wine_boundary"]
    assert _selected_skill_ids(
        runtime,
        case,
        session,
        target_id="shen_zhaoye",
        clue_id="cut_power_trace",
    ) == ["shen_power_boundary"]


def test_mist_clock_manor_npc_skill_projection_does_not_leak_story_body() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    _inspect_all(runtime, session, ["study_lock", "medicine_box"])

    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=_ask_about("jiang_yanhui", "empty_capsules"),
    )
    serialized = json.dumps(
        [skill.model_dump(mode="json") for skill in context.npc_skill_projections],
        ensure_ascii=False,
    )

    assert "jiang_capsule_boundary" in serialized
    assert "heart_medicine_replaced.safe_fragment:capsules_are_empty" in serialized
    assert "timed_lock_modified.safe_fragment:lock_has_delay_marks" not in serialized
    for body_text in _story_body_values(case):
        assert body_text not in serialized


def _selected_skill_ids(
    runtime: object,
    case: CasePackage,
    session: object,
    *,
    target_id: str,
    clue_id: str,
) -> list[str]:
    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=_ask_about(target_id, clue_id),
    )
    return [skill.skill_id for skill in context.npc_skill_projections]


def _inspect_all(runtime: object, session: object, target_ids: list[str]) -> None:
    for target_id in target_ids:
        runtime.action_service.handle(
            session=session,
            action=PlayerAction(type=ActionType.INSPECT, target_id=target_id),
        )


def _ask_about(target_id: str, clue_id: str) -> PlayerAction:
    return PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id=target_id,
        subject_type=SubjectType.CLUE,
        subject_id=clue_id,
        text=f"What can you say about {clue_id}?",
    )


def _assert_safe_fragment_refs_are_bound_to_world_info(case: CasePackage) -> None:
    safe_refs = {
        f"{world_info.id}.safe_fragment:{fragment.id}"
        for world_info in case.world_info
        for fragment in world_info.claim_graph.safe_fragments
    }
    for skill in case.npc_skills:
        assert set(skill.disclosure.safe_fragment_refs) <= safe_refs
        assert {
            ref.split(".safe_fragment:", 1)[0]
            for ref in skill.disclosure.safe_fragment_refs
        } <= set(skill.disclosure.world_info_ids)


def _story_body_values(case: CasePackage) -> list[str]:
    values: list[str] = []
    for world_info in case.world_info:
        values.extend([world_info.title, world_info.description])
        for fragment in world_info.claim_graph.safe_fragments:
            values.append(fragment.summary)
    for clue in case.clues:
        values.extend([clue.title, clue.description])
    for character in case.characters:
        for goal in character.private.goals:
            values.append(goal.summary)
        for secret in character.private.secrets:
            values.append(secret.summary)
        for knowledge in character.private.knowledge:
            values.append(knowledge.summary)
    return [value for value in values if value]
