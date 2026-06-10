from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonEmptyString = Annotated[str, Field(min_length=1)]
RELATIONSHIP_MIN = -1.0
RELATIONSHIP_MAX = 1.0


class ActionType(StrEnum):
    INSPECT = "inspect"
    TALK = "talk"
    ASK_ABOUT = "ask_about"
    PRESENT_CLUE = "present_clue"
    ACCUSE = "accuse"


class SubjectType(StrEnum):
    CLUE = "clue"
    CHARACTER = "character"
    SCENE = "scene"


class AgentIntentType(StrEnum):
    ANSWER = "answer"
    CONCEAL = "conceal"
    LIE = "lie"
    REFUSE = "refuse"
    PROBE = "probe"
    PANIC = "panic"


class DefensiveStyle(StrEnum):
    EVASIVE = "evasive"
    HOSTILE = "hostile"
    ANXIOUS = "anxious"
    NEUTRAL = "neutral"


class CharacterResponseStyle(StrEnum):
    ANSWER = "answer"
    CONCEAL = "conceal"
    DEFLECT = "deflect"
    REFUSE = "refuse"
    PANIC_CONCEAL = "panic_conceal"
    CAUTIOUS_HELP = "cautious_help"


class PrivatePriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DisclosureMode(StrEnum):
    NONE = "none"
    DENY = "deny"
    DEFLECT = "deflect"
    HINT = "hint"
    PARTIAL = "partial"
    FULL = "full"


class RhetoricTactic(StrEnum):
    ANSWER_ADJACENT_TRUTH = "answer_adjacent_truth"
    SHIFT_FOCUS = "shift_focus"
    COUNTER_QUESTION = "counter_question"
    QUALIFY_CERTAINTY = "qualify_certainty"
    EMOTIONAL_SCREEN = "emotional_screen"
    SILENCE = "silence"


class WorldInfoCategory(StrEnum):
    PHYSICAL_FACT = "physical_fact"
    CHARACTER_ACTION = "character_action"
    CHARACTER_KNOWLEDGE = "character_knowledge"
    CASE_TRUTH = "case_truth"
    SOCIAL_FACT = "social_fact"


class WorldInfoSensitivity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlayerKnowledgeAcquisition(StrEnum):
    DISCOVERED = "discovered"
    HEARD = "heard"
    INFERRED = "inferred"
    ACCUSED = "accused"


class PlayerKnowledgeSourceType(StrEnum):
    CLUE = "clue"
    DIALOGUE = "dialogue"
    INFERENCE = "inference"
    ACCUSATION = "accusation"


class CharacterFactStance(StrEnum):
    KNOWS = "knows"
    SUSPECTS = "suspects"
    CONCEALS = "conceals"
    MISBELIEVES = "misbelieves"


class CharacterFactAwarenessSourceType(StrEnum):
    CHARACTER_CARD = "character_card"
    PLAYER_ASKED_ABOUT = "player_asked_about"
    PLAYER_PRESENTED_CLUE = "player_presented_clue"
    PLAYER_ACCUSED = "player_accused"


class EventType(StrEnum):
    SESSION_CREATED = "session.created"
    PLAYER_INSPECTED = "player.inspected"
    PLAYER_TALKED = "player.talked"
    PLAYER_ASKED_ABOUT = "player.asked_about"
    PLAYER_PRESENTED_CLUE = "player.presented_clue"
    PLAYER_ACCUSED = "player.accused"
    ACCUSATION_EVALUATED = "accusation.evaluated"
    NPC_REPLIED = "npc.replied"
    DIRECTOR_BLOCKED = "director.blocked"
    RULE_REJECTED = "rule.rejected"
    CLUE_DISCOVERED = "clue.discovered"
    RELATIONSHIP_CHANGED = "relationship.changed"
    RELATIONSHIP_THRESHOLD_CROSSED = "relationship.threshold.crossed"
    PLAYER_KNOWLEDGE_UPDATED = "player_knowledge.updated"
    CHARACTER_FACT_AWARENESS_UPDATED = "character_fact_awareness.updated"
    MEMORY_CANDIDATE_CREATED = "memory_candidate.created"
    AGENT_MEMORY_SNAPSHOT_UPDATED = "agent_memory_snapshot.updated"
    CHARACTER_IMPRESSION_UPDATED = "character_impression.updated"
    NARRATIVE_BEAT_COMPLETED = "narrative.beat.completed"
    NARRATIVE_PHASE_CHANGED = "narrative.phase.changed"


