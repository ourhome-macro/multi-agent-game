from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.domain.models import (
    AgentContext,
    AgentMemorySnapshot,
    APIModel,
    CharacterFactAwarenessState,
    CharacterImpression,
    CharacterInnerContext,
    FactDisclosureStrategy,
    LLMAgentContractInput,
    LLMAgentOutputContract,
    LLMDisclosureConstraint,
    PlayerAction,
    PlayerKnowledgeState,
    RelationshipState,
    SafeFactFragmentProjection,
    SelfKnowledgeItem,
    WorldEvent,
)

PROVIDER_PAYLOAD_KIND = "llm_provider_turn.v1"

PROVIDER_MEMORY_METADATA_KEYS = frozenset(
    {
        "belief_polarity",
        "belief_subject",
        "case_thread_id",
        "chain_node_id",
        "claim_id",
        "clue_id",
        "key_clue",
        "non_authoritative",
        "phase_id",
        "phase_ids",
        "scene_id",
        "topic_tags",
        "world_info_id",
        "authority",
        "adjacent_clue_ids",
    }
)


class LLMProviderPlayerAction(APIModel):
    type: str
    target_id: str
    clue_id: str | None = None
    scene_id: str | None = None
    presentation_mode: str | None = None
    claim_id: str | None = None
    evidence_clue_ids: list[str] = Field(default_factory=list)
    subject_type: str | None = None
    subject_id: str | None = None
    text: str | None = None


class LLMProviderTurn(APIModel):
    case_id: str
    target_agent_id: str
    current_phase: str
    completed_beats: list[str] = Field(default_factory=list)
    discovered_clues: list[str] = Field(default_factory=list)
    blocked_fact_ids: list[str] = Field(default_factory=list)
    revealable_fact_ids: list[str] = Field(default_factory=list)
    asked_subject_type: str | None = None
    asked_subject_id: str | None = None
    interaction_pressure: float = 0.0
    subject_is_sensitive: bool = False
    presented_clue_id: str | None = None
    presented_knowledge_id: str | None = None
    action: LLMProviderPlayerAction


class LLMProviderNpcProfile(APIModel):
    id: str
    display_name: str
    public_role: str
    public_description: str = ""
    speech_style: str = ""
    default_tone: str = ""
    catchphrases: list[str] = Field(default_factory=list)
    visible_traits: list[str] = Field(default_factory=list)
    defensive_style: str
    pressure_response: str
    trust_response: str
    fear_response: str


class LLMProviderRelationship(APIModel):
    source_id: str
    target_id: str
    trust: float = 0.0
    suspicion: float = 0.0
    fear: float = 0.0
    intimacy: float = 0.0
    hostility: float = 0.0


class LLMProviderPlayerKnowledge(APIModel):
    knowledge_id: str
    clue_id: str | None = None
    world_info_id: str | None = None
    confidence: float
    acquisition: str
    source_type: str
    title: str
    summary: str


class LLMProviderMemory(APIModel):
    memory_id: str
    memory_type: str
    memory_scope: str
    memory_layer: str
    subject_id: str | None = None
    owner_character_id: str | None = None
    content: str
    confidence: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMProviderRecentEvent(APIModel):
    id: str
    type: str
    actor_id: str
    safe_summary: str


class LLMProviderSelfKnowledge(APIModel):
    id: str
    kind: Literal["goal", "secret", "knowledge"]
    summary: str
    priority: str
    related_clue_ids: list[str] = Field(default_factory=list)
    related_world_info_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    allowed_modes: list[str] = Field(default_factory=list)
    direct_reveal_allowed: bool = False
    direct_quote_allowed: bool = False


class LLMProviderFactAwareness(APIModel):
    world_info_id: str
    stance: str
    confidence: float
    source_type: str
    evidence_clue_ids: list[str] = Field(default_factory=list)


