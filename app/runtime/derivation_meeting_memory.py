from __future__ import annotations

from app.domain.models import CasePackage, SessionState, WorldEvent
from app.runtime.derivation_memory_constants import (
    MEETING_NARRATION_MEMORY_RULE_ID,
    MEETING_NPC_MESSAGE_MEMORY_RULE_ID,
    MEETING_SHARED_MESSAGE_MEMORY_RULE_ID,
    MEETING_VOTE_BELIEF_MEMORY_RULE_ID,
)
from app.runtime.derivation_utils import (
    AUTHORITY_SOURCE_NPC_HEARSAY as _AUTHORITY_SOURCE_NPC_HEARSAY,
)
from app.runtime.derivation_utils import (
    AUTHORITY_SOURCE_PLAYER_ACTION as _AUTHORITY_SOURCE_PLAYER_ACTION,
)
from app.runtime.derivation_utils import (
    AUTHORITY_SOURCE_PLAYER_EVIDENCE as _AUTHORITY_SOURCE_PLAYER_EVIDENCE,
)
from app.runtime.derivation_utils import (
    AUTHORITY_SOURCE_SYSTEM_RULE as _AUTHORITY_SOURCE_SYSTEM_RULE,
)
from app.runtime.derivation_utils import (
    AUTHORITY_SOURCE_WORLD_EVENT as _AUTHORITY_SOURCE_WORLD_EVENT,
)
from app.runtime.derivation_utils import (
    PRIVACY_REASON_MEETING_NPC_PRIVATE as _PRIVACY_REASON_MEETING_NPC_PRIVATE,
)
from app.runtime.derivation_utils import (
    PRIVACY_REASON_MEETING_SHARED as _PRIVACY_REASON_MEETING_SHARED,
)
from app.runtime.derivation_utils import (
    PRIVACY_REASON_MEETING_VOTE as _PRIVACY_REASON_MEETING_VOTE,
)
from app.runtime.derivation_utils import (
    meeting_npc_message_memory_id as _meeting_npc_message_memory_id,
)
from app.runtime.derivation_utils import (
    meeting_shared_message_memory_id as _meeting_shared_message_memory_id,
)
from app.runtime.derivation_utils import (
    meeting_vote_belief_memory_id as _meeting_vote_belief_memory_id,
)
from app.runtime.derivation_utils import (
    ordered_unique as _ordered_unique,
)

MEETING_MESSAGE_POSTED_EVENT_TYPE = "meeting.message.posted"
MEETING_VOTE_CAST_EVENT_TYPE = "meeting.vote.cast"
MAX_MEETING_VOTE_CONFIDENCE = 0.5
MEETING_VOTE_CONFIDENCE = 0.45