MemoryType = Literal["episodic", "belief", "relationship", "strategy"]
MemoryScope = Literal[
    "case",
    "session",
    "npc_private",
    "scene_shared",
    "director_audit",
]
MemoryLayer = Literal["core", "working", "archival"]
BeliefPolarity = Literal["believes", "suspects", "knows", "doubts"]
ALLOWED_MEMORY_METADATA_KEYS = frozenset(
    {
        "relationship_delta",
        "strategy_id",
        "belief_subject",
        "belief_polarity",
        "emotion_delta",
        "clue_id",
    }
)


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


class CharacterSpeechConfig(APIModel):
    style: str = ""
    default_tone: str = ""
    catchphrases: list[NonEmptyString] = Field(default_factory=list)
    defensive_style: DefensiveStyle = DefensiveStyle.EVASIVE


class CharacterPersonalityConfig(APIModel):
    traits: list[NonEmptyString] = Field(default_factory=list)
    pressure_response: CharacterResponseStyle = CharacterResponseStyle.CONCEAL
    trust_response: CharacterResponseStyle = CharacterResponseStyle.CAUTIOUS_HELP
    fear_response: CharacterResponseStyle = CharacterResponseStyle.PANIC_CONCEAL


class DisclosurePolicy(APIModel):
    revealable: bool = False
    allowed_modes: list[DisclosureMode] = Field(
        default_factory=lambda: [
            DisclosureMode.DENY,
            DisclosureMode.DEFLECT,
            DisclosureMode.HINT,
        ]
    )
    direct_reveal_allowed: bool = False
    direct_quote_allowed: bool = False


class PrivateGoal(APIModel):
    id: NonEmptyString
    summary: NonEmptyString
    priority: PrivatePriority = PrivatePriority.MEDIUM
    related_world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    tags: list[NonEmptyString] = Field(default_factory=list)
    disclosure_policy: DisclosurePolicy = Field(default_factory=DisclosurePolicy)


class PrivateSecret(APIModel):
    id: NonEmptyString
    summary: NonEmptyString
    priority: PrivatePriority = PrivatePriority.MEDIUM
    related_clue_ids: list[NonEmptyString] = Field(default_factory=list)
    related_world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    tags: list[NonEmptyString] = Field(default_factory=list)
    disclosure_policy: DisclosurePolicy = Field(default_factory=DisclosurePolicy)


class PrivateKnowledge(APIModel):
    id: NonEmptyString
    summary: NonEmptyString
    priority: PrivatePriority = PrivatePriority.MEDIUM
    related_clue_ids: list[NonEmptyString] = Field(default_factory=list)
    related_world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    tags: list[NonEmptyString] = Field(default_factory=list)
    disclosure_policy: DisclosurePolicy = Field(default_factory=DisclosurePolicy)


class CharacterDisclosureStyleConfig(APIModel):
    preferred_tactics: list[RhetoricTactic] = Field(default_factory=list)
    forbidden_tactics: list[RhetoricTactic] = Field(default_factory=list)
    max_mode_by_world_info: dict[NonEmptyString, DisclosureMode] = Field(default_factory=dict)


class CharacterPrivateConfig(APIModel):
    goals: list[PrivateGoal] = Field(default_factory=list)
    secrets: list[PrivateSecret] = Field(default_factory=list)
    knowledge: list[PrivateKnowledge] = Field(default_factory=list)
    disclosure_style: CharacterDisclosureStyleConfig = Field(
        default_factory=CharacterDisclosureStyleConfig
    )

    @field_validator("goals", mode="before")
    @classmethod
    def normalize_goals(cls, value: object) -> object:
        return normalize_private_items(value, "goal")

    @field_validator("secrets", mode="before")
    @classmethod
    def normalize_secrets(cls, value: object) -> object:
        return normalize_private_items(value, "secret")

    @field_validator("knowledge", mode="before")
    @classmethod
    def normalize_knowledge(cls, value: object) -> object:
        return normalize_private_items(value, "knowledge")


