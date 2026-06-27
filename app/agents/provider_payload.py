from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field

from app.domain.models import (
    AgentContext,
    AgentMemorySnapshot,
    APIModel,
    CharacterFactAwarenessState,
    CharacterInnerContext,
    DisclosureMode,
    FactDisclosureStrategy,
    LLMAgentContractInput,
    LLMAgentOutputContract,
    LLMDisclosureConstraint,
    NpcSkillProjection,
    PlayerAction,
    PlayerKnowledgeState,
    RelationshipState,
    SafeFactFragmentProjection,
    SelfKnowledgeItem,
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
        "non_authoritative",
        "scene_id",
        "world_info_id",
        "authority",
    }
)
DEFAULT_TEXT_LIMITS = {
    "npc_profile": 180,
    "player_knowledge": 220,
    "memory": 220,
    "self_knowledge": 180,
    "safe_fact": 180,
}
COMPRESSED_TEXT_LIMITS = {
    "npc_profile": 80,
    "player_knowledge": 120,
    "memory": 96,
    "self_knowledge": 96,
    "safe_fact": 120,
}


@dataclass
class _ProviderPayloadScope:
    clue_ids: set[str] = field(default_factory=set)
    world_info_ids: set[str] = field(default_factory=set)
    fact_world_info_ids: set[str] = field(default_factory=set)
    safe_fragment_refs: set[str] = field(default_factory=set)
    item_ids: set[str] = field(default_factory=set)


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
    memory_layer: str
    subject_id: str | None = None
    owner_character_id: str | None = None
    summary: str
    salience: float = 0.0
    confidence: float
    anchors: dict[str, Any] = Field(default_factory=dict)


class LLMProviderSelfKnowledge(APIModel):
    id: str
    kind: Literal["goal", "secret", "knowledge"]
    summary: str
    priority: str
    allowed_modes: list[str] = Field(default_factory=list)
    direct_reveal_allowed: bool = False
    direct_quote_allowed: bool = False


class LLMProviderFactAwareness(APIModel):
    world_info_id: str
    stance: str
    confidence: float


class LLMProviderDisclosureStrategy(APIModel):
    world_info_id: str
    stance: str
    allowed_modes: list[str] = Field(default_factory=list)
    rhetoric_tactics: list[str] = Field(default_factory=list)


class LLMProviderPrivateContext(APIModel):
    character_id: str
    self_knowledge: list[LLMProviderSelfKnowledge] = Field(default_factory=list)
    fact_awareness: list[LLMProviderFactAwareness] = Field(default_factory=list)
    disclosure_strategies: list[LLMProviderDisclosureStrategy] = Field(default_factory=list)


class LLMProviderSafeFact(APIModel):
    world_info_id: str
    fragment_id: str
    ref: str
    summary: str
    allowed_modes: list[str] = Field(default_factory=list)


class LLMProviderDisclosureLimit(APIModel):
    item_id: str
    item_kind: str
    allowed_modes: list[str] = Field(default_factory=list)
    direct_reveal_allowed: bool = False
    direct_quote_allowed: bool = False
    blocked: bool = True


class LLMProviderSkill(APIModel):
    skill_id: str
    type: str
    allowed_intents: list[str] = Field(default_factory=list)
    allowed_tactics: list[str] = Field(default_factory=list)
    max_disclosure_mode_by_world_info: dict[str, str] = Field(default_factory=dict)
    safe_fragment_refs: list[str] = Field(default_factory=list)
    allowed_proposed_actions: list[str] = Field(default_factory=list)


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
    private_context: LLMProviderPrivateContext | None = None
    safe_facts: list[LLMProviderSafeFact] = Field(default_factory=list)
    disclosure_limits: list[LLMProviderDisclosureLimit] = Field(default_factory=list)
    npc_skills: list[LLMProviderSkill] = Field(default_factory=list)
    output_limits: LLMProviderOutputLimits


