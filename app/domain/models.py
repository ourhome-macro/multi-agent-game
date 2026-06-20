from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, cast
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


class PresentationMode(StrEnum):
    PRIVATE = "private"
    SCENE_SHARED = "scene_shared"


class AgentIntentType(StrEnum):
    ANSWER = "answer"
    CONCEAL = "conceal"
    LIE = "lie"
    REFUSE = "refuse"
    PROBE = "probe"
    PANIC = "panic"


class LLMErrorType(StrEnum):
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    INVALID_JSON = "invalid_json"
    SCHEMA_ERROR = "schema_error"
    POLICY_VIOLATION = "policy_violation"
    PRIVATE_LEAK_DETECTED = "private_leak_detected"
    CONTEXT_OVER_LIMIT = "context_over_limit"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN_ERROR = "unknown_error"


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


def default_agent_disclosure_modes() -> list[DisclosureMode]:
    return [mode for mode in DisclosureMode if mode != DisclosureMode.FULL]


def default_safe_fragment_disclosure_modes() -> list[DisclosureMode]:
    return [DisclosureMode.HINT, DisclosureMode.PARTIAL]


def default_forbidden_inference_blocked_modes() -> list[DisclosureMode]:
    return [
        DisclosureMode.HINT,
        DisclosureMode.PARTIAL,
        DisclosureMode.FULL,
    ]


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
    NPC_SKILL_SELECTED = "npc_skill.selected"
    NPC_SKILL_REJECTED = "npc_skill.rejected"
    NPC_SKILL_COOLDOWN_UPDATED = "npc_skill.cooldown.updated"
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
MemoryAuthority = Literal[
    "rule_verified",
    "event_observed",
    "npc_belief",
    "player_claim",
    "hypothesis",
    "non_authoritative",
]


class MemoryOperation(StrEnum):
    CREATE = "create"
    REINFORCE = "reinforce"
    REVISE = "revise"
    SUPERSEDE = "supersede"
    ARCHIVE = "archive"


LEGACY_MEMORY_OPERATION_ALIASES = {
    "created": MemoryOperation.CREATE,
    "updated": MemoryOperation.REINFORCE,
    "reinforced": MemoryOperation.REINFORCE,
    "revised": MemoryOperation.REVISE,
    "superseded": MemoryOperation.SUPERSEDE,
    "archived": MemoryOperation.ARCHIVE,
    "seeded": MemoryOperation.CREATE,
}