class LLMProviderDisclosureStrategy(APIModel):
    world_info_id: str
    stance: str
    allowed_modes: list[str] = Field(default_factory=list)
    forbidden_modes: list[str] = Field(default_factory=list)
    rhetoric_tactics: list[str] = Field(default_factory=list)
    must_not_claim: list[str] = Field(default_factory=list)
    safe_fact_refs: list[str] = Field(default_factory=list)
    evidence_clue_ids: list[str] = Field(default_factory=list)
    confidence: float


class LLMProviderPortraitSummary(APIModel):
    target_id: str
    trust: float
    suspicion: float
    fear: float
    personality_impression: str = ""
    perceived_motive: str = ""
    suspicious_points: list[str] = Field(default_factory=list)
    trust_boundary: str = ""
    threat_level: float
    manipulation_risk: float
    usefulness: float
    tags: list[str] = Field(default_factory=list)
    confidence: float


class LLMProviderPrivateContext(APIModel):
    character_id: str
    self_knowledge: list[LLMProviderSelfKnowledge] = Field(default_factory=list)
    fact_awareness: list[LLMProviderFactAwareness] = Field(default_factory=list)
    disclosure_strategies: list[LLMProviderDisclosureStrategy] = Field(default_factory=list)
    portraits: list[LLMProviderPortraitSummary] = Field(default_factory=list)


class LLMProviderSafeFact(APIModel):
    world_info_id: str
    fragment_id: str
    ref: str
    summary: str
    aliases: list[str] = Field(default_factory=list)
    claim_patterns: list[str] = Field(default_factory=list)
    allowed_modes: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class LLMProviderDisclosureLimit(APIModel):
    item_id: str
    item_kind: str
    allowed_modes: list[str] = Field(default_factory=list)
    forbidden_modes: list[str] = Field(default_factory=list)
    direct_reveal_allowed: bool = False
    direct_quote_allowed: bool = False
    related_clue_ids: list[str] = Field(default_factory=list)
    related_world_info_ids: list[str] = Field(default_factory=list)
    rhetoric_tactics: list[str] = Field(default_factory=list)
    must_not_claim: list[str] = Field(default_factory=list)
    safe_fact_refs: list[str] = Field(default_factory=list)
    blocked: bool = True


class LLMProviderSkill(APIModel):
    skill_id: str
    type: str
    level: int
    signature: bool = False
    allowed_intents: list[str] = Field(default_factory=list)
    allowed_tactics: list[str] = Field(default_factory=list)
    max_disclosure_mode_by_world_info: dict[str, str] = Field(default_factory=dict)
    safe_fragment_refs: list[str] = Field(default_factory=list)
    memory_plan_id: str | None = None
    allowed_proposed_actions: list[str] = Field(default_factory=list)
    max_relationship_delta: dict[str, float] = Field(default_factory=dict)


class LLMProviderOutputLimits(APIModel):
    required_output_schema: Literal["AgentIntent"] = "AgentIntent"
    allowed_top_level_keys: list[str] = Field(default_factory=list)
    allowed_intents: list[str] = Field(default_factory=list)
    fallback_intent: str
    allowed_proposed_action_types: list[str] = Field(default_factory=list)
    allowed_disclosure_modes: list[str] = Field(default_factory=list)
    allowed_rhetoric_tactics: list[str] = Field(default_factory=list)
    max_relationship_delta: dict[str, float] = Field(default_factory=dict)
    disclosure_claim_required_for_world_info_touch: bool
    unknown_world_info_policy: str


