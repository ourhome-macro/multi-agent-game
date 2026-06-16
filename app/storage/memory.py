from __future__ import annotations

from uuid import uuid4

from app.domain.models import (
    CasePackage,
    CharacterSummary,
    ClueConfig,
    ClueSummary,
    EventType,
    EvidenceSummary,
    NarrativeState,
    PlayerKnowledgeState,
    PlayerKnowledgeSummary,
    RelationshipState,
    SessionState,
    StateSummary,
)
from app.rules.engine import relationship_key
from app.runtime.character_fact_awareness import build_initial_character_fact_awareness
from app.runtime.events import EventRecorder


class InMemoryCaseStore:
    def __init__(self) -> None:
        self._cases: dict[str, CasePackage] = {}

    def add(self, package: CasePackage) -> None:
        self._cases[package.meta.id] = package

    def get(self, case_id: str) -> CasePackage:
        try:
            return self._cases[case_id]
        except KeyError as exc:
            raise KeyError(f"Unknown case_id: {case_id}") from exc

    def list(self) -> list[CasePackage]:
        return list(self._cases.values())

    def default_case_id(self) -> str:
        if not self._cases:
            raise KeyError("No case packages loaded")
        return next(iter(self._cases))


class InMemorySessionStore:
    def __init__(self, recorder: EventRecorder) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._recorder = recorder

    def create(self, package: CasePackage) -> SessionState:
        session = SessionState(
            id=str(uuid4()),
            case_id=package.meta.id,
            narrative=NarrativeState(phase=package.meta.initial_phase),
            relationships={
                relationship_key(item.source_id, item.target_id): RelationshipState(
                    **item.model_dump()
                )
                for item in package.relationships
            },
        )
        session.character_fact_awareness = build_initial_character_fact_awareness(package)
        self._recorder.append(
            session,
            actor_id="system",
            event_type=EventType.SESSION_CREATED,
            payload={"case_id": package.meta.id, "initial_phase": package.meta.initial_phase},
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> SessionState:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown session_id: {session_id}") from exc


def build_state_summary(package: CasePackage, session: SessionState) -> StateSummary:
    clue_by_id = {clue.id: clue for clue in package.clues}
    discovered_clues = [
        ClueSummary(
            id=clue.id,
            title=clue.title,
            description=clue.description,
            key=clue.key,
        )
        for clue_id in sorted(session.discovered_clues)
        if (clue := clue_by_id.get(clue_id)) is not None
    ]
    evidence_assets = [
        summary
        for item in sorted(
            session.player_knowledge.values(),
            key=lambda value: value.knowledge_id,
        )
        if (summary := _build_evidence_summary(item, clue_by_id, session)) is not None
    ]

    return StateSummary(
        session_id=session.id,
        case_id=session.case_id,
        case_title=package.meta.title,
        narrative_phase=session.narrative.phase,
        completed_beats=sorted(session.narrative.completed_beats),
        characters=[
            CharacterSummary(
                id=character.id,
                display_name=character.display_name,
                public_role=character.public_role,
                public_description=character.public_description,
            )
            for character in package.characters
        ],
        discovered_clues=discovered_clues,
        player_knowledge=[
            PlayerKnowledgeSummary(
                knowledge_id=item.knowledge_id,
                clue_id=item.clue_id,
                world_info_id=item.world_info_id,
                confidence=item.confidence,
                acquisition=item.acquisition,
                source_type=item.source_type,
                title=item.title,
                summary=item.summary,
            )
            for item in sorted(
                session.player_knowledge.values(),
                key=lambda value: value.knowledge_id,
            )
        ],
        evidence_assets=evidence_assets,
        relationships=list(session.relationships.values()),
        event_count=len(session.events),
    )


def _build_evidence_summary(
    item: PlayerKnowledgeState,
    clue_by_id: dict[str, ClueConfig],
    session: SessionState,
) -> EvidenceSummary | None:
    if item.clue_id is None or item.clue_id not in session.discovered_clues:
        return None
    clue = clue_by_id.get(item.clue_id)
    if clue is None:
        return None
    return EvidenceSummary(
        id=clue.id,
        title=clue.title,
        summary=clue.description,
        source=item.source_type,
        clue_id=item.clue_id,
        world_info_id=item.world_info_id,
        source_knowledge_id=item.knowledge_id,
        unlocked_at_event_id=item.source_event_id,
    )