class CharacterConfig(APIModel):
    id: NonEmptyString
    display_name: NonEmptyString
    public_role: NonEmptyString
    public_description: str = ""
    speech: CharacterSpeechConfig = Field(default_factory=CharacterSpeechConfig)
    personality: CharacterPersonalityConfig = Field(default_factory=CharacterPersonalityConfig)
    private: CharacterPrivateConfig = Field(default_factory=CharacterPrivateConfig)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_character_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        legacy_name = normalized.pop("name", None)
        legacy_role = normalized.pop("role", None)
        legacy_speech_style = normalized.pop("speech_style", None)
        legacy_secrets = normalized.pop("secrets", None)
        legacy_goals = normalized.pop("goals", None)
        legacy_knowledge = normalized.pop("knowledge", None)
        legacy_personality = normalized.get("personality")

        if "display_name" not in normalized and legacy_name is not None:
            normalized["display_name"] = legacy_name
        if "public_role" not in normalized and legacy_role is not None:
            normalized["public_role"] = legacy_role

        if isinstance(legacy_personality, str):
            if not normalized.get("public_description"):
                normalized["public_description"] = legacy_personality
            normalized["personality"] = {}

        speech = normalized.get("speech")
        if not isinstance(speech, dict):
            speech = {}
        else:
            speech = dict(speech)
        if legacy_speech_style is not None and not speech.get("style"):
            speech["style"] = legacy_speech_style
        normalized["speech"] = speech

        private = normalized.get("private")
        if not isinstance(private, dict):
            private = {}
        else:
            private = dict(private)
        legacy_private_fields = {
            "goals": legacy_goals,
            "secrets": legacy_secrets,
            "knowledge": legacy_knowledge,
        }
        for field_name, field_value in legacy_private_fields.items():
            if field_value is not None and field_name not in private:
                private[field_name] = field_value
        normalized["private"] = private

        return normalized


class AgentCharacterView(APIModel):
    id: NonEmptyString
    display_name: NonEmptyString
    public_role: NonEmptyString
    public_description: str = ""
    speech_style: str = ""
    default_tone: str = ""
    catchphrases: list[NonEmptyString] = Field(default_factory=list)
    visible_traits: list[NonEmptyString] = Field(default_factory=list)
    defensive_style: DefensiveStyle = DefensiveStyle.EVASIVE
    pressure_response: CharacterResponseStyle = CharacterResponseStyle.CONCEAL
    trust_response: CharacterResponseStyle = CharacterResponseStyle.CAUTIOUS_HELP
    fear_response: CharacterResponseStyle = CharacterResponseStyle.PANIC_CONCEAL


class NPCPortraitState(APIModel):
    owner_character_id: NonEmptyString
    subject_id: NonEmptyString
    trust: float = 0.0
    suspicion: float = 0.0
    fear: float = 0.0
    traits: dict[str, float] = Field(default_factory=dict)
    current_strategy: str | None = None
    source_memory_ids: list[NonEmptyString] = Field(default_factory=list)

    @field_validator("trust", "suspicion", "fear", mode="before")
    @classmethod
    def clamp_portrait_metric(cls, value: object) -> float:
        return clamp_relationship_metric(value)


class SelfKnowledgeItem(APIModel):
    id: NonEmptyString
    kind: Literal["goal", "secret", "knowledge"]
    summary: NonEmptyString
    priority: PrivatePriority = PrivatePriority.MEDIUM
    related_clue_ids: list[NonEmptyString] = Field(default_factory=list)
    related_world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    tags: list[NonEmptyString] = Field(default_factory=list)
    disclosure_policy: DisclosurePolicy = Field(default_factory=DisclosurePolicy)
    source: Literal["character_card"] = "character_card"