class LLMProviderTurnPayload(APIModel):
    payload_kind: Literal["llm_provider_turn.v1"] = "llm_provider_turn.v1"
    turn: LLMProviderTurn
    npc: LLMProviderNpcProfile | None = None
    relationship_to_player: LLMProviderRelationship | None = None
    player_knowledge: list[LLMProviderPlayerKnowledge] = Field(default_factory=list)
    memories: list[LLMProviderMemory] = Field(default_factory=list)
    recent_events: list[LLMProviderRecentEvent] = Field(default_factory=list)
    private_context: LLMProviderPrivateContext | None = None
    portrait_summary: str | None = None
    safe_facts: list[LLMProviderSafeFact] = Field(default_factory=list)
    disclosure_limits: list[LLMProviderDisclosureLimit] = Field(default_factory=list)
    npc_skills: list[LLMProviderSkill] = Field(default_factory=list)
    context_layers: dict[str, Any]
    output_limits: LLMProviderOutputLimits


def build_llm_provider_turn_payload(
    contract_input: LLMAgentContractInput,
) -> LLMProviderTurnPayload:
    context = contract_input.agent_context
    return LLMProviderTurnPayload(
        turn=_project_turn(context),
        npc=_project_npc_profile(context),
        relationship_to_player=_project_relationship(context.relationship_to_player),
        player_knowledge=[
            _project_player_knowledge(item) for item in context.player_knowledge
        ],
        memories=[_project_memory(memory) for memory in context.memory_snapshots],
        recent_events=[_project_recent_event(event) for event in context.recent_events],
        private_context=_project_private_context(context.inner_context),
        portrait_summary=context.portrait_summary,
        safe_facts=_project_safe_facts(contract_input.disclosure_constraints),
        disclosure_limits=[
            _project_disclosure_limit(constraint)
            for constraint in contract_input.disclosure_constraints
        ],
        npc_skills=[
            LLMProviderSkill.model_validate(skill.model_dump(mode="json"))
            for skill in context.npc_skill_projections
        ],
        context_layers=contract_input.context_layers.model_dump(mode="json"),
        output_limits=_project_output_limits(contract_input.output_contract),
    )


def build_llm_provider_payload(
    contract_input: LLMAgentContractInput,
) -> dict[str, Any]:
    return build_llm_provider_turn_payload(contract_input).model_dump(
        mode="json",
        exclude_none=True,
    )


def _project_turn(context: AgentContext) -> LLMProviderTurn:
    return LLMProviderTurn(
        case_id=context.case_id,
        target_agent_id=context.target_agent_id,
        current_phase=context.current_phase,
        completed_beats=list(context.completed_beats),
        discovered_clues=list(context.discovered_clues),
        blocked_fact_ids=list(context.blocked_fact_ids),
        revealable_fact_ids=list(context.revealable_fact_ids),
        asked_subject_type=_enum_value(context.asked_subject_type),
        asked_subject_id=context.asked_subject_id,
        interaction_pressure=context.interaction_pressure,
        subject_is_sensitive=context.subject_is_sensitive,
        presented_clue_id=context.presented_clue_id,
        presented_knowledge_id=context.presented_knowledge_id,
        action=_project_action(context.player_action),
    )


def _project_action(action: PlayerAction) -> LLMProviderPlayerAction:
    return LLMProviderPlayerAction(
        type=_enum_value(action.type) or str(action.type),
        target_id=action.target_id,
        clue_id=action.clue_id,
        scene_id=action.scene_id,
        presentation_mode=_enum_value(action.presentation_mode),
        claim_id=action.claim_id,
        evidence_clue_ids=list(action.evidence_clue_ids),
        subject_type=_enum_value(action.subject_type),
        subject_id=action.subject_id,
        text=action.text,
    )


def _project_npc_profile(context: AgentContext) -> LLMProviderNpcProfile | None:
    profile = context.target_profile
    if profile is None:
        return None
    return LLMProviderNpcProfile.model_validate(profile.model_dump(mode="json"))


def _project_relationship(
    relationship: RelationshipState | None,
) -> LLMProviderRelationship | None:
    if relationship is None:
        return None
    return LLMProviderRelationship.model_validate(relationship.model_dump(mode="json"))


