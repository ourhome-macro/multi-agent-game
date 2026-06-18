from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.gateway import AgentGateway
from app.agents.llm_contract import build_llm_agent_input
from app.cases.errors import CaseLoadError
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    CasePackage,
    DisclosureMode,
    PlayerAction,
    SubjectType,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
SKILL_ID = "butler_drawer_pressure_deflection"
SAFE_FRAGMENT_REF = "desk_forced_open.safe_fragment:drawer_was_forced"


class RecordingSkillAgent:
    backend_name = "recording"
    model_name = "recording-skill-agent"

    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    def generate(self, context: AgentContext) -> AgentIntent:
        self.contexts.append(context)
        return AgentIntent(
            speech="I will keep the answer within the selected limits.",
            intent=AgentIntentType.CONCEAL,
            proposed_actions=[],
            memory_refs=[],
            disclosure_claims=[],
        )


def test_case_loader_loads_npc_skill_config() -> None:
    case = CaseLoader().load(CASE_DIR)

    skill = next(item for item in case.npc_skills if item.id == SKILL_ID)

    assert skill.owner_character_ids == ["butler"]
    assert skill.disclosure.max_mode == DisclosureMode.PARTIAL
    assert skill.disclosure.safe_fragment_refs == [SAFE_FRAGMENT_REF]


def test_case_loader_rejects_unbound_skill_safe_fragment() -> None:
    case_dir = PROJECT_ROOT / "pytest_tmp_npc_skill_cases" / uuid4().hex
    case_dir.parent.mkdir(exist_ok=True)
    shutil.copytree(CASE_DIR, case_dir)
    skill_yaml = (case_dir / "npc_skills.yaml").read_text(encoding="utf-8")
    (case_dir / "npc_skills.yaml").write_text(
        skill_yaml.replace(
            "  disclosure:\n    world_info_ids:\n      - desk_forced_open",
            "  disclosure:\n    world_info_ids:\n      - will_swapped",
        ),
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="safe_fragment_refs are not bound"):
        CaseLoader().load(case_dir)


def test_npc_skill_is_locked_until_player_has_required_knowledge() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    action = _ask_about_drawer()

    locked_context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=action,
    )

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    unlocked_context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=action,
    )

    assert locked_context.npc_skill_projections == []
    assert [skill.skill_id for skill in unlocked_context.npc_skill_projections] == [
        SKILL_ID
    ]
    assert "player_knowledge.desk_forced_open" in {
        item.knowledge_id for item in unlocked_context.player_knowledge
    }


def test_npc_skill_projection_does_not_include_private_or_story_body() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=_ask_about_drawer(),
    )
    serialized = json.dumps(
        [skill.model_dump(mode="json") for skill in context.npc_skill_projections],
        ensure_ascii=False,
    )

    assert SKILL_ID in serialized
    assert SAFE_FRAGMENT_REF in serialized
    assert "书桌抽屉存在新鲜撬动痕迹" not in serialized
    for private_value in _private_character_values(case):
        assert private_value not in serialized


def test_npc_skill_limits_director_safe_fragments() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=_ask_about_drawer(),
    )

    assert [fragment.ref for fragment in context.director_safe_fragments] == [
        SAFE_FRAGMENT_REF
    ]
    assert context.director_safe_fragments[0].summary.startswith("书桌抽屉存在")


def test_npc_skill_caps_director_safe_fragment_modes() -> None:
    case = CaseLoader().load(CASE_DIR)
    skill_index = next(
        index for index, skill in enumerate(case.npc_skills) if skill.id == SKILL_ID
    )
    case.npc_skills[skill_index] = case.npc_skills[skill_index].model_copy(
        update={
            "disclosure": case.npc_skills[skill_index].disclosure.model_copy(
                update={"max_mode": DisclosureMode.HINT}
            )
        }
    )
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=_ask_about_drawer(),
    )
    contract_input = build_llm_agent_input(context)
    constraint = next(
        item
        for item in contract_input.disclosure_constraints
        if item.item_kind == "world_info" and item.item_id == "desk_forced_open"
    )

    assert context.director_safe_fragments[0].allowed_modes == [DisclosureMode.HINT]
    assert constraint.safe_fragments[0].allowed_modes == [DisclosureMode.HINT]
    assert DisclosureMode.PARTIAL not in constraint.safe_fragments[0].allowed_modes


