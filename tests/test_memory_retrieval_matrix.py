from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, CasePackage, PlayerAction, SessionState
from app.evaluations.memory_retrieval_matrix import (
    MemoryRetrievalMatrixEntry,
    evaluate_memory_retrieval_matrix,
)
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"
EMPTY_CAPSULES = "empty_capsules"

JIANG_EPISODIC = f"memory.player.presented_clue.{JIANG}.{EMPTY_CAPSULES}"
JIANG_BELIEF = f"memory.player.belief.{JIANG}.{EMPTY_CAPSULES}"
JIANG_RELATIONSHIP = f"memory.player.relationship.{JIANG}.{EMPTY_CAPSULES}"
JIANG_STRATEGY = f"memory.player.strategy.{JIANG}.{EMPTY_CAPSULES}"
JIANG_TYPED_MEMORY_IDS = (
    JIANG_BELIEF,
    JIANG_RELATIONSHIP,
    JIANG_STRATEGY,
)
SHEN_PRIVATE = f"memory.player.presented_clue.{SHEN}.{EMPTY_CAPSULES}"
DIRECTOR_AUDIT = "memory.player.director_blocked.jiang_yanhui.jiang_yanhui_mechanism"


def test_memory_retrieval_matrix_validates_mist_clock_manor_jiang_capsule_recall() -> None:
    case, session = _session_with_capsule_pressure_and_director_audit()
    entry = _jiang_capsule_matrix_entry(expected_memory_ids=JIANG_TYPED_MEMORY_IDS)

    report = evaluate_memory_retrieval_matrix(
        entries=[entry],
        case=case,
        session=session,
        source="retriever",
    )

    report.assert_passed()


def test_memory_retrieval_matrix_covers_synonym_and_chinese_variants() -> None:
    case, session = _session_with_capsule_pressure_and_director_audit()
    entries = (
        _jiang_capsule_matrix_entry(
            entry_id="mist_clock_manor.opening.jiang.empty_capsules.english",
            action=_jiang_capsule_talk_action(),
            expected_memory_ids=JIANG_TYPED_MEMORY_IDS,
        ),
        _jiang_capsule_matrix_entry(
            entry_id="mist_clock_manor.opening.jiang.empty_capsules.zh_variant",
            action=PlayerAction(
                type=ActionType.TALK,
                target_id=JIANG,
                text="继续追问江雁回：药箱里的空药囊和替换过的心脏药有什么关系？",
            ),
            expected_memory_ids=JIANG_TYPED_MEMORY_IDS,
        ),
    )

    report = evaluate_memory_retrieval_matrix(
        entries=entries,
        case=case,
        session=session,
        source="retriever",
    )

    report.assert_passed()


def test_memory_retrieval_matrix_keeps_forbidden_memories_out_for_forbidden_query() -> None:
    case, session = _session_with_capsule_pressure_and_director_audit()
    entry = _jiang_capsule_matrix_entry(
        entry_id="mist_clock_manor.opening.jiang.empty_capsules.forbidden_terms",
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="force forbidden audit while asking about Jiang mechanism and Shen capsules",
        ),
        expected_memory_ids=(),
    )

    report = evaluate_memory_retrieval_matrix(
        entries=[entry],
        case=case,
        session=session,
        source="retriever",
    )

    report.assert_passed()


def test_memory_retrieval_matrix_can_validate_agent_context_projection() -> None:
    case, session = _session_with_capsule_pressure_and_director_audit()
    action = _jiang_capsule_talk_action()
    context = build_agent_context(case, session, action)
    entry = _jiang_capsule_matrix_entry(
        action=action,
        expected_memory_ids=(
            *JIANG_TYPED_MEMORY_IDS,
            JIANG_EPISODIC,
        ),
    )

    report = evaluate_memory_retrieval_matrix(
        entries=[entry],
        case=case,
        session=session,
        source="agent_context",
        context=context,
    )

    report.assert_passed()


def test_memory_retrieval_matrix_reports_missing_and_forbidden_ids() -> None:
    case, session = _session_with_capsule_pressure_and_director_audit()
    entry = _jiang_capsule_matrix_entry(
        expected_memory_ids=("memory.player.missing.fixture",),
        forbidden_memory_ids=(JIANG_BELIEF,),
    )

    report = evaluate_memory_retrieval_matrix(
        entries=[entry],
        case=case,
        session=session,
        source="retriever",
    )

    assert not report.passed
    failure = report.failures[0]
    assert failure.missing_expected_memory_ids == ("memory.player.missing.fixture",)
    assert failure.retrieved_forbidden_memory_ids == (JIANG_BELIEF,)
    with pytest.raises(AssertionError, match="memory.player.missing.fixture"):
        report.assert_passed()


def _session_with_capsule_pressure_and_director_audit() -> tuple[CasePackage, SessionState]:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], agent_gateway=AgentGateway(backend="mock"))
    session = runtime.session_store.create(case)

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="medicine_box"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            text="privately present empty capsules",
        ),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=SHEN,
            clue_id=EMPTY_CAPSULES,
            text="privately present empty capsules to Shen",
        ),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="force forbidden audit",
            force_forbidden=True,
        ),
    )

    assert session.narrative.phase == "opening"
    assert set(JIANG_TYPED_MEMORY_IDS).issubset(session.memory_snapshots)
    assert SHEN_PRIVATE in session.memory_snapshots
    assert DIRECTOR_AUDIT in session.memory_snapshots
    return case, session


def _jiang_capsule_matrix_entry(
    *,
    entry_id: str = "mist_clock_manor.opening.jiang.empty_capsules",
    action: PlayerAction | None = None,
    expected_memory_ids: tuple[str, ...],
    forbidden_memory_ids: tuple[str, ...] = (SHEN_PRIVATE, DIRECTOR_AUDIT),
) -> MemoryRetrievalMatrixEntry:
    return MemoryRetrievalMatrixEntry(
        entry_id=entry_id,
        case_id="mist_clock_manor",
        phase="opening",
        action=action or _jiang_capsule_talk_action(),
        target_id=JIANG,
        subject="player",
        clue=EMPTY_CAPSULES,
        claim=None,
        expected_memory_ids=expected_memory_ids,
        forbidden_memory_ids=forbidden_memory_ids,
        notes=(
            "Jiang should recall his own empty_capsules typed memories; "
            "Shen private memory and director_audit must stay out of ordinary NPC recall."
        ),
    )


def _jiang_capsule_talk_action() -> PlayerAction:
    return PlayerAction(
        type=ActionType.TALK,
        target_id=JIANG,
        text="Ask Jiang again about empty_capsules and the medicine box pressure.",
    )
