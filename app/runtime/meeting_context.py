from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import (
    AgentMemorySnapshot,
    CasePackage,
    EventType,
    PlayerAction,
    SessionState,
    SubjectType,
)


@dataclass(frozen=True)
class MeetingMessageContext:
    event_id: str
    speaker_id: str
    message_kind: str
    text: str
    target_id: str | None = None
    clue_id: str | None = None


@dataclass(frozen=True)
class MeetingEvidenceContext:
    clue_id: str
    title: str
    summary: str
    posted_event_id: str


@dataclass(frozen=True)
class MeetingMemoryContext:
    memory_id: str
    summary: str
    source_event_ids: list[str]
    source_memory_ids: list[str]
    memory_type: str
    memory_scope: str
    salience: float
    confidence: float


@dataclass(frozen=True)
class MeetingSpeakerContext:
    speaker_id: str
    meeting_id: str | None
    topic: str | None
    question_event_id: str | None
    question_text: str | None
    subject_type: SubjectType | None
    subject_id: str | None
    public_messages: list[MeetingMessageContext]
    public_evidence: list[MeetingEvidenceContext]
    visible_memories: list[MeetingMemoryContext]

    def reference_payload(self) -> dict[str, list[str]]:
        return {
            "meeting_event_ids": [item.event_id for item in self.public_messages],
            "evidence_clue_ids": [item.clue_id for item in self.public_evidence],
            "memory_ids": [item.memory_id for item in self.visible_memories],
        }


class MeetingContextBuilder:
    def __init__(
        self,
        *,
        max_messages: int = 12,
        max_evidence: int = 8,
        max_memories: int = 8,
    ) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be positive")
        if max_evidence < 0:
            raise ValueError("max_evidence must be non-negative")
        if max_memories < 0:
            raise ValueError("max_memories must be non-negative")
        self._max_messages = max_messages
        self._max_evidence = max_evidence
        self._max_memories = max_memories

    def build(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        speaker_id: str,
        action: PlayerAction,
    ) -> MeetingSpeakerContext:
        messages = _public_meeting_messages(
            session=session,
            meeting_id=session.meeting.meeting_id,
        )[-self._max_messages :]
        return MeetingSpeakerContext(
            speaker_id=speaker_id,
            meeting_id=session.meeting.meeting_id,
            topic=session.meeting.topic,
            question_event_id=_latest_question_event_id(messages, speaker_id),
            question_text=action.text,
            subject_type=action.subject_type,
            subject_id=action.subject_id,
            public_messages=messages,
            public_evidence=_public_evidence(
                case=case,
                session=session,
                messages=messages,
                max_evidence=self._max_evidence,
            ),
            visible_memories=_visible_memory_contexts(
                session=session,
                speaker_id=speaker_id,
                max_memories=self._max_memories,
            ),
        )


def _public_meeting_messages(
    *,
    session: SessionState,
    meeting_id: str | None,
) -> list[MeetingMessageContext]:
    messages: list[MeetingMessageContext] = []
    for event in session.events:
        if event.type != EventType.MEETING_MESSAGE_POSTED:
            continue
        if meeting_id is not None and event.payload.get("meeting_id") != meeting_id:
            continue
        text = _optional_text(event.payload.get("text"))
        if text is None:
            continue
        messages.append(
            MeetingMessageContext(
                event_id=event.id,
                speaker_id=str(event.payload.get("speaker_id", event.actor_id)),
                message_kind=str(event.payload.get("message_kind", "message")),
                text=text,
                target_id=_optional_text(event.payload.get("target_id")),
                clue_id=_optional_text(event.payload.get("clue_id")),
            )
        )
    return messages


def _latest_question_event_id(
    messages: list[MeetingMessageContext],
    speaker_id: str,
) -> str | None:
    for message in reversed(messages):
        if message.message_kind == "question" and message.target_id == speaker_id:
            return message.event_id
    return None


def _public_evidence(
    *,
    case: CasePackage,
    session: SessionState,
    messages: list[MeetingMessageContext],
    max_evidence: int,
) -> list[MeetingEvidenceContext]:
    if max_evidence == 0:
        return []

    clue_by_id = {clue.id: clue for clue in case.clues}
    contexts: list[MeetingEvidenceContext] = []
    seen_clue_ids: set[str] = set()
    for message in messages:
        if message.message_kind != "evidence" or message.clue_id is None:
            continue
        if message.clue_id in seen_clue_ids:
            continue
        if message.clue_id not in session.discovered_clues:
            continue
        clue = clue_by_id.get(message.clue_id)
        if clue is None:
            continue
        contexts.append(
            MeetingEvidenceContext(
                clue_id=clue.id,
                title=clue.title,
                summary=clue.description,
                posted_event_id=message.event_id,
            )
        )
        seen_clue_ids.add(message.clue_id)
    return contexts[-max_evidence:]


def _visible_memory_contexts(
    *,
    session: SessionState,
    speaker_id: str,
    max_memories: int,
) -> list[MeetingMemoryContext]:
    if max_memories == 0:
        return []

    snapshots = [
        snapshot
        for snapshot in session.memory_snapshots.values()
        if _memory_visible_to_speaker(snapshot, speaker_id)
    ]
    snapshots.sort(
        key=lambda snapshot: (
            -snapshot.salience,
            -len(snapshot.source_event_ids),
            snapshot.memory_id,
        )
    )
    return [
        MeetingMemoryContext(
            memory_id=snapshot.memory_id,
            summary=snapshot.content,
            source_event_ids=list(snapshot.source_event_ids),
            source_memory_ids=list(snapshot.source_memory_ids),
            memory_type=str(snapshot.memory_type),
            memory_scope=str(snapshot.memory_scope),
            salience=snapshot.salience,
            confidence=snapshot.confidence,
        )
        for snapshot in snapshots[:max_memories]
    ]


def _memory_visible_to_speaker(
    snapshot: AgentMemorySnapshot,
    speaker_id: str,
) -> bool:
    scope = str(snapshot.memory_scope)
    if scope not in {"case", "session", "npc_private", "scene_shared"}:
        return False
    if not _memory_layer_allowed(snapshot):
        return False

    owner = snapshot.owner_character_id
    visible_to = set(snapshot.visible_to_character_ids)
    if scope in {"case", "session"}:
        return not visible_to or owner == speaker_id or speaker_id in visible_to
    if scope == "npc_private":
        return owner == speaker_id or speaker_id in visible_to
    if scope == "scene_shared":
        return owner == speaker_id or speaker_id in visible_to
    return False


def _memory_layer_allowed(snapshot: AgentMemorySnapshot) -> bool:
    scope = str(snapshot.memory_scope)
    layer = str(snapshot.memory_layer)
    if scope == "case":
        return layer == "core"
    if scope == "session":
        return layer == "working"
    return layer != "archival"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