class CharacterImpression(NPCPortraitState):
    observer_id: NonEmptyString
    target_id: NonEmptyString
    personality_impression: str = ""
    perceived_motive: str = ""
    suspected_knowledge_refs: list[NonEmptyString] = Field(default_factory=list)
    suspicious_points: list[NonEmptyString] = Field(default_factory=list)
    trust_boundary: str = ""
    alliance_potential: float = Field(default=0.0, ge=0.0, le=1.0)
    threat_level: float = Field(default=0.0, ge=0.0, le=1.0)
    manipulation_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    usefulness: float = Field(default=0.0, ge=0.0, le=1.0)
    tags: list[NonEmptyString] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_event_ids: list[NonEmptyString] = Field(default_factory=list)
    last_updated_event_id: NonEmptyString

    @model_validator(mode="before")
    @classmethod
    def normalize_portrait_aliases(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "owner_character_id" not in normalized and "observer_id" in normalized:
            normalized["owner_character_id"] = normalized["observer_id"]
        if "subject_id" not in normalized and "target_id" in normalized:
            normalized["subject_id"] = normalized["target_id"]
        if "observer_id" not in normalized and "owner_character_id" in normalized:
            normalized["observer_id"] = normalized["owner_character_id"]
        if "target_id" not in normalized and "subject_id" in normalized:
            normalized["target_id"] = normalized["subject_id"]
        return normalized


class CharacterFactAwarenessState(APIModel):
    awareness_id: NonEmptyString
    character_id: NonEmptyString
    world_info_id: NonEmptyString
    stance: CharacterFactStance
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_type: CharacterFactAwarenessSourceType
    source_refs: list[NonEmptyString] = Field(default_factory=list)
    evidence_clue_ids: list[NonEmptyString] = Field(default_factory=list)
    source_event_ids: list[NonEmptyString] = Field(default_factory=list)
    last_updated_event_id: NonEmptyString


class FactDisclosureStrategy(APIModel):
    world_info_id: NonEmptyString
    stance: CharacterFactStance
    allowed_modes: list[DisclosureMode] = Field(default_factory=list)
    forbidden_modes: list[DisclosureMode] = Field(default_factory=list)
    rhetoric_tactics: list[RhetoricTactic] = Field(default_factory=list)
    must_not_claim: list[NonEmptyString] = Field(default_factory=list)
    safe_fact_refs: list[NonEmptyString] = Field(default_factory=list)
    evidence_clue_ids: list[NonEmptyString] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_awareness_id: NonEmptyString


class CharacterInnerContext(APIModel):
    character_id: NonEmptyString
    inner_goals: list[SelfKnowledgeItem] = Field(default_factory=list)
    inner_secrets: list[SelfKnowledgeItem] = Field(default_factory=list)
    inner_knowledge: list[SelfKnowledgeItem] = Field(default_factory=list)
    fact_awareness: list[CharacterFactAwarenessState] = Field(default_factory=list)
    fact_disclosure_strategies: list[FactDisclosureStrategy] = Field(default_factory=list)
    inner_portraits: list[CharacterImpression] = Field(default_factory=list)


class LLMDisclosureConstraint(APIModel):
    item_id: NonEmptyString
    item_kind: Literal["goal", "secret", "knowledge", "forbidden_fact", "world_info"]
    allowed_modes: list[DisclosureMode] = Field(default_factory=list)
    forbidden_modes: list[DisclosureMode] = Field(default_factory=list)
    direct_reveal_allowed: bool = False
    direct_quote_allowed: bool = False
    related_clue_ids: list[NonEmptyString] = Field(default_factory=list)
    related_world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    rhetoric_tactics: list[RhetoricTactic] = Field(default_factory=list)
    must_not_claim: list[NonEmptyString] = Field(default_factory=list)
    safe_fact_refs: list[NonEmptyString] = Field(default_factory=list)
    blocked: bool = True


class LLMAgentOutputContract(APIModel):
    allowed_top_level_keys: list[NonEmptyString] = Field(
        default_factory=lambda: [
            "speech",
            "intent",
            "emotional_shift",
            "proposed_actions",
            "memory_refs",
            "disclosure_claims",
        ]
    )
    allowed_intents: list[AgentIntentType] = Field(
        default_factory=lambda: list(AgentIntentType)
    )
    fallback_intent: AgentIntentType = AgentIntentType.REFUSE
    allowed_proposed_action_types: list[ProposedActionType] = Field(
        default_factory=lambda: [
            ProposedActionType.DISCOVER_CLUE,
            ProposedActionType.RELATIONSHIP_CHANGE,
        ]
    )
    allowed_disclosure_modes: list[DisclosureMode] = Field(
        default_factory=lambda: [
            mode for mode in DisclosureMode if mode != DisclosureMode.FULL
        ]
    )
    allowed_rhetoric_tactics: list[RhetoricTactic] = Field(
        default_factory=lambda: list(RhetoricTactic)
    )
    disclosure_claim_required_for_world_info_touch: bool = True
    unknown_world_info_policy: Literal["avoid_or_refuse"] = "avoid_or_refuse"


class DisclosureClaim(APIModel):
    world_info_id: NonEmptyString
    mode: DisclosureMode
    tactic: RhetoricTactic | None = None
    source_refs: list[NonEmptyString] = Field(default_factory=list)
    claim_refs: list[NonEmptyString] = Field(default_factory=list)


class WorldInfoConfig(APIModel):
    id: NonEmptyString
    title: NonEmptyString
    description: str = ""
    category: WorldInfoCategory = WorldInfoCategory.CASE_TRUTH
    sensitivity: WorldInfoSensitivity = WorldInfoSensitivity.MEDIUM
    aliases: list[NonEmptyString] = Field(default_factory=list)
    claim_patterns: list[NonEmptyString] = Field(default_factory=list)


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
    reveals_world_info: list[NonEmptyString] = Field(default_factory=list)
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
    trust: float = 0.0
    suspicion: float = 0.0
    fear: float = 0.0
    intimacy: float = 0.0
    hostility: float = 0.0

    @field_validator("trust", "suspicion", "fear", "intimacy", "hostility", mode="before")
    @classmethod
    def clamp_relationship_metric(cls, value: object) -> float:
        return clamp_relationship_metric(value)


class ForbiddenFactConfig(APIModel):
    id: NonEmptyString
    text: NonEmptyString
    blocked_terms: list[NonEmptyString]
    reveal_phase: NonEmptyString | None = None
    world_info_id: NonEmptyString | None = None


class DiscoverClueAction(APIModel):
    type: Literal[ProposedActionType.DISCOVER_CLUE]
    clue_id: NonEmptyString


class RelationshipChangeAction(APIModel):
    type: Literal[ProposedActionType.RELATIONSHIP_CHANGE]
    source_id: NonEmptyString
    target_id: NonEmptyString
    deltas: dict[str, float]


class NarrativePhaseChangeAction(APIModel):
    type: Literal[ProposedActionType.NARRATIVE_PHASE_CHANGE]
    phase: NonEmptyString


ProposedAction = DiscoverClueAction | RelationshipChangeAction | NarrativePhaseChangeAction


class MockReplyConfig(APIModel):
    phase: NonEmptyString | None = None
    asked_subject_type: SubjectType | None = None
    asked_subject_id: NonEmptyString | None = None
    presented_clue: NonEmptyString | None = None
    min_interaction_pressure: float | None = Field(default=None, ge=0.0, le=1.0)
    max_interaction_pressure: float | None = Field(default=None, ge=0.0, le=1.0)
    requires_subject_sensitive: bool | None = None
    requires_discovered: list[NonEmptyString] = Field(default_factory=list)
    missing_discovered: list[NonEmptyString] = Field(default_factory=list)
    requires_memory: list[NonEmptyString] = Field(default_factory=list)
    missing_memory: list[NonEmptyString] = Field(default_factory=list)
    min_relationship: dict[str, float] = Field(default_factory=dict)
    max_relationship: dict[str, float] = Field(default_factory=dict)
    speech: NonEmptyString
    intent: AgentIntentType = AgentIntentType.ANSWER
    emotional_shift: dict[str, float] = Field(default_factory=dict)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)