ALLOWED_MEMORY_DECAY_POLICY_NAMES = frozenset(
    {
        "standard",
        "sticky",
        "ephemeral",
        "never_archive",
    }
)
ALLOWED_MEMORY_DECAY_POLICY_KEYS = frozenset(
    {
        "name",
        "archive_after_days",
        "reinforced_event_count",
    }
)
ALLOWED_MEMORY_AUTHORITY_SOURCES = frozenset(
    {
        "system_rule",
        "rule_derived",
        "player_evidence",
        "player_action",
        "world_event",
        "npc_direct",
        "npc_hearsay",
        "llm_summary",
        "archival",
    }
)
ALLOWED_MEMORY_AUTHORITIES = frozenset(
    {
        "rule_verified",
        "event_observed",
        "npc_belief",
        "player_claim",
        "hypothesis",
        "non_authoritative",
    }
)
ALLOWED_MEMORY_METADATA_KEYS = frozenset(
    {
        "relationship_delta",
        "strategy_id",
        "belief_subject",
        "belief_polarity",
        "emotion_delta",
        "clue_id",
        "world_info_id",
        "claim_id",
        "case_thread_id",
        "chain_node_id",
        "adjacent_clue_ids",
        "key_clue",
        "scene_id",
        "phase_id",
        "phase_ids",
        "topic_tags",
        "privacy_reason",
        "decay_policy",
        "non_authoritative",
        "authority_source",
        "authority",
        "is_plot_critical",
        "quarantine_reason",
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


class NpcSkillType(StrEnum):
    DIALOGUE = "dialogue"
    SOCIAL = "social"
    INVESTIGATION = "investigation"
    MEMORY = "memory"
    PLOT_GATED = "plot_gated"


class NpcSkillPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NpcSkillTriggerConfig(APIModel):
    action_types: list[ActionType] = Field(default_factory=list)
    subject_types: list[SubjectType] = Field(default_factory=list)
    subject_ids: list[NonEmptyString] = Field(default_factory=list)
    clue_ids: list[NonEmptyString] = Field(default_factory=list)
    topic_tags: list[NonEmptyString] = Field(default_factory=list)


class NpcSkillUnlockCondition(APIModel):
    phases: list[NonEmptyString] = Field(default_factory=list)
    completed_beats: list[NonEmptyString] = Field(default_factory=list)
    required_discovered_clues: list[NonEmptyString] = Field(default_factory=list)
    required_player_knowledge: list[NonEmptyString] = Field(default_factory=list)
    required_world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    required_pressure_min: float | None = Field(default=None, ge=0.0, le=1.0)
    suspicion_min: float | None = Field(default=None, ge=-1.0, le=1.0)
    trust_min: float | None = Field(default=None, ge=-1.0, le=1.0)
    fear_min: float | None = Field(default=None, ge=-1.0, le=1.0)


class NpcSkillDisclosurePolicy(APIModel):
    world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    max_mode: DisclosureMode = DisclosureMode.DEFLECT
    allowed_tactics: list[RhetoricTactic] = Field(default_factory=list)
    safe_fragment_refs: list[NonEmptyString] = Field(default_factory=list)
    forbidden_claim_refs: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_full_mode(self) -> NpcSkillDisclosurePolicy:
        if self.max_mode == DisclosureMode.FULL:
            raise ValueError("NPC skill disclosure max_mode must not be full")
        return self


class NpcSkillMemoryPolicy(APIModel):
    include_types: list[MemoryType] = Field(default_factory=list)
    include_scopes: list[MemoryScope] = Field(default_factory=list)
    include_layers: list[MemoryLayer] = Field(default_factory=list)
    topic_tags: list[NonEmptyString] = Field(default_factory=list)
    max_items: int | None = Field(default=None, ge=0)


class NpcSkillProposedActionPolicy(APIModel):
    allowed: list[ProposedActionType] = Field(default_factory=list)
    max_relationship_delta: dict[str, float] = Field(default_factory=dict)

    @field_validator("max_relationship_delta", mode="before")
    @classmethod
    def clamp_delta(cls, value: object) -> dict[str, float]:
        if value is None:
            return {}
        return _validate_metric_delta(value, "max_relationship_delta")


class NpcSkillCooldownConfig(APIModel):
    turns: int = Field(default=0, ge=0)


class NpcSkillFailureConfig(APIModel):
    fallback_skill_id: NonEmptyString | None = None


class NpcSkillConfig(APIModel):
    id: NonEmptyString
    owner_character_ids: list[NonEmptyString]
    type: NpcSkillType
    level: int = Field(default=1, ge=0)
    priority: NpcSkillPriority = NpcSkillPriority.MEDIUM
    signature: bool = False
    triggers: NpcSkillTriggerConfig = Field(default_factory=NpcSkillTriggerConfig)
    unlock_conditions: NpcSkillUnlockCondition = Field(
        default_factory=NpcSkillUnlockCondition
    )
    disclosure: NpcSkillDisclosurePolicy = Field(default_factory=NpcSkillDisclosurePolicy)
    memory: NpcSkillMemoryPolicy = Field(default_factory=NpcSkillMemoryPolicy)
    proposed_action_policy: NpcSkillProposedActionPolicy = Field(
        default_factory=NpcSkillProposedActionPolicy
    )
    cooldown: NpcSkillCooldownConfig = Field(default_factory=NpcSkillCooldownConfig)
    failure: NpcSkillFailureConfig = Field(default_factory=NpcSkillFailureConfig)

    @model_validator(mode="after")
    def validate_owners(self) -> NpcSkillConfig:
        if not self.owner_character_ids:
            raise ValueError("NPC skill must define owner_character_ids")
        return self


class NpcSkillProjection(APIModel):
    skill_id: NonEmptyString
    type: NpcSkillType
    level: int = Field(ge=0)
    signature: bool = False
    allowed_intents: list[AgentIntentType] = Field(default_factory=list)
    allowed_tactics: list[RhetoricTactic] = Field(default_factory=list)
    max_disclosure_mode_by_world_info: dict[NonEmptyString, DisclosureMode] = Field(
        default_factory=dict
    )
    safe_fragment_refs: list[NonEmptyString] = Field(default_factory=list)
    memory_plan_id: NonEmptyString | None = None
    allowed_proposed_actions: list[ProposedActionType] = Field(default_factory=list)
    max_relationship_delta: dict[str, float] = Field(default_factory=dict)


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


class SafeFactFragmentProjection(APIModel):
    world_info_id: NonEmptyString
    fragment_id: NonEmptyString
    ref: NonEmptyString
    summary: NonEmptyString
    aliases: list[NonEmptyString] = Field(default_factory=list)
    claim_patterns: list[NonEmptyString] = Field(default_factory=list)
    allowed_modes: list[DisclosureMode] = Field(default_factory=list)
    source_refs: list[NonEmptyString] = Field(default_factory=list)


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
    safe_fragments: list[SafeFactFragmentProjection] = Field(default_factory=list)
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
        default_factory=default_agent_disclosure_modes
    )
    allowed_rhetoric_tactics: list[RhetoricTactic] = Field(
        default_factory=lambda: list(RhetoricTactic)
    )
    max_relationship_delta: dict[str, float] = Field(default_factory=dict)
    disclosure_claim_required_for_world_info_touch: bool = True
    unknown_world_info_policy: Literal["avoid_or_refuse"] = "avoid_or_refuse"


class DisclosureClaim(APIModel):
    world_info_id: NonEmptyString
    mode: DisclosureMode
    tactic: RhetoricTactic | None = None
    source_refs: list[NonEmptyString] = Field(default_factory=list)
    claim_refs: list[NonEmptyString] = Field(default_factory=list)


class LLMSchemaValidationError(APIModel):
    loc: list[str] = Field(default_factory=list)
    error_type: str = "unknown"
    message_sanitized: str = ""


class LLMErrorSummary(APIModel):
    backend: NonEmptyString
    error_type: LLMErrorType
    error_message_sanitized: NonEmptyString
    fallback_used: bool = True
    schema_validation_errors: list[LLMSchemaValidationError] = Field(default_factory=list)


class FactUnlockConditionConfig(APIModel):
    phases: list[NonEmptyString] = Field(default_factory=list)
    completed_beats: list[NonEmptyString] = Field(default_factory=list)
    discovered_clues: list[NonEmptyString] = Field(default_factory=list)
    player_knowledge_ids: list[NonEmptyString] = Field(default_factory=list)
    player_world_info_ids: list[NonEmptyString] = Field(default_factory=list)


class SafeFactFragmentConfig(APIModel):
    id: NonEmptyString
    summary: NonEmptyString
    aliases: list[NonEmptyString] = Field(default_factory=list)
    claim_patterns: list[NonEmptyString] = Field(default_factory=list)
    allowed_modes: list[DisclosureMode] = Field(
        default_factory=default_safe_fragment_disclosure_modes
    )
    unlock_conditions: FactUnlockConditionConfig = Field(
        default_factory=FactUnlockConditionConfig
    )


class ForbiddenInferenceConfig(APIModel):
    id: NonEmptyString
    summary: str = ""
    trigger_fragment_ids: list[NonEmptyString] = Field(default_factory=list)
    trigger_world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    aliases: list[NonEmptyString] = Field(default_factory=list)
    claim_patterns: list[NonEmptyString] = Field(default_factory=list)
    blocked_modes: list[DisclosureMode] = Field(
        default_factory=default_forbidden_inference_blocked_modes
    )
    unlock_conditions: FactUnlockConditionConfig | None = None


class ClaimGraphConfig(APIModel):
    safe_fragments: list[SafeFactFragmentConfig] = Field(default_factory=list)
    forbidden_inferences: list[ForbiddenInferenceConfig] = Field(default_factory=list)


class WorldInfoConfig(APIModel):
    id: NonEmptyString
    title: NonEmptyString
    description: str = ""
    category: WorldInfoCategory = WorldInfoCategory.CASE_TRUTH
    sensitivity: WorldInfoSensitivity = WorldInfoSensitivity.MEDIUM
    aliases: list[NonEmptyString] = Field(default_factory=list)
    claim_patterns: list[NonEmptyString] = Field(default_factory=list)
    claim_graph: ClaimGraphConfig = Field(default_factory=ClaimGraphConfig)


class BacktrackUnlockConditionConfig(APIModel):
    phases: list[NonEmptyString] = Field(default_factory=list)
    completed_beats: list[NonEmptyString] = Field(default_factory=list)
    discovered_clues: list[NonEmptyString] = Field(default_factory=list)
    player_knowledge_ids: list[NonEmptyString] = Field(default_factory=list)
    player_world_info_ids: list[NonEmptyString] = Field(default_factory=list)
    prior_inspected_hotspots: list[NonEmptyString] = Field(default_factory=list)
    min_prior_inspections: int = Field(default=1, ge=1)


class BacktrackClueUnlockConfig(APIModel):
    id: NonEmptyString
    clue_ids: list[NonEmptyString] = Field(default_factory=list)
    conditions: BacktrackUnlockConditionConfig = Field(
        default_factory=BacktrackUnlockConditionConfig
    )

    @model_validator(mode="after")
    def require_clue_ids(self) -> BacktrackClueUnlockConfig:
        if not self.clue_ids:
            raise ValueError("backtrack unlock must define at least one clue_id")
        return self


class SceneHotspotConfig(APIModel):
    id: NonEmptyString
    name: NonEmptyString
    description: str = ""
    discover_clues: list[str] = Field(default_factory=list)
    backtrack_unlocks: list[BacktrackClueUnlockConfig] = Field(default_factory=list)


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


class MemoryEffectConfig(APIModel):
    """A memory candidate a rule derives from a runtime event.

    ``memory_id`` / ``memory_id_template`` and ``content`` /
    ``content_template`` may use controlled event variables. The rendered
    values must remain stable so events stay replayable.
    """

    rule_id: NonEmptyString | None = None
    memory_id: NonEmptyString | None = None
    memory_id_template: NonEmptyString | None = None
    memory_type: MemoryType = "episodic"
    memory_scope: MemoryScope = "npc_private"
    memory_layer: MemoryLayer = "working"
    operation: MemoryOperation = MemoryOperation.CREATE
    subject_id: NonEmptyString = "player"
    owner_character_id: NonEmptyString | None = "{target_id}"
    visible_to_character_ids: list[NonEmptyString] = Field(
        default_factory=lambda: ["{target_id}"]
    )
    content: NonEmptyString | None = None
    content_template: NonEmptyString | None = None
    salience: float = Field(default=0.0, ge=0.0, le=1.0)
    salience_from_event: NonEmptyString | None = None
    min_salience: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_event_ids: list[NonEmptyString] = Field(
        default_factory=lambda: ["{source_event_id}"]
    )
    source_memory_ids: list[NonEmptyString] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_memory_metadata(cls, value: object) -> dict[str, Any]:
        return validate_memory_metadata(value)

    @field_validator("operation", mode="before")
    @classmethod
    def validate_memory_operation(cls, value: object) -> MemoryOperation:
        return normalize_memory_operation(value)

    @model_validator(mode="after")
    def validate_templates(self) -> MemoryEffectConfig:
        if self.memory_id is None and self.memory_id_template is None:
            raise ValueError("memory effect must define memory_id or memory_id_template")
        if self.content is None and self.content_template is None:
            raise ValueError("memory effect must define content or content_template")
        return self

    @property
    def memory_id_pattern(self) -> str:
        return str(self.memory_id_template or self.memory_id)

    @property
    def content_pattern(self) -> str:
        return str(self.content_template or self.content)


class MemoryImpressionEffectConfig(APIModel):
    """Optional portrait nudge applied when a derivation rule fires.

    These deltas mirror the relationship/strategy memory the rule already
    produces, so the NPC's private impression stays aligned with its memory
    without the author configuring the same numbers twice.
    """

    relationship_delta: dict[str, float] = Field(default_factory=dict)
    strategy_id: NonEmptyString | None = None
    traits: dict[str, float] = Field(default_factory=dict)


class MemoryDerivationRuleConfig(APIModel):
    id: NonEmptyString
    trigger_action_type: NonEmptyString | None = None
    trigger_event_type: NonEmptyString | None = None
    target_id: NonEmptyString | None = None
    target_character_id: NonEmptyString | None = None
    subject_id: NonEmptyString | None = None
    clue_id: NonEmptyString | None = None
    claim_id: NonEmptyString | None = None
    produces: list[MemoryEffectConfig] = Field(default_factory=list)
    impression: MemoryImpressionEffectConfig | None = None

    @model_validator(mode="after")
    def validate_trigger(self) -> MemoryDerivationRuleConfig:
        if self.trigger_event_type is None and self.trigger_action_type is None:
            raise ValueError(
                "memory derivation rule must define trigger_event_type "
                "or trigger_action_type"
            )
        if (
            self.trigger_event_type is not None
            and self.trigger_action_type is not None
            and self.trigger_event_type != self.trigger_action_type
        ):
            raise ValueError(
                "trigger_event_type and trigger_action_type must match when both are set"
            )
        if (
            self.target_id is not None
            and self.target_character_id is not None
            and self.target_id != self.target_character_id
        ):
            raise ValueError(
                "target_id and target_character_id must match when both are set"
            )
        if (
            self.clue_id is not None
            and self.subject_id is not None
            and self.clue_id != self.subject_id
        ):
            raise ValueError("clue_id and subject_id must match when both are set")
        return self

    @property
    def trigger_type(self) -> str:
        return str(self.trigger_event_type or self.trigger_action_type)

    @property
    def target_match_id(self) -> str | None:
        return self.target_id or self.target_character_id

    @property
    def subject_match_id(self) -> str | None:
        return self.clue_id or self.subject_id


class CasePackage(APIModel):
    meta: CaseMeta
    world_info: list[WorldInfoConfig] = Field(default_factory=list)
    characters: list[CharacterConfig]
    scenes: list[SceneConfig]
    clues: list[ClueConfig]
    relationships: list[RelationshipConfig] = Field(default_factory=list)
    forbidden_facts: list[ForbiddenFactConfig] = Field(default_factory=list)
    mock_dialogues: list[MockDialogueConfig] = Field(default_factory=list)
    npc_skills: list[NpcSkillConfig] = Field(default_factory=list)
    memory_derivation_rules: list[MemoryDerivationRuleConfig] = Field(default_factory=list)
    narrative_rules: NarrativeRulesConfig = Field(default_factory=NarrativeRulesConfig)
    solution_claims: SolutionClaimsConfig = Field(default_factory=SolutionClaimsConfig)


class PlayerAction(APIModel):
    type: ActionType
    target_id: NonEmptyString
    clue_id: NonEmptyString | None = None
    scene_id: NonEmptyString | None = None
    presentation_mode: PresentationMode | None = None
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
            if self.presentation_mode is not None:
                raise ValueError("presentation_mode is only valid for present_clue")
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
            if (
                self.presentation_mode == PresentationMode.PRIVATE
                and self.scene_id is not None
            ):
                raise ValueError("private present_clue cannot set scene_id")
            if (
                self.presentation_mode == PresentationMode.SCENE_SHARED
                and self.scene_id is None
            ):
                raise ValueError("scene_shared present_clue requires scene_id")
            return self
        if self.type == ActionType.ACCUSE:
            if self.claim_id is None:
                raise ValueError("accuse requires claim_id")
            if self.clue_id is not None:
                raise ValueError("clue_id is only valid for present_clue")
            if self.scene_id is not None:
                raise ValueError("scene_id is only valid for present_clue")
            if self.presentation_mode is not None:
                raise ValueError("presentation_mode is only valid for present_clue")
            if self.subject_type is not None or self.subject_id is not None:
                raise ValueError("subject fields are only valid for ask_about")
            return self
        if self.clue_id is not None:
            raise ValueError("clue_id is only valid for present_clue")
        if self.scene_id is not None:
            raise ValueError("scene_id is only valid for present_clue")
        if self.presentation_mode is not None:
            raise ValueError("presentation_mode is only valid for present_clue")
        if self.claim_id is not None or self.evidence_clue_ids:
            raise ValueError("claim fields are only valid for accuse")
        if self.subject_type is not None or self.subject_id is not None:
            raise ValueError("subject fields are only valid for ask_about")
        return self

    @property
    def effective_presentation_mode(self) -> PresentationMode | None:
        if self.type != ActionType.PRESENT_CLUE:
            return None
        if self.presentation_mode is not None:
            return self.presentation_mode
        if self.scene_id is not None:
            return PresentationMode.SCENE_SHARED
        return PresentationMode.PRIVATE


class AgentIntent(APIModel):
    speech: NonEmptyString
    intent: AgentIntentType
    emotional_shift: dict[str, float] = Field(default_factory=dict)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    disclosure_claims: list[DisclosureClaim] = Field(default_factory=list)
    llm_error: LLMErrorSummary | None = None

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


class EvidenceAsset(APIModel):
    id: NonEmptyString
    title: NonEmptyString
    summary: str
    source: PlayerKnowledgeSourceType = PlayerKnowledgeSourceType.CLUE
    clue_id: NonEmptyString | None = None
    world_info_id: NonEmptyString | None = None
    source_knowledge_id: NonEmptyString


class MemoryCandidateState(APIModel):
    memory_id: NonEmptyString
    rule_id: NonEmptyString | None = None
    memory_type: MemoryType = "episodic"
    memory_scope: MemoryScope = "npc_private"
    memory_layer: MemoryLayer = "working"
    operation: MemoryOperation = MemoryOperation.CREATE
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

    @field_validator("operation", mode="before")
    @classmethod
    def validate_memory_operation(cls, value: object) -> MemoryOperation:
        return normalize_memory_operation(value)


class AgentMemorySnapshot(APIModel):
    memory_id: NonEmptyString
    rule_id: NonEmptyString | None = None
    memory_type: MemoryType = "episodic"
    memory_scope: MemoryScope = "npc_private"
    memory_layer: MemoryLayer = "working"
    last_operation: MemoryOperation = MemoryOperation.CREATE
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

    @field_validator("last_operation", mode="before")
    @classmethod
    def validate_memory_operation(cls, value: object) -> MemoryOperation:
        return normalize_memory_operation(value)


def normalize_memory_operation(value: object) -> MemoryOperation:
    if isinstance(value, MemoryOperation):
        return value
    if value is None:
        return MemoryOperation.CREATE
    normalized = str(value).casefold()
    alias = LEGACY_MEMORY_OPERATION_ALIASES.get(normalized)
    if alias is not None:
        return alias
    return MemoryOperation(normalized)


def serialize_memory_operation(operation: MemoryOperation) -> str:
    return operation.value


class CompressedHistoryContext(APIModel):
    summary: str
    important_event_ids: list[str] = Field(default_factory=list)
    important_memory_ids: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class LLMHardContextProjection(APIModel):
    current_phase: NonEmptyString
    completed_beats: list[NonEmptyString] = Field(default_factory=list)
    discovered_clues: list[NonEmptyString] = Field(default_factory=list)
    player_knowledge_ids: list[NonEmptyString] = Field(default_factory=list)
    blocked_fact_ids: list[NonEmptyString] = Field(default_factory=list)
    revealable_fact_ids: list[NonEmptyString] = Field(default_factory=list)
    director_safe_fragment_refs: list[NonEmptyString] = Field(default_factory=list)
    selected_npc_skill_ids: list[NonEmptyString] = Field(default_factory=list)
    selected_memory_ids: list[NonEmptyString] = Field(default_factory=list)
    security_flags: list[NonEmptyString] = Field(default_factory=list)
    output_contract_allowed_intents: list[NonEmptyString] = Field(default_factory=list)
    output_contract_allowed_proposed_actions: list[NonEmptyString] = Field(
        default_factory=list
    )
    required_output_schema: Literal["AgentIntent"] = "AgentIntent"


class LLMSoftContextProjection(APIModel):
    recent_event_ids: list[NonEmptyString] = Field(default_factory=list)
    compressed_history_present: bool = False
    compressed_history_event_ids: list[NonEmptyString] = Field(default_factory=list)
    compressed_history_memory_ids: list[NonEmptyString] = Field(default_factory=list)
    memory_description_ids: list[NonEmptyString] = Field(default_factory=list)
    portrait_summary_present: bool = False


class LLMContextLayerProjection(APIModel):
    hard: LLMHardContextProjection
    soft: LLMSoftContextProjection
    compression_policy: Literal["soft_only"] = "soft_only"


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
    director_safe_fragments: list[SafeFactFragmentProjection] = Field(
        default_factory=list
    )
    npc_skill_projections: list[NpcSkillProjection] = Field(default_factory=list)
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
    context_layers: LLMContextLayerProjection
    required_output_schema: Literal["AgentIntent"] = "AgentIntent"
    turn_plan_id: str | None = None


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


class RawTextActionRequest(APIModel):
    raw_text: NonEmptyString


class RawTextActionResponse(APIModel):
    status: NonEmptyString
    action: PlayerAction | None = None
    response: ActionResponse | None = None
    reason: str | None = None
    missing_slots: list[NonEmptyString] = Field(default_factory=list)
    route_trace: dict[str, object] = Field(default_factory=dict)


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


class EvidenceSummary(EvidenceAsset):
    unlocked_at_event_id: NonEmptyString


class StateSummary(APIModel):
    session_id: NonEmptyString
    case_id: NonEmptyString
    case_title: NonEmptyString
    narrative_phase: NonEmptyString
    completed_beats: list[NonEmptyString]
    characters: list[CharacterSummary]
    discovered_clues: list[ClueSummary]
    player_knowledge: list[PlayerKnowledgeSummary]
    evidence_assets: list[EvidenceSummary] = Field(default_factory=list)
    relationships: list[RelationshipState]
    event_count: int


class ActionResponse(APIModel):
    session_id: NonEmptyString
    accepted: bool
    speech: str | None = None
    director_blocked: bool = False
    director_reason: str | None = None
    llm_fallback_used: bool = False
    llm_error: LLMErrorSummary | None = None
    new_events: list[WorldEvent]
    state: StateSummary


def clamp_relationship_metric(value: object) -> float:
    numeric_value = float(cast(Any, value))
    clamped = min(max(numeric_value, RELATIONSHIP_MIN), RELATIONSHIP_MAX)
    return round(clamped, 4)


def validate_memory_metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {"authority": "event_observed", "non_authoritative": False}
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
    for key in (
        "strategy_id",
        "belief_subject",
        "clue_id",
        "world_info_id",
        "claim_id",
        "case_thread_id",
        "chain_node_id",
        "scene_id",
        "phase_id",
        "privacy_reason",
    ):
        if key in metadata and metadata[key] is not None:
            metadata[key] = _validate_metadata_string(metadata[key], key)
    if "phase_ids" in metadata:
        metadata["phase_ids"] = _validate_metadata_string_list(
            metadata["phase_ids"],
            "phase_ids",
        )
    if "topic_tags" in metadata:
        metadata["topic_tags"] = _validate_metadata_string_list(
            metadata["topic_tags"],
            "topic_tags",
        )
    if "adjacent_clue_ids" in metadata:
        metadata["adjacent_clue_ids"] = _validate_metadata_string_list(
            metadata["adjacent_clue_ids"],
            "adjacent_clue_ids",
        )
    if "decay_policy" in metadata:
        metadata["decay_policy"] = _validate_decay_policy(metadata["decay_policy"])
    if "non_authoritative" in metadata and not isinstance(
        metadata["non_authoritative"],
        bool,
    ):
        raise ValueError("non_authoritative must be a boolean")
    if "authority_source" in metadata:
        metadata["authority_source"] = _validate_authority_source(
            metadata["authority_source"]
        )
    if "authority" in metadata:
        metadata["authority"] = _validate_memory_authority(metadata["authority"])
    else:
        metadata["authority"] = _default_memory_authority(metadata)
    if "non_authoritative" not in metadata:
        metadata["non_authoritative"] = metadata["authority"] == "non_authoritative"
    elif metadata["non_authoritative"] and metadata["authority"] != "non_authoritative":
        raise ValueError(
            "non_authoritative cannot be true when authority is authoritative"
        )
    if "is_plot_critical" in metadata and not isinstance(
        metadata["is_plot_critical"],
        bool,
    ):
        raise ValueError("is_plot_critical must be a boolean")
    if "key_clue" in metadata and not isinstance(metadata["key_clue"], bool):
        raise ValueError("key_clue must be a boolean")
    if "quarantine_reason" in metadata and metadata["quarantine_reason"] is not None:
        metadata["quarantine_reason"] = _validate_metadata_string(
            metadata["quarantine_reason"],
            "quarantine_reason",
        )
    return metadata


def _validate_metric_delta(value: object, field_name: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return {str(key): clamp_relationship_metric(item) for key, item in value.items()}


def _validate_metadata_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def _validate_metadata_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    normalized: list[str] = []
    for item in value:
        text = _validate_metadata_string(item, field_name)
        if text not in normalized:
            normalized.append(text)
    return normalized


def _validate_authority_source(value: object) -> str:
    normalized = _validate_metadata_string(value, "authority_source")
    if normalized not in ALLOWED_MEMORY_AUTHORITY_SOURCES:
        raise ValueError(f"authority_source is not supported: {normalized}")
    return normalized


def _validate_memory_authority(value: object) -> str:
    normalized = _validate_metadata_string(value, "authority")
    if normalized not in ALLOWED_MEMORY_AUTHORITIES:
        raise ValueError(f"authority is not supported: {normalized}")
    return normalized


def _default_memory_authority(metadata: dict[str, Any]) -> str:
    if metadata.get("non_authoritative") is True:
        return "non_authoritative"
    authority_source = metadata.get("authority_source")
    if authority_source in {"system_rule", "rule_derived"}:
        return "rule_verified"
    if authority_source in {"player_evidence", "player_action", "world_event"}:
        return "event_observed"
    if authority_source == "npc_direct":
        return "npc_belief"
    if authority_source in {"npc_hearsay", "llm_summary", "archival"}:
        return "non_authoritative"
    return "event_observed"


def _validate_decay_policy(value: object) -> str | dict[str, int | str]:
    if isinstance(value, str):
        normalized = _validate_metadata_string(value, "decay_policy")
        if normalized not in ALLOWED_MEMORY_DECAY_POLICY_NAMES:
            raise ValueError(f"decay_policy is not supported: {normalized}")
        return normalized
    if not isinstance(value, dict):
        raise ValueError("decay_policy must be a string or object")
    policy = {str(key): item for key, item in value.items()}
    unknown_keys = set(policy) - ALLOWED_MEMORY_DECAY_POLICY_KEYS
    if unknown_keys:
        raise ValueError(
            f"Unsupported memory decay_policy keys: {sorted(unknown_keys)}"
        )
    normalized_policy: dict[str, int | str] = {}
    if "name" in policy:
        name = _validate_metadata_string(policy["name"], "decay_policy.name")
        if name not in ALLOWED_MEMORY_DECAY_POLICY_NAMES:
            raise ValueError(f"decay_policy.name is not supported: {name}")
        normalized_policy["name"] = name
    if "archive_after_days" in policy:
        archive_after_days = _validate_non_negative_int(
            policy["archive_after_days"],
            "decay_policy.archive_after_days",
        )
        normalized_policy["archive_after_days"] = archive_after_days
    if "reinforced_event_count" in policy:
        reinforced_event_count = _validate_positive_int(
            policy["reinforced_event_count"],
            "decay_policy.reinforced_event_count",
        )
        normalized_policy["reinforced_event_count"] = reinforced_event_count
    return normalized_policy


def _validate_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        number = int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return number


def _validate_positive_int(value: object, field_name: str) -> int:
    number = _validate_non_negative_int(value, field_name)
    if number <= 0:
        raise ValueError(f"{field_name} must be positive")
    return number


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
