from __future__ import annotations

from app.domain.models import CasePackage, EventType, SessionState, WorldEvent
from app.runtime.events import EventRecorder

NARRATION_MESSAGE_KIND = "narration"


class MeetingNarrationSystem:
    def __init__(self, recorder: EventRecorder) -> None:
        self._recorder = recorder

    def apply(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_events: list[WorldEvent],
    ) -> list[WorldEvent]:
        if not session.meeting.active or session.meeting.meeting_id is None:
            return []

        events: list[WorldEvent] = []
        for source_event in source_events:
            text = _narration_text(case=case, source_event=source_event)
            if text is None:
                continue
            events.append(
                self._recorder.append(
                    session,
                    actor_id="director",
                    event_type=EventType.MEETING_MESSAGE_POSTED,
                    payload={
                        "meeting_id": session.meeting.meeting_id,
                        "speaker_id": "director",
                        "message_kind": NARRATION_MESSAGE_KIND,
                        "text": text,
                        "narrates_event_id": source_event.id,
                        "narrates_event_type": source_event.type.value,
                        **_narration_payload_refs(source_event),
                    },
                    caused_by_event_id=source_event.id,
                )
            )
        return events


def _narration_text(case: CasePackage, source_event: WorldEvent) -> str | None:
    if source_event.type == EventType.MEETING_VERDICT_ACCEPTED:
        target_id = _optional_str(source_event.payload.get("target_id")) or "the suspect"
        result = _optional_str(source_event.payload.get("result")) or "accepted"
        return (
            f"Narrator: The meeting verdict against {target_id} is rule-checked "
            f"and recorded as {result}."
        )
    if source_event.type == EventType.NARRATIVE_BEAT_COMPLETED:
        beat_id = _optional_str(source_event.payload.get("beat_id"))
        beat = next((item for item in case.narrative_rules.beats if item.id == beat_id), None)
        description = beat.description if beat is not None else None
        if description:
            return f"Narrator: {description}"
        if beat_id is not None:
            return f"Narrator: Story beat completed: {beat_id}."
    if source_event.type == EventType.NARRATIVE_PHASE_CHANGED:
        phase = (
            _optional_str(source_event.payload.get("to_phase"))
            or _optional_str(source_event.payload.get("phase"))
            or "the next phase"
        )
        return f"Narrator: The meeting moves the case into phase '{phase}'."
    return None


def _narration_payload_refs(source_event: WorldEvent) -> dict[str, object]:
    refs: dict[str, object] = {}
    for key in (
        "target_id",
        "result",
        "beat_id",
        "phase",
        "to_phase",
        "trigger_beat_id",
    ):
        if key in source_event.payload and source_event.payload[key] is not None:
            refs[key] = source_event.payload[key]
    if "phase" not in refs and "to_phase" in refs:
        refs["phase"] = refs["to_phase"]
    return refs


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