class MockDialogueConfig(APIModel):
    character_id: NonEmptyString
    default_speech: NonEmptyString
    default_intent: AgentIntentType = AgentIntentType.ANSWER
    forbidden_test_speech: str | None = None
    relationship_delta_on_talk: dict[str, float] = Field(default_factory=dict)
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
    trigger_event_type: EventType | None = None
    trigger_payload: dict[str, str] = Field(default_factory=dict)
    next_phase: NonEmptyString | None = None


class NarrativeRulesConfig(APIModel):
    phases: list[NarrativePhaseConfig] = Field(default_factory=list)
    beats: list[NarrativeBeatConfig] = Field(default_factory=list)


class SolutionClaimConfig(APIModel):
    id: NonEmptyString
    target_id: NonEmptyString
    required_evidence: list[NonEmptyString] = Field(default_factory=list)
    required_world_info: list[NonEmptyString] = Field(default_factory=list)
    allowed_phases: list[NonEmptyString] = Field(default_factory=list)
    result: Literal["correct", "incorrect"]


class SolutionClaimsConfig(APIModel):
    claims: list[SolutionClaimConfig] = Field(default_factory=list)


class CasePackage(APIModel):
    meta: CaseMeta
    world_info: list[WorldInfoConfig] = Field(default_factory=list)
    characters: list[CharacterConfig]
    scenes: list[SceneConfig]
    clues: list[ClueConfig]
    relationships: list[RelationshipConfig] = Field(default_factory=list)
    forbidden_facts: list[ForbiddenFactConfig] = Field(default_factory=list)
    mock_dialogues: list[MockDialogueConfig] = Field(default_factory=list)
    narrative_rules: NarrativeRulesConfig = Field(default_factory=NarrativeRulesConfig)
    solution_claims: SolutionClaimsConfig = Field(default_factory=SolutionClaimsConfig)


