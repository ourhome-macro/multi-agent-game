from __future__ import annotations

from app.domain.models import CasePackage, EventType, NarrativeBeatConfig, SessionState, WorldEvent
from app.runtime.events import EventRecorder


class RuleTriggerSystem:
    def __init__(self, recorder: EventRecorder) -> None:
        self._recorder = recorder

    def evaluate(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        trigger_event = self._find_event(session, caused_by_event_id)
        changed = True
        while changed:
            changed = False
            for beat in case.narrative_rules.beats:
                if beat.id in session.narrative.completed_beats:
                    continue
                if not self._is_beat_ready(beat, session, trigger_event):
                    continue
                events.append(
                    self._complete_beat(
                        session=session,
                        beat=beat,
                        caused_by_event_id=caused_by_event_id,
                    )
                )
                changed = True
                if beat.next_phase is not None and beat.next_phase != session.narrative.phase:
                    events.append(
                        self._change_phase(
                            session=session,
                            next_phase=beat.next_phase,
                            trigger_beat_id=beat.id,
                            caused_by_event_id=caused_by_event_id,
                        )
                    )
        return events

    def _is_beat_ready(
        self,
        beat: NarrativeBeatConfig,
        session: SessionState,
        trigger_event: WorldEvent | None,
    ) -> bool:
        if beat.phase is not None and beat.phase != session.narrative.phase:
            return False
        if not set(beat.all_discovered).issubset(session.discovered_clues):
            return False
        if not set(beat.all_completed).issubset(session.narrative.completed_beats):
            return False
        if beat.trigger_event_type is not None:
            if trigger_event is None or trigger_event.type != beat.trigger_event_type:
                return False
            for key, expected_value in beat.trigger_payload.items():
                if str(trigger_event.payload.get(key)) != expected_value:
                    return False
        return len(session.narrative.completed_beats) >= beat.min_completed

    def _find_event(self, session: SessionState, event_id: str) -> WorldEvent | None:
        return next((event for event in session.events if event.id == event_id), None)

    def _complete_beat(
        self,
        *,
        session: SessionState,
        beat: NarrativeBeatConfig,
        caused_by_event_id: str,
    ) -> WorldEvent:
        session.narrative.completed_beats.add(beat.id)
        return self._recorder.append(
            session,
            actor_id="rule_trigger_system",
            event_type=EventType.NARRATIVE_BEAT_COMPLETED,
            payload={"beat_id": beat.id, "phase": session.narrative.phase},
            caused_by_event_id=caused_by_event_id,
        )

    def _change_phase(
        self,
        *,
        session: SessionState,
        next_phase: str,
        trigger_beat_id: str,
        caused_by_event_id: str,
    ) -> WorldEvent:
        previous_phase = session.narrative.phase
        session.narrative.phase = next_phase
        return self._recorder.append(
            session,
            actor_id="rule_trigger_system",
            event_type=EventType.NARRATIVE_PHASE_CHANGED,
            payload={
                "from_phase": previous_phase,
                "phase": next_phase,
                "to_phase": next_phase,
                "trigger_beat_id": trigger_beat_id,
            },
            caused_by_event_id=caused_by_event_id,
        )
