from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ActionType, CasePackage, PlayerAction, SessionState


@dataclass(frozen=True)
class MeetingSpeaker:
    speaker_id: str
    reason: str


class MeetingSpeakerSelector:
    def __init__(self, *, max_speakers: int = 2) -> None:
        if max_speakers < 1:
            raise ValueError("max_speakers must be positive")
        self._max_speakers = max_speakers

    def select(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[MeetingSpeaker]:
        if action.type != ActionType.MEETING_ASK:
            return []
        if not session.meeting.active:
            return []

        target_id = action.target_id
        if target_id not in {character.id for character in case.characters}:
            return []
        if session.meeting.participant_ids and target_id not in set(
            session.meeting.participant_ids
        ):
            return []

        return [
            MeetingSpeaker(
                speaker_id=target_id,
                reason="directly_asked",
            )
        ][: self._max_speakers]