class PlayerAction(APIModel):
    type: ActionType
    target_id: NonEmptyString
    clue_id: NonEmptyString | None = None
    scene_id: NonEmptyString | None = None
    claim_id: NonEmptyString | None = None
    evidence_clue_ids: list[NonEmptyString] = Field(default_factory=list)
    subject_type: SubjectType | None = None
    subject_id: NonEmptyString | None = None
    text: str | None = None
    force_forbidden: bool = False

    @model_validator(mode="after")
    def validate_action_specific_fields(self) -> PlayerAction:
        if self.type == ActionType.ASK_ABOUT:
            if self.subject_type is None or self.subject_id is None:
                raise ValueError("ask_about requires subject_type and subject_id")
            if self.clue_id is not None:
                raise ValueError("clue_id is only valid for present_clue")
            if self.scene_id is not None:
                raise ValueError("scene_id is only valid for present_clue")
            if self.claim_id is not None or self.evidence_clue_ids:
                raise ValueError("claim fields are only valid for accuse")
            return self
        if self.type == ActionType.PRESENT_CLUE:
            if self.clue_id is None:
                raise ValueError("present_clue requires clue_id")
            if self.subject_type is not None or self.subject_id is not None:
                raise ValueError("subject fields are only valid for ask_about")
            if self.claim_id is not None or self.evidence_clue_ids:
                raise ValueError("claim fields are only valid for accuse")
            return self
        if self.type == ActionType.ACCUSE:
            if self.claim_id is None:
                raise ValueError("accuse requires claim_id")
            if self.clue_id is not None:
                raise ValueError("clue_id is only valid for present_clue")
            if self.scene_id is not None:
                raise ValueError("scene_id is only valid for present_clue")
            if self.subject_type is not None or self.subject_id is not None:
                raise ValueError("subject fields are only valid for ask_about")
            return self
        if self.clue_id is not None:
            raise ValueError("clue_id is only valid for present_clue")
        if self.scene_id is not None:
            raise ValueError("scene_id is only valid for present_clue")
        if self.claim_id is not None or self.evidence_clue_ids:
            raise ValueError("claim fields are only valid for accuse")
        if self.subject_type is not None or self.subject_id is not None:
            raise ValueError("subject fields are only valid for ask_about")
        return self


class AgentIntent(APIModel):
    speech: NonEmptyString
    intent: AgentIntentType
    emotional_shift: dict[str, float] = Field(default_factory=dict)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    disclosure_claims: list[DisclosureClaim] = Field(default_factory=list)

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


class PromptBundle(APIModel):
    agent_prompt: NonEmptyString
    contract_instruction: NonEmptyString
    safety_instruction: NonEmptyString


class DirectorDecision(APIModel):
    allowed: bool
    reason: str | None = None
    blocked_fact_id: str | None = None
    safe_speech: str | None = None
    world_info_id: str | None = None
    claimed_mode: DisclosureMode | None = None
    detected_directness: str | None = None
    matched_by: str | None = None
    matched_text: str | None = None
    pattern_id: str | None = None
    safe_fallback_used: bool = False


