from __future__ import annotations

from app.agents.context import build_agent_context
from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.domain.models import (
    ActionType,
    CaseMeta,
    CasePackage,
    CharacterConfig,
    EventType,
    NarrativeState,
    PlayerAction,
    SessionState,
    WorldEvent,
)


def test_recent_events_default_deny_unlisted_runtime_events() -> None:
    session = SessionState(
        id="session.recent_events.default_deny",
        case_id="case.recent_events.default_deny",
        narrative=NarrativeState(phase="opening"),
        relationships={},
        events=[
            WorldEvent(
                id="event.rule_rejected.internal",
                case_id="case.recent_events.default_deny",
                session_id="session.recent_events.default_deny",
                actor_id="rule_engine",
                type=EventType.RULE_REJECTED,
                payload={"reason": "PRIVATE_RULE_DETAIL_SHOULD_NOT_SURFACE"},
                created_at="2026-06-27T00:00:00Z",
            ),
            WorldEvent(
                id="event.player_talked.target",
                case_id="case.recent_events.default_deny",
                session_id="session.recent_events.default_deny",
                actor_id="player",
                type=EventType.PLAYER_TALKED,
                payload={"target_id": "npc", "text": "visible only to target"},
                created_at="2026-06-27T00:00:01Z",
            ),
        ],
    )

    context = build_agent_context(
        _case(),
        session,
        PlayerAction(
            type=ActionType.TALK,
            target_id="npc",
            text="continue",
        ),
        retrieval_plan=_plan(allow_recent_events=True),
        memory_snapshots=[],
    )

    assert [event.id for event in context.recent_events] == [
        "event.player_talked.target"
    ]
    assert "PRIVATE_RULE_DETAIL_SHOULD_NOT_SURFACE" not in " ".join(
        event.model_dump_json() for event in context.recent_events
    )


def _case() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id="case.recent_events.default_deny",
            title="Recent Events Default Deny",
            initial_phase="opening",
        ),
        characters=[
            CharacterConfig(id="npc", display_name="NPC", public_role="Witness"),
            CharacterConfig(id="other_npc", display_name="Other", public_role="Witness"),
        ],
        scenes=[],
        clues=[],
    )


def _plan(*, allow_recent_events: bool) -> MemoryRetrievalPlan:
    return MemoryRetrievalPlan(
        skill_id="test.recent_events.default_deny",
        included_memory_types=("episodic", "belief", "relationship", "strategy"),
        included_scopes=("case", "session", "npc_private", "scene_shared"),
        included_layers=("core", "working"),
        forbidden_scopes=("director_audit",),
        forbidden_layers=("archival",),
        max_memory_items=8,
        inject_portrait_summary=False,
        allow_recent_events=allow_recent_events,
    )
