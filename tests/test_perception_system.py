from __future__ import annotations

from types import SimpleNamespace

from app.domain.models import EventType, WorldEvent
from app.runtime.perception import observe_recent, visible_events_for

EXPECTED_OBSERVED_KEYS = {
    "observer_id",
    "observed_event_id",
    "scene_id",
    "visibility",
    "perception_quality",
    "redacted_payload_ref",
}


def test_same_scene_public_events_are_observed_with_redacted_payload_ref() -> None:
    event = _event(
        event_id="evt-public",
        event_type=EventType.PLAYER_INSPECTED,
        payload={
            "scene_id": "library",
            "target_id": "desk",
            "text": "body text must not be copied",
        },
    )

    observed = visible_events_for(
        case=_case(),
        session=_session(ada="library", beth="hall"),
        observer_id="ada",
        events=[event],
    )
    absent = visible_events_for(
        case=_case(),
        session=_session(ada="library", beth="hall"),
        observer_id="beth",
        events=[event],
    )

    assert absent == []
    assert len(observed) == 1
    assert set(observed[0]) == EXPECTED_OBSERVED_KEYS
    assert observed[0] == {
        "observer_id": "ada",
        "observed_event_id": "evt-public",
        "scene_id": "library",
        "visibility": "public",
        "perception_quality": "direct",
        "redacted_payload_ref": "world_event:evt-public:payload",
    }
    assert "text" not in observed[0]


def test_absent_npc_does_not_observe_scene_shared_presented_clue() -> None:
    event = _event(
        event_id="evt-shared-clue",
        event_type=EventType.PLAYER_PRESENTED_CLUE,
        payload={
            "target_id": "ada",
            "clue_id": "clue-knife",
            "presentation_mode": "scene_shared",
            "scene_id": "library",
            "present_character_ids": ["ada", "beth"],
            "text": "the private clue body must stay out of npc.observed",
        },
    )

    observed = visible_events_for(
        case=_case(),
        session=_session(ada="library", beth="hall"),
        observer_id="beth",
        events=[event],
    )

    assert observed == []


def test_private_presented_clue_is_not_observed_by_third_party() -> None:
    event = _event(
        event_id="evt-private-clue",
        event_type=EventType.PLAYER_PRESENTED_CLUE,
        payload={
            "target_id": "ada",
            "clue_id": "clue-letter",
            "presentation_mode": "private",
            "text": "only Ada should know this was presented",
        },
    )

    third_party = visible_events_for(
        case=_case(),
        session=_session(ada="library", beth="library"),
        observer_id="beth",
        events=[event],
    )
    target = visible_events_for(
        case=_case(),
        session=_session(ada="library", beth="library"),
        observer_id="ada",
        events=[event],
    )

    assert third_party == []
    assert target == [
        {
            "observer_id": "ada",
            "observed_event_id": "evt-private-clue",
            "scene_id": "library",
            "visibility": "private",
            "perception_quality": "direct",
            "redacted_payload_ref": "world_event:evt-private-clue:payload",
        }
    ]


def test_director_rule_and_memory_audit_events_are_not_observable() -> None:
    events = [
        _event(
            event_id="evt-director",
            event_type=EventType.DIRECTOR_BLOCKED,
            payload={"target_id": "ada", "scene_id": "library", "reason": "spoiler"},
        ),
        _event(
            event_id="evt-rule",
            event_type=EventType.RULE_REJECTED,
            payload={"scene_id": "library", "reason": "illegal action"},
        ),
        _event(
            event_id="evt-memory",
            event_type=EventType.MEMORY_CANDIDATE_CREATED,
            payload={
                "scene_id": "library",
                "memory_scope": "npc_private",
                "owner_character_id": "beth",
                "content": "Beth's private memory",
            },
        ),
        _event(
            event_id="evt-snapshot",
            event_type=EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
            payload={"scene_id": "library", "content": "snapshot body"},
        ),
        _event(
            event_id="evt-impression",
            event_type=EventType.CHARACTER_IMPRESSION_UPDATED,
            payload={"scene_id": "library", "content": "impression body"},
        ),
    ]

    observed = visible_events_for(
        case=_case(),
        session=_session(ada="library"),
        observer_id="ada",
        events=events,
    )

    assert observed == []


def test_observe_recent_applies_limit_before_visibility_filtering() -> None:
    old_event = _event(
        event_id="evt-old",
        event_type=EventType.PLAYER_INSPECTED,
        payload={"scene_id": "library", "visibility": "public"},
    )
    recent_event = _event(
        event_id="evt-recent",
        event_type=EventType.PLAYER_INSPECTED,
        payload={"scene_id": "library", "visibility": "public"},
    )

    observed = observe_recent(
        case=_case(),
        session=_session(ada="library"),
        observer_id="ada",
        events=[old_event, recent_event],
        limit=1,
    )

    assert [item["observed_event_id"] for item in observed] == ["evt-recent"]


def _case() -> SimpleNamespace:
    return SimpleNamespace(id="case-1")


def _session(**npc_locations: str) -> SimpleNamespace:
    return SimpleNamespace(id="session-1", case_id="case-1", npc_locations=npc_locations)


def _event(
    *,
    event_id: str,
    event_type: EventType,
    payload: dict[str, object],
    actor_id: str = "player",
) -> WorldEvent:
    return WorldEvent(
        id=event_id,
        case_id="case-1",
        session_id="session-1",
        actor_id=actor_id,
        type=event_type,
        payload=payload,
        created_at="2026-06-27T00:00:00+00:00",
    )
