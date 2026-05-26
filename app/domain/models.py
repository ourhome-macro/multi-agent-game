from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

NonEmptyString = Annotated[str, Field(min_length=1)]


class ActionType(StrEnum):
    INSPECT = "inspect"
    TALK = "talk"


class AgentIntentType(StrEnum):
    ANSWER = "answer"
    CONCEAL = "conceal"
    LIE = "lie"
    REFUSE = "refuse"
    PROBE = "probe"
    PANIC = "panic"


class EventType(StrEnum):
    SESSION_CREATED = "session.created"
    PLAYER_INSPECTED = "player.inspected"
    PLAYER_TALKED = "player.talked"
    NPC_REPLIED = "npc.replied"
    DIRECTOR_BLOCKED = "director.blocked"
    RULE_REJECTED = "rule.rejected"
    CLUE_DISCOVERED = "clue.discovered"
    RELATIONSHIP_CHANGED = "relationship.changed"
    NARRATIVE_BEAT_COMPLETED = "narrative.beat.completed"
    NARRATIVE_PHASE_CHANGED = "narrative.phase.changed"


class ProposedActionType(StrEnum):
    DISCOVER_CLUE = "clue.discover"
    RELATIONSHIP_CHANGE = "relationship.change"
    NARRATIVE_PHASE_CHANGE = "narrative.phase.change"


ALLOWED_PROPOSED_ACTION_TYPES = frozenset(item.value for item in ProposedActionType)


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseMeta(APIModel):
    id: NonEmptyString
    title: NonEmptyString
    description: str = ""
    initial_phase: NonEmptyString


class CharacterConfig(APIModel):
    id: NonEmptyString
    name: NonEmptyString
    role: NonEmptyString
    personality: str = ""
    speech_style: str = ""
    secrets: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)


class SceneHotspotConfig(APIModel):
    id: NonEmptyString
    name: NonEmptyString
    description: str = ""
    discover_clues: list[str] = Field(default_factory=list)


class SceneConfig(APIModel):
    id: NonEmptyString
    name: NonEmptyString
    description: str = ""
    hotspots: list[SceneHotspotConfig] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)


class ClueConfig(APIModel):
    id: NonEmptyString
    title: NonEmptyString
    description: str
    truth_status: Literal["true", "false", "unknown"] = "unknown"
    related_characters: list[str] = Field(default_factory=list)
    related_events: list[str] = Field(default_factory=list)
    key: bool = False

    @field_validator("truth_status", mode="before")
    @classmethod
    def normalize_truth_status(cls, value: object) -> object:
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, str):
            return value.lower()
        return value


class RelationshipConfig(APIModel):
    source_id: NonEmptyString
    target_id: NonEmptyString
    trust: int = 0
    suspicion: int = 0
    fear: int = 0
    intimacy: int = 0
    hostility: int = 0


class ForbiddenFactConfig(APIModel):
    id: NonEmptyString
    text: NonEmptyString
    blocked_terms: list[NonEmptyString]
    reveal_phase: NonEmptyString | None = None


class DiscoverClueAction(APIModel):
    type: Literal[ProposedActionType.DISCOVER_CLUE]
    clue_id: NonEmptyString


class RelationshipChangeAction(APIModel):
    type: Literal[ProposedActionType.RELATIONSHIP_CHANGE]
    source_id: NonEmptyString
    target_id: NonEmptyString
    deltas: dict[str, int]


class NarrativePhaseChangeAction(APIModel):
    type: Literal[ProposedActionType.NARRATIVE_PHASE_CHANGE]
    phase: NonEmptyString


ProposedAction = DiscoverClueAction | RelationshipChangeAction | NarrativePhaseChangeAction


class MockReplyConfig(APIModel):
    phase: NonEmptyString | None = None
    requires_discovered: list[NonEmptyString] = Field(default_factory=list)
    missing_discovered: list[NonEmptyString] = Field(default_factory=list)
    min_relationship: dict[str, int] = Field(default_factory=dict)
    max_relationship: dict[str, int] = Field(default_factory=dict)
    speech: NonEmptyString
    intent: AgentIntentType = AgentIntentType.ANSWER
    emotional_shift: dict[str, int] = Field(default_factory=dict)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)