def _project_player_knowledge(
    item: PlayerKnowledgeState,
) -> LLMProviderPlayerKnowledge:
    return LLMProviderPlayerKnowledge(
        knowledge_id=item.knowledge_id,
        clue_id=item.clue_id,
        world_info_id=item.world_info_id,
        confidence=item.confidence,
        acquisition=item.acquisition.value,
        source_type=item.source_type.value,
        title=item.title,
        summary=item.summary,
    )


def _project_memory(memory: AgentMemorySnapshot) -> LLMProviderMemory:
    return LLMProviderMemory(
        memory_id=memory.memory_id,
        memory_type=memory.memory_type,
        memory_scope=memory.memory_scope,
        memory_layer=memory.memory_layer,
        subject_id=memory.subject_id,
        owner_character_id=memory.owner_character_id,
        content=memory.content,
        confidence=memory.confidence,
        metadata=_project_memory_metadata(memory.metadata),
    )


def _project_memory_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in PROVIDER_MEMORY_METADATA_KEYS and _is_json_scalar_or_list(value)
    }


def _is_json_scalar_or_list(value: Any) -> bool:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(item is None or isinstance(item, str | int | float | bool) for item in value)
    return False


def _project_recent_event(event: WorldEvent) -> LLMProviderRecentEvent:
    return LLMProviderRecentEvent(
        id=event.id,
        type=event.type.value,
        actor_id=event.actor_id,
        safe_summary=_safe_event_summary(event),
    )


def _safe_event_summary(event: WorldEvent) -> str:
    event_type = event.type.value
    normalized = event_type.replace(".", " ")
    return f"A recent {normalized} event occurred."


def _project_private_context(
    inner_context: CharacterInnerContext | None,
) -> LLMProviderPrivateContext | None:
    if inner_context is None:
        return None
    return LLMProviderPrivateContext(
        character_id=inner_context.character_id,
        self_knowledge=[
            _project_self_knowledge(item)
            for item in [
                *inner_context.inner_goals,
                *inner_context.inner_secrets,
                *inner_context.inner_knowledge,
            ]
        ],
        fact_awareness=[
            _project_fact_awareness(item) for item in inner_context.fact_awareness
        ],
        disclosure_strategies=[
            _project_disclosure_strategy(strategy)
            for strategy in inner_context.fact_disclosure_strategies
        ],
        portraits=[
            _project_portrait_summary(portrait)
            for portrait in inner_context.inner_portraits
        ],
    )


def _project_self_knowledge(item: SelfKnowledgeItem) -> LLMProviderSelfKnowledge:
    return LLMProviderSelfKnowledge(
        id=item.id,
        kind=item.kind,
        summary=item.summary,
        priority=item.priority.value,
        related_clue_ids=list(item.related_clue_ids),
        related_world_info_ids=list(item.related_world_info_ids),
        tags=list(item.tags),
        allowed_modes=[mode.value for mode in item.disclosure_policy.allowed_modes],
        direct_reveal_allowed=item.disclosure_policy.direct_reveal_allowed,
        direct_quote_allowed=item.disclosure_policy.direct_quote_allowed,
    )


def _project_fact_awareness(
    item: CharacterFactAwarenessState,
) -> LLMProviderFactAwareness:
    return LLMProviderFactAwareness(
        world_info_id=item.world_info_id,
        stance=item.stance.value,
        confidence=item.confidence,
        source_type=item.source_type.value,
        evidence_clue_ids=list(item.evidence_clue_ids),
    )


def _project_disclosure_strategy(
    strategy: FactDisclosureStrategy,
) -> LLMProviderDisclosureStrategy:
    return LLMProviderDisclosureStrategy(
        world_info_id=strategy.world_info_id,
        stance=strategy.stance.value,
        allowed_modes=[mode.value for mode in strategy.allowed_modes],
        forbidden_modes=[mode.value for mode in strategy.forbidden_modes],
        rhetoric_tactics=[tactic.value for tactic in strategy.rhetoric_tactics],
        must_not_claim=list(strategy.must_not_claim),
        safe_fact_refs=list(strategy.safe_fact_refs),
        evidence_clue_ids=list(strategy.evidence_clue_ids),
        confidence=strategy.confidence,
    )