class RelationshipState(APIModel):
    source_id: NonEmptyString
    target_id: NonEmptyString
    trust: float = 0.0
    suspicion: float = 0.0
    fear: float = 0.0
    intimacy: float = 0.0
    hostility: float = 0.0

    @field_validator("trust", "suspicion", "fear", "intimacy", "hostility", mode="before")
    @classmethod
    def clamp_state_relationship_metric(cls, value: object) -> float:
        return clamp_relationship_metric(value)


class PlayerKnowledgeState(APIModel):
    knowledge_id: NonEmptyString
    clue_id: NonEmptyString | None = None
    world_info_id: NonEmptyString | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    acquisition: PlayerKnowledgeAcquisition = PlayerKnowledgeAcquisition.DISCOVERED
    source_type: PlayerKnowledgeSourceType = PlayerKnowledgeSourceType.CLUE
    title: NonEmptyString
    summary: str
    source_event_id: NonEmptyString


class MemoryCandidateState(APIModel):
    memory_id: NonEmptyString
    rule_id: NonEmptyString | None = None
    memory_type: MemoryType = "episodic"
    memory_scope: MemoryScope = "npc_private"
    memory_layer: MemoryLayer = "working"
    subject_id: NonEmptyString
    owner_character_id: NonEmptyString | None = None
    visible_to_character_ids: list[NonEmptyString] = Field(default_factory=list)
    content: NonEmptyString
    source_event_id: NonEmptyString
    source_event_ids: list[NonEmptyString] = Field(default_factory=list)
    source_memory_ids: list[NonEmptyString] = Field(default_factory=list)
    visibility: list[NonEmptyString] = Field(default_factory=list)
    salience: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_memory_metadata(cls, value: object) -> dict[str, Any]:
        return validate_memory_metadata(value)


class AgentMemorySnapshot(APIModel):
    memory_id: NonEmptyString
    rule_id: NonEmptyString | None = None
    memory_type: MemoryType = "episodic"
    memory_scope: MemoryScope = "npc_private"
    memory_layer: MemoryLayer = "working"
    subject_id: NonEmptyString | None = None
    owner_character_id: NonEmptyString | None = None
    visible_to_character_ids: list[NonEmptyString] = Field(default_factory=list)
    content: NonEmptyString
    source_event_ids: list[NonEmptyString] = Field(default_factory=list)
    source_memory_ids: list[NonEmptyString] = Field(default_factory=list)
    salience: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    visibility: Literal["private", "public"] = "private"
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_updated_event_id: NonEmptyString
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_memory_metadata(cls, value: object) -> dict[str, Any]:
        return validate_memory_metadata(value)


class CompressedHistoryContext(APIModel):
    summary: str
    important_event_ids: list[str] = Field(default_factory=list)
    important_memory_ids: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class AgentContext(APIModel):
    case_id: NonEmptyString
    session_id: NonEmptyString
    target_agent_id: NonEmptyString
    current_phase: NonEmptyString
    completed_beats: list[NonEmptyString] = Field(default_factory=list)
    discovered_clues: list[NonEmptyString] = Field(default_factory=list)
    player_knowledge: list[PlayerKnowledgeState] = Field(default_factory=list)
    relationship_to_player: RelationshipState | None = None
    relationship_thresholds_crossed: list[str] = Field(default_factory=list)
    recent_events: list[WorldEvent] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidateState] = Field(default_factory=list)
    memory_snapshots: list[AgentMemorySnapshot] = Field(default_factory=list)
    compressed_history: CompressedHistoryContext | None = None
    blocked_fact_ids: list[NonEmptyString] = Field(default_factory=list)
    revealable_fact_ids: list[NonEmptyString] = Field(default_factory=list)
    asked_subject_type: SubjectType | None = None
    asked_subject_id: NonEmptyString | None = None
    interaction_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    subject_is_sensitive: bool = False
    presented_clue_id: NonEmptyString | None = None
    presented_knowledge_id: NonEmptyString | None = None
    player_action: PlayerAction
    target_profile: AgentCharacterView | None = None
    inner_context: CharacterInnerContext | None = None
    portrait_summary: str | None = None
    default_speech: str | None = None
    default_intent: AgentIntentType | None = None
    reply_options: list[MockReplyConfig] = Field(default_factory=list)
    fallback_relationship_delta: dict[str, float] = Field(default_factory=dict)


