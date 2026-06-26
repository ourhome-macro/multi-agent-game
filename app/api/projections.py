from __future__ import annotations

from typing import Any

from app.domain.models import (
    ActionResponse,
    CasePackage,
    EventType,
    PublicActionResponse,
    PublicCaseDetail,
    PublicCharacter,
    PublicEventStreamItem,
    PublicEventStreamResponse,
    PublicEvidenceSummary,
    PublicPlayerKnowledgeSummary,
    PublicScene,
    PublicSceneHotspot,
    PublicStateSummary,
    StateSummary,
    WorldEvent,
)


def build_public_case_detail(case: CasePackage) -> PublicCaseDetail:
    initial_scene = case.scenes[0]
    return PublicCaseDetail(
        id=case.meta.id,
        title=case.meta.title,
        description=case.meta.description,
        initial_phase=case.meta.initial_phase,
        initial_scene_id=initial_scene.id,
        scenes=[
            PublicScene(
                id=scene.id,
                name=scene.name,
                description=scene.description,
                characters=list(scene.characters),
                hotspots=[
                    PublicSceneHotspot(
                        id=hotspot.id,
                        name=hotspot.name,
                        description=hotspot.description,
                    )
                    for hotspot in scene.hotspots
                ],
            )
            for scene in case.scenes
        ],
        characters=[
            PublicCharacter(
                id=character.id,
                display_name=character.display_name,
                public_role=character.public_role,
                public_description=character.public_description,
            )
            for character in case.characters
        ],
        assets=[],
    )


def build_public_event_stream(
    *,
    session_id: str,
    case_id: str,
    events: list[WorldEvent],
    after_count: int,
    limit: int,
) -> PublicEventStreamResponse:
    total_count = len(events)
    start = min(after_count, total_count)
    items: list[PublicEventStreamItem] = []
    next_after_count = start

    for index in range(start, total_count):
        next_after_count = index + 1
        event = events[index]
        payload = _public_event_payload(event)
        if payload is None:
            continue
        items.append(
            PublicEventStreamItem(
                sequence=index + 1,
                id=event.id,
                type=event.type,
                actor_id=event.actor_id,
                created_at=event.created_at,
                payload=payload,
            )
        )
        if len(items) >= limit:
            break

    return PublicEventStreamResponse(
        session_id=session_id,
        case_id=case_id,
        after_count=after_count,
        next_after_count=next_after_count,
        has_more=next_after_count < total_count,
        events=items,
    )


def build_public_action_response(response: ActionResponse) -> PublicActionResponse:
    first_event_sequence = max(
        1,
        response.state.event_count - len(response.new_events) + 1,
    )
    public_events: list[PublicEventStreamItem] = []

    for index, event in enumerate(response.new_events):
        payload = _public_event_payload(event)
        if payload is None:
            continue
        public_events.append(
            PublicEventStreamItem(
                sequence=first_event_sequence + index,
                id=event.id,
                type=event.type,
                actor_id=event.actor_id,
                created_at=event.created_at,
                payload=payload,
            )
        )

    return PublicActionResponse(
        session_id=response.session_id,
        accepted=response.accepted,
        speech=response.speech,
        director_blocked=response.director_blocked,
        director_reason=response.director_reason,
        llm_fallback_used=response.llm_fallback_used,
        llm_error=response.llm_error,
        new_events=public_events,
        state=build_public_state_summary(response.state),
    )