def test_npc_skill_safe_fragment_survives_stricter_fact_strategy() -> None:
    case = CaseLoader().load(CASE_DIR)
    character_index = next(
        index for index, character in enumerate(case.characters) if character.id == "butler"
    )
    butler = case.characters[character_index]
    case.characters[character_index] = butler.model_copy(
        update={
            "private": butler.private.model_copy(
                update={
                    "disclosure_style": butler.private.disclosure_style.model_copy(
                        update={
                            "max_mode_by_world_info": {
                                **butler.private.disclosure_style.max_mode_by_world_info,
                                "desk_forced_open": DisclosureMode.DEFLECT,
                            }
                        }
                    )
                }
            )
        }
    )
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=_ask_about_drawer(),
    )
    contract_input = build_llm_agent_input(context)
    constraint = next(
        item
        for item in contract_input.disclosure_constraints
        if item.item_kind == "world_info" and item.item_id == "desk_forced_open"
    )

    assert [fragment.ref for fragment in context.director_safe_fragments] == [
        SAFE_FRAGMENT_REF
    ]
    assert constraint.safe_fragments[0].ref == SAFE_FRAGMENT_REF
    assert DisclosureMode.PARTIAL in constraint.allowed_modes
    assert DisclosureMode.PARTIAL not in constraint.forbidden_modes


def test_llm_contract_includes_skill_projection_without_unlocking_more_facts() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=_ask_about_drawer(),
    )

    contract_input = build_llm_agent_input(context)
    serialized = contract_input.model_dump_json()

    assert contract_input.agent_context.npc_skill_projections[0].skill_id == SKILL_ID
    assert SAFE_FRAGMENT_REF in serialized
    assert "killer_is_niece" not in serialized
    assert "will_swapped" not in {
        fragment.world_info_id
        for fragment in contract_input.agent_context.director_safe_fragments
    }


def test_runtime_trace_records_npc_skill_projection_without_sensitive_content() -> None:
    case = CaseLoader().load(CASE_DIR)
    agent = RecordingSkillAgent()
    trace_dir = PROJECT_ROOT / "pytest_tmp_npc_skill_trace"
    trace_dir.mkdir(exist_ok=True)
    trace_id = uuid4().hex
    trace_jsonl = trace_dir / f"trace-{trace_id}.jsonl"
    trace_log = trace_dir / f"trace-{trace_id}.log"
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer(
            jsonl_path=trace_jsonl,
            log_path=trace_log,
        ),
    )
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    runtime.action_service.handle(session=session, action=_ask_about_drawer())

    record = json.loads(trace_jsonl.read_text(encoding="utf-8"))
    projection = record["npc_skill_projection"]
    serialized_projection = json.dumps(projection, ensure_ascii=False)

    assert record["schema_version"] == 8
    assert projection["selected_skill_ids"] == [SKILL_ID]
    assert projection["skill_safe_fragment_refs"] == [SAFE_FRAGMENT_REF]
    assert projection["items"][0]["safe_fragment_refs"] == [SAFE_FRAGMENT_REF]
    assert "书桌抽屉存在新鲜撬动痕迹" not in serialized_projection
    assert "content" not in serialized_projection
    assert "content" not in json.dumps(
        record["context_layer_budget"],
        ensure_ascii=False,
    )
    for private_value in _private_character_values(case):
        assert private_value not in serialized_projection


def _ask_about_drawer() -> PlayerAction:
    return PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id="butler",
        subject_type=SubjectType.CLUE,
        subject_id="scratched_drawer",
        text="What about the drawer scratches?",
    )


def _private_character_values(case: CasePackage) -> list[str]:
    values: list[str] = []
    for character in case.characters:
        for goal in character.private.goals:
            values.append(goal.summary)
        for secret in character.private.secrets:
            values.append(secret.summary)
        for knowledge in character.private.knowledge:
            values.append(knowledge.summary)
    return [value for value in values if value]