class MeetingMemoryDerivationMixin:
    def _derive_meeting_message_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        speaker_id = _optional_str(source_event.payload.get("speaker_id"))
        if speaker_id is None:
            speaker_id = _optional_str(source_event.actor_id)
        meeting_id = _meeting_id(session, source_event)
        if speaker_id is None or meeting_id is None:
            return None

        if _is_shared_meeting_message(source_event, speaker_id):
            participants = _meeting_participant_ids(case, session, source_event)
            if not participants:
                return None
            return self._derive_meeting_shared_message_memory_candidate(
                case=case,
                session=session,
                source_event=source_event,
                meeting_id=meeting_id,
                speaker_id=speaker_id,
                visible_to_character_ids=participants,
            )

        if speaker_id in _character_ids(case):
            return self._derive_meeting_npc_message_memory_candidate(
                case=case,
                session=session,
                source_event=source_event,
                meeting_id=meeting_id,
                speaker_id=speaker_id,
            )
        return None

    def _derive_meeting_shared_message_memory_candidate(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
        meeting_id: str,
        speaker_id: str,
        visible_to_character_ids: list[str],
    ) -> WorldEvent | None:
        message_kind = _message_kind(source_event)
        clue_id = _optional_str(source_event.payload.get("clue_id"))
        is_evidence = message_kind == "evidence"
        is_narration = message_kind == "narration"
        if is_evidence:
            if clue_id is None:
                return None
            if not _player_knows_clue(session, clue_id):
                return None

        topic_tags = _meeting_topic_tags(
            meeting_id,
            "message",
            message_kind,
            speaker_id,
            clue_id,
        )
        metadata: dict[str, object] = {
            "topic_tags": topic_tags,
            "privacy_reason": _PRIVACY_REASON_MEETING_SHARED,
            "authority_source": _shared_message_authority_source(
                is_evidence=is_evidence,
                is_narration=is_narration,
            ),
            "authority": _shared_message_authority(
                is_evidence=is_evidence,
                is_narration=is_narration,
            ),
        }
        phase_id = _optional_str(source_event.payload.get("phase"))
        if is_narration and phase_id is not None:
            metadata["phase_id"] = phase_id
        if is_evidence:
            clue_metadata = self._clue_memory_metadata(case, clue_id)
            metadata = {
                **clue_metadata,
                **metadata,
                "topic_tags": _ordered_unique(
                    [
                        *[str(item) for item in clue_metadata.get("topic_tags", [])],
                        *topic_tags,
                    ]
                ),
            }

        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=_meeting_shared_message_memory_id(meeting_id, source_event.id),
            rule_id=(
                MEETING_NARRATION_MEMORY_RULE_ID
                if is_narration
                else MEETING_SHARED_MESSAGE_MEMORY_RULE_ID
            ),
            memory_type="episodic",
            memory_scope="scene_shared",
            memory_layer="working",
            content=_shared_message_content(case, source_event, message_kind, clue_id),
            salience=_shared_message_salience(
                is_evidence=is_evidence,
                is_narration=is_narration,
            ),
            owner_character_id=None,
            visible_to_character_ids=visible_to_character_ids,
            metadata=metadata,
        )

    def _derive_meeting_npc_message_memory_candidate(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
        meeting_id: str,
        speaker_id: str,
    ) -> WorldEvent | None:
        speaker_name = _character_name(case, speaker_id)
        text = _compact_text(source_event.payload.get("text"))
        if text is None:
            return None
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=_meeting_npc_message_memory_id(speaker_id, source_event.id),
            rule_id=MEETING_NPC_MESSAGE_MEMORY_RULE_ID,
            memory_type="episodic",
            memory_scope="npc_private",
            memory_layer="working",
            content=f"{speaker_name} spoke in the meeting: {text}",
            salience=0.58,
            owner_character_id=speaker_id,
            visible_to_character_ids=[speaker_id],
            metadata={
                "topic_tags": _meeting_topic_tags(
                    meeting_id,
                    "message",
                    _message_kind(source_event),
                    speaker_id,
                ),
                "privacy_reason": _PRIVACY_REASON_MEETING_NPC_PRIVATE,
                "authority_source": _AUTHORITY_SOURCE_WORLD_EVENT,
                "authority": "event_observed",
            },
        )

    def _derive_meeting_vote_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        meeting_id = _meeting_id(session, source_event)
        voter_id = _optional_str(source_event.payload.get("voter_id"))
        target_id = _optional_str(source_event.payload.get("target_id"))
        choice = _optional_str(source_event.payload.get("choice"))
        participants = _meeting_participant_ids(case, session, source_event)
        if meeting_id is None or voter_id is None or target_id is None or choice is None:
            return None
        if not participants:
            return None

        confidence = min(MEETING_VOTE_CONFIDENCE, MAX_MEETING_VOTE_CONFIDENCE)
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=_meeting_vote_belief_memory_id(meeting_id, source_event.id),
            rule_id=MEETING_VOTE_BELIEF_MEMORY_RULE_ID,
            memory_type="belief",
            memory_scope="scene_shared",
            memory_layer="working",
            content=_vote_content(case, source_event, voter_id, target_id, choice),
            salience=0.45,
            owner_character_id=None,
            visible_to_character_ids=participants,
            confidence=confidence,
            metadata={
                "topic_tags": _meeting_topic_tags(
                    meeting_id,
                    "vote",
                    voter_id,
                    target_id,
                    choice,
                ),
                "privacy_reason": _PRIVACY_REASON_MEETING_VOTE,
                "authority_source": _AUTHORITY_SOURCE_NPC_HEARSAY,
                "authority": "non_authoritative",
                "non_authoritative": True,
                "belief_subject": f"meeting_vote_{meeting_id}_{target_id}_{choice}",
                "belief_polarity": _vote_belief_polarity(choice),
            },
        )