def build_public_state_summary(summary: StateSummary) -> PublicStateSummary:
    return PublicStateSummary(
        session_id=summary.session_id,
        case_id=summary.case_id,
        case_title=summary.case_title,
        narrative_phase=summary.narrative_phase,
        completed_beats=list(summary.completed_beats),
        characters=list(summary.characters),
        discovered_clues=list(summary.discovered_clues),
        player_knowledge=[
            PublicPlayerKnowledgeSummary(
                clue_id=item.clue_id,
                confidence=item.confidence,
                acquisition=item.acquisition,
                source_type=item.source_type,
                title=item.title,
                summary=item.summary,
            )
            for item in summary.player_knowledge
        ],
        evidence_assets=[
            PublicEvidenceSummary(
                id=item.id,
                title=item.title,
                summary=item.summary,
                source=item.source,
                clue_id=item.clue_id,
            )
            for item in summary.evidence_assets
        ],
        relationships=list(summary.relationships),
        event_count=summary.event_count,
    )


def _public_event_payload(event: WorldEvent) -> dict[str, Any] | None:
    payload = event.payload
    if event.type == EventType.SESSION_CREATED:
        return _copy_keys(payload, ["case_id", "initial_phase"])
    if event.type == EventType.PLAYER_INSPECTED:
        return _copy_keys(payload, ["target_id"])
    if event.type == EventType.CLUE_DISCOVERED:
        return _copy_keys(payload, ["clue_id", "source_hotspot_id"])
    if event.type == EventType.PLAYER_KNOWLEDGE_UPDATED:
        return _copy_keys(
            payload,
            ["clue_id", "confidence", "acquisition", "source_type", "title", "summary"],
        )
    if event.type == EventType.PLAYER_TALKED:
        return _copy_keys(payload, ["target_id", "text"])
    if event.type == EventType.PLAYER_ASKED_ABOUT:
        return _copy_keys(
            payload,
            ["target_id", "subject_type", "subject_id", "text", "interaction_pressure"],
        )
    if event.type == EventType.PLAYER_PRESENTED_CLUE:
        return _copy_keys(
            payload,
            [
                "target_id",
                "clue_id",
                "presentation_mode",
                "scene_id",
                "present_character_ids",
                "text",
                "interaction_pressure",
            ],
        )
    if event.type == EventType.PLAYER_ACCUSED:
        return _copy_keys(payload, ["target_id", "evidence_clue_ids", "text"])
    if event.type == EventType.ACCUSATION_EVALUATED:
        return _copy_keys(payload, ["target_id", "result"])
    if event.type == EventType.NPC_REPLIED:
        return _copy_keys(payload, ["speech"])
    if event.type == EventType.DIRECTOR_BLOCKED:
        return _copy_keys(payload, ["target_id", "reason", "safe_fallback_used"])
    if event.type == EventType.RULE_REJECTED:
        return _public_rule_rejection_payload(payload)
    if event.type == EventType.RELATIONSHIP_CHANGED:
        public = _copy_keys(payload, ["source_id", "target_id", "deltas"])
        current = payload.get("current")
        if isinstance(current, dict):
            public["current"] = _copy_keys(
                current,
                [
                    "source_id",
                    "target_id",
                    "trust",
                    "suspicion",
                    "fear",
                    "intimacy",
                    "hostility",
                ],
            )
        return public
    if event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
        return _copy_keys(
            payload,
            ["source_id", "target_id", "metric", "threshold", "state", "current_value"],
        )
    if event.type == EventType.NARRATIVE_BEAT_COMPLETED:
        return _copy_keys(payload, ["beat_id", "phase"])
    if event.type == EventType.NARRATIVE_PHASE_CHANGED:
        return _copy_keys(payload, ["from_phase", "phase", "to_phase", "trigger_beat_id"])
    return None


def _public_rule_rejection_payload(payload: dict[str, Any]) -> dict[str, Any]:
    public = _copy_keys(payload, ["action_type", "reason"])
    proposed_payload = payload.get("proposed_payload")
    if isinstance(proposed_payload, dict):
        public["proposed_payload"] = _copy_keys(
            proposed_payload,
            [
                "target_id",
                "clue_id",
                "subject_type",
                "subject_id",
                "presentation_mode",
                "scene_id",
                "evidence_clue_ids",
                "text",
            ],
        )
    return public


def _copy_keys(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}