class LLMAgentContractInput(APIModel):
    agent_context: AgentContext
    disclosure_constraints: list[LLMDisclosureConstraint] = Field(default_factory=list)
    output_contract: LLMAgentOutputContract = Field(
        default_factory=LLMAgentOutputContract
    )
    required_output_schema: Literal["AgentIntent"] = "AgentIntent"


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
    relationship_thresholds_crossed: set[str] = Field(default_factory=set)
    discovered_clues: set[str] = Field(default_factory=set)
    player_knowledge: dict[str, PlayerKnowledgeState] = Field(default_factory=dict)
    character_fact_awareness: dict[str, CharacterFactAwarenessState] = Field(
        default_factory=dict
    )
    memory_candidates: dict[str, MemoryCandidateState] = Field(default_factory=dict)
    memory_snapshots: dict[str, AgentMemorySnapshot] = Field(default_factory=dict)
    character_impressions: dict[str, dict[str, CharacterImpression]] = Field(
        default_factory=dict
    )
    events: list[WorldEvent] = Field(default_factory=list)


class CreateSessionRequest(APIModel):
    case_id: str | None = None


class CreateSessionResponse(APIModel):
    session_id: NonEmptyString
    state: StateSummary


class CharacterSummary(APIModel):
    id: NonEmptyString
    display_name: NonEmptyString
    public_role: NonEmptyString
    public_description: str = ""


class ClueSummary(APIModel):
    id: NonEmptyString
    title: NonEmptyString
    description: str
    key: bool


class PlayerKnowledgeSummary(APIModel):
    knowledge_id: NonEmptyString
    clue_id: NonEmptyString | None = None
    world_info_id: NonEmptyString | None = None
    confidence: float
    acquisition: PlayerKnowledgeAcquisition
    source_type: PlayerKnowledgeSourceType
    title: NonEmptyString
    summary: str


class StateSummary(APIModel):
    session_id: NonEmptyString
    case_id: NonEmptyString
    case_title: NonEmptyString
    narrative_phase: NonEmptyString
    completed_beats: list[NonEmptyString]
    characters: list[CharacterSummary]
    discovered_clues: list[ClueSummary]
    player_knowledge: list[PlayerKnowledgeSummary]
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


def clamp_relationship_metric(value: object) -> float:
    numeric_value = float(value)
    clamped = min(max(numeric_value, RELATIONSHIP_MIN), RELATIONSHIP_MAX)
    return round(clamped, 4)


def validate_memory_metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("memory metadata must be an object")
    metadata = {str(key): item for key, item in value.items()}
    unknown_keys = set(metadata) - ALLOWED_MEMORY_METADATA_KEYS
    if unknown_keys:
        raise ValueError(f"Unsupported memory metadata keys: {sorted(unknown_keys)}")
    if "relationship_delta" in metadata:
        metadata["relationship_delta"] = _validate_metric_delta(
            metadata["relationship_delta"],
            "relationship_delta",
        )
    if "emotion_delta" in metadata:
        metadata["emotion_delta"] = _validate_metric_delta(
            metadata["emotion_delta"],
            "emotion_delta",
        )
    if "belief_polarity" in metadata and metadata["belief_polarity"] not in {
        "believes",
        "suspects",
        "knows",
        "doubts",
    }:
        raise ValueError("belief_polarity is not supported")
    for key in ("strategy_id", "belief_subject", "clue_id"):
        if key in metadata and metadata[key] is not None:
            metadata[key] = str(metadata[key])
    return metadata


def _validate_metric_delta(value: object, field_name: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return {str(key): clamp_relationship_metric(item) for key, item in value.items()}


def normalize_private_items(value: object, prefix: str) -> object:
    if value is None:
        return []
    if not isinstance(value, list):
        return value

    normalized: list[object] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            normalized.append(
                {
                    "id": f"{prefix}_{index:03d}",
                    "summary": item,
                }
            )
        else:
            normalized.append(item)
    return normalized