def _is_shared_meeting_message(
    source_event: WorldEvent,
    speaker_id: str,
) -> bool:
    message_kind = _message_kind(source_event)
    return speaker_id == "player" or message_kind in {"evidence", "narration"}


def _shared_message_content(
    case: CasePackage,
    source_event: WorldEvent,
    message_kind: str,
    clue_id: str | None,
) -> str:
    text = _compact_text(source_event.payload.get("text")) or "no text"
    if message_kind == "evidence" and clue_id is not None:
        clue = next((item for item in case.clues if item.id == clue_id), None)
        clue_label = clue.title if clue is not None else clue_id
        return f"Player presented evidence '{clue_label}' in the meeting: {text}"
    if message_kind == "narration":
        return f"Director narrated in the meeting: {text}"
    return f"Player said in the meeting: {text}"


def _shared_message_authority_source(
    *,
    is_evidence: bool,
    is_narration: bool,
) -> str:
    if is_narration:
        return _AUTHORITY_SOURCE_SYSTEM_RULE
    if is_evidence:
        return _AUTHORITY_SOURCE_PLAYER_EVIDENCE
    return _AUTHORITY_SOURCE_PLAYER_ACTION


def _shared_message_authority(
    *,
    is_evidence: bool,
    is_narration: bool,
) -> str:
    if is_narration:
        return "rule_verified"
    if is_evidence:
        return "event_observed"
    return "player_claim"


def _shared_message_salience(
    *,
    is_evidence: bool,
    is_narration: bool,
) -> float:
    if is_narration:
        return 0.66
    if is_evidence:
        return 0.62
    return 0.5


def _vote_content(
    case: CasePackage,
    source_event: WorldEvent,
    voter_id: str,
    target_id: str,
    choice: str,
) -> str:
    voter_name = _character_name(case, voter_id) if voter_id != "player" else "Player"
    target_name = _character_name(case, target_id)
    reason = _compact_text(source_event.payload.get("reason"))
    suffix = f" Reason: {reason}" if reason is not None else ""
    return (
        f"{voter_name} cast a non-authoritative meeting vote "
        f"'{choice}' about {target_name}.{suffix}"
    )


def _meeting_id(session: SessionState, source_event: WorldEvent) -> str | None:
    return _optional_str(source_event.payload.get("meeting_id")) or _optional_str(
        session.meeting.meeting_id
    )


def _meeting_participant_ids(
    case: CasePackage,
    session: SessionState,
    source_event: WorldEvent,
) -> list[str]:
    character_ids = _character_ids(case)
    raw_participants = source_event.payload.get("participant_ids")
    if isinstance(raw_participants, list):
        participants = [str(item) for item in raw_participants if str(item) in character_ids]
    else:
        participants = [
            str(item)
            for item in session.meeting.participant_ids
            if str(item) in character_ids
        ]
    return _ordered_unique(participants)


def _player_knows_clue(session: SessionState, clue_id: str) -> bool:
    return clue_id in session.discovered_clues or any(
        knowledge.clue_id == clue_id for knowledge in session.player_knowledge.values()
    )


def _message_kind(source_event: WorldEvent) -> str:
    return (_optional_str(source_event.payload.get("message_kind")) or "speech").lower()


def _meeting_topic_tags(meeting_id: str, *parts: object | None) -> list[str]:
    return _ordered_unique(
        [
            "meeting",
            meeting_id,
            *[str(part) for part in parts if part is not None and str(part)],
        ]
    )


def _vote_belief_polarity(choice: str) -> str:
    normalized = choice.lower()
    if normalized == "defend":
        return "doubts"
    if normalized == "accuse":
        return "suspects"
    return "believes"


def _character_ids(case: CasePackage) -> set[str]:
    return {character.id for character in case.characters}


def _character_name(case: CasePackage, character_id: str) -> str:
    return next(
        (character.display_name for character in case.characters if character.id == character_id),
        character_id,
    )


def _compact_text(value: object, *, limit: int = 180) -> str | None:
    text = _optional_str(value)
    if text is None:
        return None
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return f"{compacted[: limit - 3]}..."


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