def build_llm_provider_turn_payload(
    contract_input: LLMAgentContractInput,
) -> LLMProviderTurnPayload:
    context = contract_input.agent_context
    text_limits = _provider_text_limits(context)
    scope = _build_provider_payload_scope(contract_input)
    self_knowledge_ids: set[str] = set()
    relevant_player_knowledge = _filter_relevant_player_knowledge(
        context,
        disclosure_constraints=contract_input.disclosure_constraints,
    )
    return LLMProviderTurnPayload(
        turn=_project_turn(context),
        npc=_project_npc_profile(context, text_limits=text_limits),
        relationship_to_player=_project_relationship(context.relationship_to_player),
        player_knowledge=[
            _project_player_knowledge(item, text_limits=text_limits)
            for item in relevant_player_knowledge
        ],
        memories=[
            _project_memory(memory, text_limits=text_limits)
            for memory in context.memory_snapshots
        ],
        private_context=None,
        safe_facts=_project_safe_facts(
            contract_input.disclosure_constraints,
            scope=scope,
            output_contract=contract_input.output_contract,
            text_limits=text_limits,
        ),
        disclosure_limits=[
            _project_disclosure_limit(
                constraint,
                output_contract=contract_input.output_contract,
            )
            for constraint in contract_input.disclosure_constraints
            if _disclosure_constraint_in_scope(
                constraint,
                scope=scope,
                self_knowledge_ids=self_knowledge_ids,
            )
        ],
        npc_skills=[_project_skill(skill) for skill in context.npc_skill_projections],
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


def _project_npc_profile(
    context: AgentContext,
    *,
    text_limits: dict[str, int],
) -> LLMProviderNpcProfile | None:
    profile = context.target_profile
    if profile is None:
        return None
    return LLMProviderNpcProfile(
        id=profile.id,
        display_name=profile.display_name,
        public_role=profile.public_role,
        public_description=_compact_text(
            profile.public_description,
            limit=text_limits["npc_profile"],
        ),
        speech_style=_compact_text(profile.speech_style, limit=text_limits["npc_profile"]),
        default_tone=_compact_text(profile.default_tone, limit=text_limits["npc_profile"]),
        catchphrases=[
            _compact_text(item, limit=40) for item in profile.catchphrases[:3]
        ],
        visible_traits=[
            _compact_text(item, limit=40) for item in profile.visible_traits[:5]
        ],
        defensive_style=profile.defensive_style.value,
        pressure_response=profile.pressure_response.value,
        trust_response=profile.trust_response.value,
        fear_response=profile.fear_response.value,
    )


def _project_relationship(
    relationship: RelationshipState | None,
) -> LLMProviderRelationship | None:
    if relationship is None:
        return None
    return LLMProviderRelationship.model_validate(relationship.model_dump(mode="json"))


def _project_player_knowledge(
    item: PlayerKnowledgeState,
    *,
    text_limits: dict[str, int],
) -> LLMProviderPlayerKnowledge:
    return LLMProviderPlayerKnowledge(
        knowledge_id=item.knowledge_id,
        clue_id=item.clue_id,
        world_info_id=item.world_info_id,
        confidence=item.confidence,
        acquisition=item.acquisition.value,
        source_type=item.source_type.value,
        title=_compact_text(item.title, limit=80),
        summary=_compact_text(item.summary, limit=text_limits["player_knowledge"]),
    )


def _filter_relevant_player_knowledge(
    context: AgentContext,
    *,
    disclosure_constraints: list[LLMDisclosureConstraint],
) -> list[PlayerKnowledgeState]:
    clue_ids, world_info_ids, generic_ids = _player_knowledge_relevance_anchors(
        context,
        disclosure_constraints=disclosure_constraints,
    )
    return [
        item
        for item in context.player_knowledge
        if _player_knowledge_matches(
            item,
            clue_ids=clue_ids,
            world_info_ids=world_info_ids,
            generic_ids=generic_ids,
        )
    ]


def _player_knowledge_relevance_anchors(
    context: AgentContext,
    *,
    disclosure_constraints: list[LLMDisclosureConstraint],
) -> tuple[set[str], set[str], set[str]]:
    clue_ids: set[str] = set()
    world_info_ids: set[str] = set()
    generic_ids: set[str] = set()

    action = context.player_action
    _add_string_anchor(action.clue_id, clue_ids, generic_ids)
    _add_string_anchor(action.claim_id, world_info_ids, generic_ids)
    _add_string_anchors(action.evidence_clue_ids, clue_ids, generic_ids)

    if action.subject_id:
        generic_ids.add(action.subject_id)
        if _enum_value(action.subject_type) == "clue":
            clue_ids.add(action.subject_id)

    for memory in context.memory_snapshots:
        metadata = memory.metadata
        _add_string_anchor(_metadata_string(metadata, "clue_id"), clue_ids, generic_ids)
        _add_string_anchor(
            _metadata_string(metadata, "world_info_id"),
            world_info_ids,
            generic_ids,
        )
        _add_string_anchors(
            _metadata_string_list(metadata, "adjacent_clue_ids"),
            clue_ids,
            generic_ids,
        )
        _add_string_anchors(
            _metadata_string_list(metadata, "topic_tags"),
            generic_ids,
        )

    for constraint in disclosure_constraints:
        _add_string_anchors(constraint.related_clue_ids, clue_ids, generic_ids)
        _add_string_anchors(
            constraint.related_world_info_ids,
            world_info_ids,
            generic_ids,
        )
        if constraint.item_kind == "world_info":
            _add_string_anchor(constraint.item_id, world_info_ids, generic_ids)
        for fragment in constraint.safe_fragments:
            _add_string_anchor(fragment.world_info_id, world_info_ids, generic_ids)

    return clue_ids, world_info_ids, generic_ids


def _player_knowledge_matches(
    item: PlayerKnowledgeState,
    *,
    clue_ids: set[str],
    world_info_ids: set[str],
    generic_ids: set[str],
) -> bool:
    if item.knowledge_id in generic_ids:
        return True
    if item.clue_id and (item.clue_id in clue_ids or item.clue_id in generic_ids):
        return True
    return bool(
        item.world_info_id
        and (item.world_info_id in world_info_ids or item.world_info_id in generic_ids)
    )


def _build_provider_payload_scope(
    contract_input: LLMAgentContractInput,
) -> _ProviderPayloadScope:
    context = contract_input.agent_context
    scope = _ProviderPayloadScope()

    _add_action_scope_anchors(scope, context)
    for memory in context.memory_snapshots:
        _add_memory_scope_anchors(scope, memory.metadata)
    _add_skill_scope_anchors(scope, context)
    _add_player_knowledge_scope_anchors(scope, context)
    _add_authorized_safe_fragment_scope(
        scope,
        context,
        disclosure_constraints=contract_input.disclosure_constraints,
    )
    scope.fact_world_info_ids.update(scope.world_info_ids)
    return scope


def _add_action_scope_anchors(
    scope: _ProviderPayloadScope,
    context: AgentContext,
) -> None:
    action = context.player_action
    _add_id(action.clue_id, scope.clue_ids, scope.item_ids)
    _add_id(context.presented_clue_id, scope.clue_ids, scope.item_ids)
    _add_id(context.presented_knowledge_id, scope.item_ids)
    _add_id(action.claim_id, scope.world_info_ids, scope.fact_world_info_ids, scope.item_ids)
    _add_ids(action.evidence_clue_ids, scope.clue_ids, scope.item_ids)

    _add_subject_scope_anchor(scope, _enum_value(action.subject_type), action.subject_id)
    _add_subject_scope_anchor(
        scope,
        _enum_value(context.asked_subject_type),
        context.asked_subject_id,
    )


def _add_subject_scope_anchor(
    scope: _ProviderPayloadScope,
    subject_type: str | None,
    subject_id: str | None,
) -> None:
    if not subject_id:
        return
    scope.item_ids.add(subject_id)
    if subject_type == "clue":
        scope.clue_ids.add(subject_id)


def _add_memory_scope_anchors(
    scope: _ProviderPayloadScope,
    metadata: dict[str, Any],
) -> None:
    _add_id(_metadata_string(metadata, "clue_id"), scope.clue_ids, scope.item_ids)
    _add_ids(
        _metadata_string_list(metadata, "adjacent_clue_ids"),
        scope.clue_ids,
        scope.item_ids,
    )
    _add_id(
        _metadata_string(metadata, "world_info_id"),
        scope.world_info_ids,
        scope.fact_world_info_ids,
        scope.item_ids,
    )
    _add_id(
        _metadata_string(metadata, "claim_id"),
        scope.world_info_ids,
        scope.fact_world_info_ids,
        scope.item_ids,
    )
    _add_id(_metadata_string(metadata, "key_clue"), scope.clue_ids, scope.item_ids)
    _add_id(_metadata_string(metadata, "belief_subject"), scope.item_ids)


def _add_skill_scope_anchors(
    scope: _ProviderPayloadScope,
    context: AgentContext,
) -> None:
    for skill in context.npc_skill_projections:
        for ref in skill.safe_fragment_refs:
            _add_id(ref, scope.safe_fragment_refs, scope.item_ids)
            _add_id(
                _world_info_id_from_safe_fragment_ref(ref),
                scope.world_info_ids,
                scope.fact_world_info_ids,
                scope.item_ids,
            )
        for world_info_id in skill.max_disclosure_mode_by_world_info:
            _add_id(
                world_info_id,
                scope.world_info_ids,
                scope.fact_world_info_ids,
                scope.item_ids,
            )


def _add_player_knowledge_scope_anchors(
    scope: _ProviderPayloadScope,
    context: AgentContext,
) -> None:
    anchored_clue_ids = set(scope.clue_ids)
    anchored_world_info_ids = set(scope.world_info_ids)
    anchored_item_ids = set(scope.item_ids)
    if context.presented_knowledge_id:
        anchored_item_ids.add(context.presented_knowledge_id)

    for item in context.player_knowledge:
        if not _player_knowledge_matches(
            item,
            clue_ids=anchored_clue_ids,
            world_info_ids=anchored_world_info_ids,
            generic_ids=anchored_item_ids,
        ):
            continue
        _add_id(item.knowledge_id, scope.item_ids)
        _add_id(item.clue_id, scope.clue_ids, scope.item_ids)
        _add_id(
            item.world_info_id,
            scope.world_info_ids,
            scope.fact_world_info_ids,
            scope.item_ids,
        )


def _add_authorized_safe_fragment_scope(
    scope: _ProviderPayloadScope,
    context: AgentContext,
    *,
    disclosure_constraints: list[LLMDisclosureConstraint],
) -> None:
    safe_fragments = list(context.director_safe_fragments)
    if not safe_fragments:
        safe_fragments = [
            fragment
            for constraint in disclosure_constraints
            for fragment in constraint.safe_fragments
        ]
    for fragment in safe_fragments:
        _add_id(fragment.ref, scope.safe_fragment_refs, scope.item_ids)
        _add_id(
            fragment.world_info_id,
            scope.fact_world_info_ids,
            scope.item_ids,
        )


def _add_id(value: str | None, *targets: set[str]) -> None:
    if not value:
        return
    for target in targets:
        target.add(value)


def _add_ids(values: list[str], *targets: set[str]) -> None:
    for value in values:
        _add_id(value, *targets)


def _world_info_id_from_safe_fragment_ref(ref: str) -> str | None:
    if ".safe_fragment:" not in ref:
        return None
    world_info_id, _ = ref.split(".safe_fragment:", 1)
    return world_info_id or None


def _add_string_anchor(
    value: str | None,
    primary: set[str],
    generic: set[str],
) -> None:
    if not value:
        return
    primary.add(value)
    generic.add(value)


def _add_string_anchors(
    values: list[str],
    primary: set[str],
    generic: set[str] | None = None,
) -> None:
    for value in values:
        if not value:
            continue
        primary.add(value)
        if generic is not None:
            generic.add(value)


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _metadata_string_list(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _project_memory(
    memory: AgentMemorySnapshot,
    *,
    text_limits: dict[str, int],
) -> LLMProviderMemory:
    return LLMProviderMemory(
        memory_id=memory.memory_id,
        memory_type=memory.memory_type,
        memory_layer=memory.memory_layer,
        subject_id=memory.subject_id,
        owner_character_id=memory.owner_character_id,
        summary=_compact_text(memory.content, limit=text_limits["memory"]),
        salience=memory.salience,
        confidence=memory.confidence,
        anchors=_project_memory_metadata(memory.metadata),
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


def _project_private_context(
    inner_context: CharacterInnerContext | None,
    *,
    scope: _ProviderPayloadScope,
    self_knowledge_ids: set[str],
    disclosure_constraints: list[LLMDisclosureConstraint],
    output_contract: LLMAgentOutputContract,
    text_limits: dict[str, int],
) -> LLMProviderPrivateContext | None:
    if inner_context is None:
        return None
    constraints_by_item = _disclosure_constraints_by_item(disclosure_constraints)
    return LLMProviderPrivateContext(
        character_id=inner_context.character_id,
        self_knowledge=[
            _project_self_knowledge(
                item,
                output_contract=output_contract,
                constraint=_constraint_for_self_knowledge(
                    item,
                    constraints_by_item=constraints_by_item,
                ),
                text_limits=text_limits,
            )
            for item in [
                *inner_context.inner_goals,
                *inner_context.inner_secrets,
                *inner_context.inner_knowledge,
            ]
            if item.id in self_knowledge_ids
        ],
        fact_awareness=[
            _project_fact_awareness(item)
            for item in inner_context.fact_awareness
            if _fact_awareness_in_scope(item, scope)
        ],
        disclosure_strategies=[
            _project_disclosure_strategy(
                strategy,
                output_contract=output_contract,
                constraint=constraints_by_item.get(("world_info", strategy.world_info_id)),
            )
            for strategy in inner_context.fact_disclosure_strategies
            if _disclosure_strategy_in_scope(strategy, scope)
        ],
    )


def _scoped_self_knowledge_ids(
    inner_context: CharacterInnerContext | None,
    scope: _ProviderPayloadScope,
) -> set[str]:
    if inner_context is None:
        return set()
    return {
        item.id
        for item in [
            *inner_context.inner_goals,
            *inner_context.inner_secrets,
            *inner_context.inner_knowledge,
        ]
        if _self_knowledge_in_scope(item, scope)
    }


def _self_knowledge_in_scope(
    item: SelfKnowledgeItem,
    scope: _ProviderPayloadScope,
) -> bool:
    if item.id in scope.item_ids:
        return True
    if set(item.related_clue_ids) & scope.clue_ids:
        return True
    if set(item.related_world_info_ids) & scope.world_info_ids:
        return True
    return False


def _fact_awareness_in_scope(
    item: CharacterFactAwarenessState,
    scope: _ProviderPayloadScope,
) -> bool:
    return item.world_info_id in scope.fact_world_info_ids or bool(
        set(item.evidence_clue_ids) & scope.clue_ids
    )


def _disclosure_strategy_in_scope(
    strategy: FactDisclosureStrategy,
    scope: _ProviderPayloadScope,
) -> bool:
    if strategy.world_info_id in scope.fact_world_info_ids:
        return True
    if set(strategy.evidence_clue_ids) & scope.clue_ids:
        return True
    return bool(
        set(strategy.safe_fact_refs)
        & (scope.safe_fragment_refs | scope.clue_ids | scope.item_ids)
    )


def _disclosure_constraints_by_item(
    constraints: list[LLMDisclosureConstraint],
) -> dict[tuple[str, str], LLMDisclosureConstraint]:
    return {
        (constraint.item_kind, constraint.item_id): constraint
        for constraint in constraints
    }


def _constraint_for_self_knowledge(
    item: SelfKnowledgeItem,
    *,
    constraints_by_item: dict[tuple[str, str], LLMDisclosureConstraint],
) -> LLMDisclosureConstraint | None:
    return constraints_by_item.get((item.kind, item.id))


def _project_self_knowledge(
    item: SelfKnowledgeItem,
    *,
    output_contract: LLMAgentOutputContract,
    constraint: LLMDisclosureConstraint | None = None,
    text_limits: dict[str, int],
) -> LLMProviderSelfKnowledge:
    allowed_modes = (
        constraint.allowed_modes
        if constraint is not None
        else item.disclosure_policy.allowed_modes
    )
    forbidden_modes = constraint.forbidden_modes if constraint is not None else []
    return LLMProviderSelfKnowledge(
        id=item.id,
        kind=item.kind,
        summary=_compact_text(item.summary, limit=text_limits["self_knowledge"]),
        priority=item.priority.value,
        allowed_modes=_project_allowed_modes(
            allowed_modes,
            output_contract=output_contract,
            forbidden_modes=forbidden_modes,
        ),
        direct_reveal_allowed=(
            constraint.direct_reveal_allowed
            if constraint is not None
            else item.disclosure_policy.direct_reveal_allowed
        ),
        direct_quote_allowed=(
            constraint.direct_quote_allowed
            if constraint is not None
            else item.disclosure_policy.direct_quote_allowed
        ),
    )


def _project_fact_awareness(
    item: CharacterFactAwarenessState,
) -> LLMProviderFactAwareness:
    return LLMProviderFactAwareness(
        world_info_id=item.world_info_id,
        stance=item.stance.value,
        confidence=item.confidence,
    )


def _project_disclosure_strategy(
    strategy: FactDisclosureStrategy,
    *,
    output_contract: LLMAgentOutputContract,
    constraint: LLMDisclosureConstraint | None = None,
) -> LLMProviderDisclosureStrategy:
    allowed_modes = constraint.allowed_modes if constraint is not None else strategy.allowed_modes
    forbidden_modes = (
        constraint.forbidden_modes if constraint is not None else strategy.forbidden_modes
    )
    return LLMProviderDisclosureStrategy(
        world_info_id=strategy.world_info_id,
        stance=strategy.stance.value,
        allowed_modes=_project_allowed_modes(
            allowed_modes,
            output_contract=output_contract,
            forbidden_modes=forbidden_modes,
        ),
        rhetoric_tactics=[tactic.value for tactic in strategy.rhetoric_tactics],
    )


def _project_safe_facts(
    constraints: list[LLMDisclosureConstraint],
    *,
    scope: _ProviderPayloadScope,
    output_contract: LLMAgentOutputContract,
    text_limits: dict[str, int],
) -> list[LLMProviderSafeFact]:
    safe_facts: list[LLMProviderSafeFact] = []
    seen_refs: set[str] = set()
    for constraint in constraints:
        for fragment in constraint.safe_fragments:
            if fragment.ref not in scope.safe_fragment_refs:
                continue
            if fragment.ref in seen_refs:
                continue
            safe_facts.append(
                _project_safe_fact(
                    fragment,
                    output_contract=output_contract,
                    constraint=constraint,
                    text_limits=text_limits,
                )
            )
            seen_refs.add(fragment.ref)
    return safe_facts


def _project_safe_fact(
    fragment: SafeFactFragmentProjection,
    *,
    output_contract: LLMAgentOutputContract,
    constraint: LLMDisclosureConstraint,
    text_limits: dict[str, int],
) -> LLMProviderSafeFact:
    return LLMProviderSafeFact(
        world_info_id=fragment.world_info_id,
        fragment_id=fragment.fragment_id,
        ref=fragment.ref,
        summary=_compact_text(fragment.summary, limit=text_limits["safe_fact"]),
        allowed_modes=_project_allowed_modes(
            fragment.allowed_modes,
            output_contract=output_contract,
            forbidden_modes=constraint.forbidden_modes,
        ),
    )


def _project_disclosure_limit(
    constraint: LLMDisclosureConstraint,
    *,
    output_contract: LLMAgentOutputContract,
) -> LLMProviderDisclosureLimit:
    return LLMProviderDisclosureLimit(
        item_id=constraint.item_id,
        item_kind=constraint.item_kind,
        allowed_modes=_project_allowed_modes(
            constraint.allowed_modes,
            output_contract=output_contract,
            forbidden_modes=constraint.forbidden_modes,
        ),
        direct_reveal_allowed=constraint.direct_reveal_allowed,
        direct_quote_allowed=constraint.direct_quote_allowed,
        blocked=constraint.blocked,
    )


def _project_skill(skill: NpcSkillProjection) -> LLMProviderSkill:
    return LLMProviderSkill(
        skill_id=skill.skill_id,
        type=skill.type.value,
        allowed_intents=[intent.value for intent in skill.allowed_intents],
        allowed_tactics=[tactic.value for tactic in skill.allowed_tactics],
        max_disclosure_mode_by_world_info={
            world_info_id: mode.value
            for world_info_id, mode in skill.max_disclosure_mode_by_world_info.items()
        },
        safe_fragment_refs=list(skill.safe_fragment_refs),
        allowed_proposed_actions=[
            action_type.value for action_type in skill.allowed_proposed_actions
        ],
    )


def _disclosure_constraint_in_scope(
    constraint: LLMDisclosureConstraint,
    *,
    scope: _ProviderPayloadScope,
    self_knowledge_ids: set[str],
) -> bool:
    if constraint.item_kind in {"goal", "secret", "knowledge"}:
        return constraint.item_id in self_knowledge_ids
    if constraint.item_kind == "world_info":
        return (
            constraint.item_id in scope.fact_world_info_ids
            or bool(set(constraint.related_clue_ids) & scope.clue_ids)
            or bool(set(constraint.related_world_info_ids) & scope.fact_world_info_ids)
            or any(
                fragment.ref in scope.safe_fragment_refs
                for fragment in constraint.safe_fragments
            )
            or bool(
                set(constraint.safe_fact_refs)
                & (scope.safe_fragment_refs | scope.clue_ids | scope.item_ids)
            )
        )
    if constraint.item_kind == "forbidden_fact":
        return False
    return False


def _project_allowed_modes(
    allowed_modes: list[DisclosureMode],
    *,
    output_contract: LLMAgentOutputContract,
    forbidden_modes: list[DisclosureMode],
) -> list[str]:
    output_allowed_modes = set(output_contract.allowed_disclosure_modes)
    forbidden = set(forbidden_modes)
    return [
        mode.value
        for mode in allowed_modes
        if mode != DisclosureMode.FULL
        and mode in output_allowed_modes
        and mode not in forbidden
    ]


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


def _provider_text_limits(context: AgentContext) -> dict[str, int]:
    return (
        COMPRESSED_TEXT_LIMITS
        if context.compressed_history is not None
        else DEFAULT_TEXT_LIMITS
    )


def _compact_text(value: str, *, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    if limit <= 3:
        return normalized[:limit]
    return normalized[: limit - 3].rstrip() + "..."