class MockDialogueConfig(APIModel):
    character_id: NonEmptyString
    default_speech: NonEmptyString
    default_intent: AgentIntentType = AgentIntentType.ANSWER
    forbidden_test_speech: str | None = None
    relationship_delta_on_talk: dict[str, int] = Field(default_factory=dict)
    replies: list[MockReplyConfig] = Field(default_factory=list)


class NarrativePhaseConfig(APIModel):
    id: NonEmptyString
    title: str = ""


class NarrativeBeatConfig(APIModel):
    id: NonEmptyString
    phase: NonEmptyString | None = None
    description: str = ""
    all_completed: list[NonEmptyString] = Field(default_factory=list)
    min_completed: int = Field(default=0, ge=0)
    all_discovered: list[NonEmptyString] = Field(default_factory=list)
    next_phase: NonEmptyString | None = None


class NarrativeRulesConfig(APIModel):
    phases: list[NarrativePhaseConfig] = Field(default_factory=list)
    beats: list[NarrativeBeatConfig] = Field(default_factory=list)


class CasePackage(APIModel):
    meta: CaseMeta
    characters: list[CharacterConfig]
    scenes: list[SceneConfig]
    clues: list[ClueConfig]
    relationships: list[RelationshipConfig] = Field(default_factory=list)
    forbidden_facts: list[ForbiddenFactConfig] = Field(default_factory=list)
    mock_dialogues: list[MockDialogueConfig] = Field(default_factory=list)
    narrative_rules: NarrativeRulesConfig = Field(default_factory=NarrativeRulesConfig)


class PlayerAction(APIModel):
    type: ActionType
    target_id: NonEmptyString
    text: str | None = None
    force_forbidden: bool = False


class AgentIntent(APIModel):
    speech: NonEmptyString
    intent: AgentIntentType
    emotional_shift: dict[str, int] = Field(default_factory=dict)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)

    @field_validator("proposed_actions", mode="before")
    @classmethod
    def validate_proposed_action_whitelist(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        for item in value:
            if not isinstance(item, dict):
                continue
            action_type = item.get("type")
            if isinstance(action_type, ProposedActionType):
                action_type = action_type.value
            if action_type not in ALLOWED_PROPOSED_ACTION_TYPES:
                raise ValueError(f"Unsupported proposed action type: {action_type}")
        return value


class DirectorDecision(APIModel):
    allowed: bool
    reason: str | None = None
    blocked_fact_id: str | None = None
    safe_speech: str | None = None


class RelationshipState(APIModel):
    source_id: NonEmptyString
    target_id: NonEmptyString
    trust: int = 0
    suspicion: int = 0
    fear: int = 0
    intimacy: int = 0
    hostility: int = 0


class NarrativeState(APIModel):
    phase: NonEmptyString
    discovered_clues: set[str] = Field(default_factory=set)
    completed_beats: set[str] = Field(default_factory=set)


class WorldEvent(APIModel):
    id: NonEmptyString = Field(default_factory=lambda: str(uuid4()))
    case_id: NonEmptyString
    session_id: NonEmptyString
    actor_id: NonEmptyString
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    caused_by_event_id: str | None = None
    created_at: NonEmptyString


class SessionState(APIModel):
    id: NonEmptyString
    case_id: NonEmptyString
    narrative: NarrativeState
    relationships: dict[str, RelationshipState]
    discovered_clues: set[str] = Field(default_factory=set)
    events: list[WorldEvent] = Field(default_factory=list)


class CreateSessionRequest(APIModel):
    case_id: str | None = None


class CreateSessionResponse(APIModel):
    session_id: NonEmptyString
    state: StateSummary


class CharacterSummary(APIModel):
    id: NonEmptyString
    name: NonEmptyString
    role: NonEmptyString


class ClueSummary(APIModel):
    id: NonEmptyString
    title: NonEmptyString
    description: str
    key: bool


class StateSummary(APIModel):
    session_id: NonEmptyString
    case_id: NonEmptyString
    case_title: NonEmptyString
    narrative_phase: NonEmptyString
    completed_beats: list[NonEmptyString]
    characters: list[CharacterSummary]
    discovered_clues: list[ClueSummary]
    relationships: list[RelationshipState]
    event_count: int


class ActionResponse(APIModel):
    session_id: NonEmptyString
    accepted: bool
    speech: str | None = None
    director_blocked: bool = False
    director_reason: str | None = None
    new_events: list[WorldEvent]
    state: StateSummary