def _project_portrait_summary(
    portrait: CharacterImpression,
) -> LLMProviderPortraitSummary:
    return LLMProviderPortraitSummary(
        target_id=portrait.target_id,
        trust=portrait.trust,
        suspicion=portrait.suspicion,
        fear=portrait.fear,
        personality_impression=portrait.personality_impression,
        perceived_motive=portrait.perceived_motive,
        suspicious_points=list(portrait.suspicious_points),
        trust_boundary=portrait.trust_boundary,
        threat_level=portrait.threat_level,
        manipulation_risk=portrait.manipulation_risk,
        usefulness=portrait.usefulness,
        tags=list(portrait.tags),
        confidence=portrait.confidence,
    )


def _project_safe_facts(
    constraints: list[LLMDisclosureConstraint],
) -> list[LLMProviderSafeFact]:
    safe_facts: list[LLMProviderSafeFact] = []
    seen_refs: set[str] = set()
    for constraint in constraints:
        for fragment in constraint.safe_fragments:
            if fragment.ref in seen_refs:
                continue
            safe_facts.append(_project_safe_fact(fragment))
            seen_refs.add(fragment.ref)
    return safe_facts


def _project_safe_fact(fragment: SafeFactFragmentProjection) -> LLMProviderSafeFact:
    return LLMProviderSafeFact(
        world_info_id=fragment.world_info_id,
        fragment_id=fragment.fragment_id,
        ref=fragment.ref,
        summary=fragment.summary,
        aliases=list(fragment.aliases),
        claim_patterns=list(fragment.claim_patterns),
        allowed_modes=[mode.value for mode in fragment.allowed_modes],
        source_refs=list(fragment.source_refs),
    )


def _project_disclosure_limit(
    constraint: LLMDisclosureConstraint,
) -> LLMProviderDisclosureLimit:
    return LLMProviderDisclosureLimit(
        item_id=constraint.item_id,
        item_kind=constraint.item_kind,
        allowed_modes=[mode.value for mode in constraint.allowed_modes],
        forbidden_modes=[mode.value for mode in constraint.forbidden_modes],
        direct_reveal_allowed=constraint.direct_reveal_allowed,
        direct_quote_allowed=constraint.direct_quote_allowed,
        related_clue_ids=list(constraint.related_clue_ids),
        related_world_info_ids=list(constraint.related_world_info_ids),
        rhetoric_tactics=[tactic.value for tactic in constraint.rhetoric_tactics],
        must_not_claim=list(constraint.must_not_claim),
        safe_fact_refs=list(constraint.safe_fact_refs),
        blocked=constraint.blocked,
    )


def _project_output_limits(
    output_contract: LLMAgentOutputContract,
) -> LLMProviderOutputLimits:
    return LLMProviderOutputLimits(
        allowed_top_level_keys=list(output_contract.allowed_top_level_keys),
        allowed_intents=[intent.value for intent in output_contract.allowed_intents],
        fallback_intent=output_contract.fallback_intent.value,
        allowed_proposed_action_types=[
            action_type.value
            for action_type in output_contract.allowed_proposed_action_types
        ],
        allowed_disclosure_modes=[
            mode.value for mode in output_contract.allowed_disclosure_modes
        ],
        allowed_rhetoric_tactics=[
            tactic.value for tactic in output_contract.allowed_rhetoric_tactics
        ],
        max_relationship_delta=dict(output_contract.max_relationship_delta),
        disclosure_claim_required_for_world_info_touch=(
            output_contract.disclosure_claim_required_for_world_info_touch
        ),
        unknown_world_info_policy=output_contract.unknown_world_info_policy,
    )


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return str(value)
