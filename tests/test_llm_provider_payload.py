from __future__ import annotations

import json
from typing import Any

import httpx

from app.agents.llm_contract import build_llm_agent_input
from app.agents.provider_payload import build_llm_provider_payload
from app.agents.real_llm_agent import OpenAILLMAgent
from app.domain.models import (
    ActionType,
    AgentCharacterView,
    AgentContext,
    AgentIntentType,
    AgentMemorySnapshot,
    CharacterFactAwarenessSourceType,
    CharacterFactAwarenessState,
    CharacterFactStance,
    CharacterImpression,
    CharacterInnerContext,
    CharacterResponseStyle,
    DefensiveStyle,
    DisclosureMode,
    DisclosurePolicy,
    EventType,
    FactDisclosureStrategy,
    LLMAgentOutputContract,
    LLMDisclosureConstraint,
    MockReplyConfig,
    NpcSkillProjection,
    NpcSkillType,
    PlayerAction,
    PlayerKnowledgeAcquisition,
    PlayerKnowledgeSourceType,
    PlayerKnowledgeState,
    RelationshipState,
    RhetoricTactic,
    SafeFactFragmentProjection,
    SelfKnowledgeItem,
    SubjectType,
    WorldEvent,
)

AUDIT_FIELD_NAMES = [
    '"reply_options"',
    '"payload"',
    '"source_event_id"',
    '"source_event_ids"',
    '"source_memory_ids"',
    '"created_at"',
    '"updated_at"',
    '"last_updated_event_id"',
    '"rule_id"',
]


class _FakeOpenAIResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.request_url = "https://example.test"

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        request = httpx.Request("POST", self.request_url)
        response = httpx.Response(
            self.status_code,
            request=request,
            json=self._payload,
        )
        raise httpx.HTTPStatusError(
            f"HTTP status {self.status_code}",
            request=request,
            response=response,
        )

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeOpenAIClient:
    def __init__(self, responses: list[dict[str, Any]] | dict[str, Any]) -> None:
        raw_responses = responses if isinstance(responses, list) else [responses]
        self._responses = [_FakeOpenAIResponse(item) for item in raw_responses]
        self.request_payloads: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeOpenAIResponse:
        request_payload = kwargs.get("json")
        if isinstance(request_payload, dict):
            self.request_payloads.append(request_payload)
        response = self._responses.pop(0)
        response.request_url = url
        return response


def test_real_llm_provider_request_uses_compact_payload(monkeypatch: Any) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "responses")
    context = _build_context_with_audit_only_fields()
    contract_input = build_llm_agent_input(context)
    full_contract = contract_input.model_dump_json()
    client = _FakeOpenAIClient(
        {
            "output_text": json.dumps(
                {
                    "speech": "I can answer within the current limits.",
                    "intent": "answer",
                    "emotional_shift": {},
                    "proposed_actions": [],
                    "memory_refs": ["memory.selected"],
                    "disclosure_claims": [],
                }
            )
        }
    )

    OpenAILLMAgent(api_key="test-key", client=client).generate_strict(
        context,
        contract_input=contract_input,
    )

    assert "SHOULD_NOT_LEAK_REPLY_OPTIONS" in full_contract
    assert "SHOULD_NOT_LEAK_EVENT_PAYLOAD" in full_contract
    assert "source_event_ids" in full_contract
    assert client.request_payloads
    provider_payload = json.loads(
        client.request_payloads[0]["input"][0]["content"][0]["text"]
    )
    serialized = json.dumps(provider_payload, ensure_ascii=False)

    assert provider_payload["payload_kind"] == "llm_provider_turn.v1"
    assert provider_payload["turn"]["action"]["text"] == "Where were you?"
    assert "content" not in provider_payload["memories"][0]
    assert provider_payload["memories"][0]["summary"] == "Selected memory content."
    assert "recent_events" not in provider_payload
    assert "context_layers" not in provider_payload
    assert "SHOULD_NOT_LEAK_REPLY_OPTIONS" not in serialized
    assert "SHOULD_NOT_LEAK_EVENT_PAYLOAD" not in serialized
    assert "event.payload.secret" not in serialized
    assert "rule.secret" not in serialized
    for field_name in AUDIT_FIELD_NAMES:
        assert field_name not in serialized


def test_provider_payload_projects_memory_summary_instead_of_full_content() -> None:
    long_content = (
        "The NPC remembers only the safe beginning. "
        + ("detail " * 80)
        + "TRAILING_MEMORY_DETAIL_SHOULD_NOT_SEND"
    )
    base_context = _build_context_with_audit_only_fields()
    context = base_context.model_copy(
        update={
            "memory_snapshots": [
                base_context.memory_snapshots[0].model_copy(
                    update={
                        "content": long_content,
                        "salience": 0.7,
                        "metadata": {
                            "world_info_id": "door_was_locked",
                            "authority": "rule_verified",
                            "topic_tags": [
                                "SHOULD_NOT_SEND_PROVIDER_MEMORY_TOPIC_TAG"
                            ],
                        },
                    }
                )
            ]
        }
    )

    provider_payload = build_llm_provider_payload(build_llm_agent_input(context))
    memory_payload = provider_payload["memories"][0]
    serialized = json.dumps(provider_payload, ensure_ascii=False)

    assert "content" not in memory_payload
    assert memory_payload["summary"].startswith(
        "The NPC remembers only the safe beginning."
    )
    assert len(memory_payload["summary"]) <= 220
    assert memory_payload["summary"].endswith("...")
    assert memory_payload["salience"] == 0.7
    assert memory_payload["anchors"] == {
        "world_info_id": "door_was_locked",
        "authority": "rule_verified",
    }
    assert "TRAILING_MEMORY_DETAIL_SHOULD_NOT_SEND" not in serialized
    assert "SHOULD_NOT_SEND_PROVIDER_MEMORY_TOPIC_TAG" not in serialized


def test_schema_repair_request_reuses_compact_provider_payload(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    context = _build_context_with_audit_only_fields()
    contract_input = build_llm_agent_input(context)
    client = _FakeOpenAIClient(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "intent": "answer",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [],
                                }
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I can answer safely now.",
                                    "intent": "answer",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [],
                                }
                            )
                        }
                    }
                ]
            },
        ]
    )

    OpenAILLMAgent(
        api_key="test-key",
        client=client,
        schema_repair_attempts=1,
    ).generate_strict(
        context,
        contract_input=contract_input,
    )

    assert len(client.request_payloads) == 2
    repair_request = client.request_payloads[1]
    provider_payload = json.loads(repair_request["messages"][1]["content"])
    serialized_repair_request = json.dumps(repair_request, ensure_ascii=False)

    assert provider_payload["payload_kind"] == "llm_provider_turn.v1"
    assert "Schema repair required" in repair_request["messages"][-1]["content"]
    assert "SHOULD_NOT_LEAK_REPLY_OPTIONS" not in serialized_repair_request
    assert "SHOULD_NOT_LEAK_EVENT_PAYLOAD" not in serialized_repair_request
    assert "event.payload.secret" not in serialized_repair_request
    assert "rule.secret" not in serialized_repair_request
    for field_name in AUDIT_FIELD_NAMES:
        assert field_name not in serialized_repair_request


def test_provider_payload_filters_player_knowledge_by_relevance_anchors() -> None:
    action = PlayerAction(
        type=ActionType.ACCUSE,
        target_id="npc",
        claim_id="claim.hidden_mechanism",
        evidence_clue_ids=["evidence_clue"],
        text="This chain fits the hidden mechanism.",
    )
    context = AgentContext(
        case_id="case",
        session_id="session",
        target_agent_id="npc",
        current_phase="reconstruction",
        player_action=action,
        player_knowledge=[
            _knowledge(
                "knowledge.claim",
                world_info_id="claim.hidden_mechanism",
                summary="Claim-relevant player knowledge.",
            ),
            _knowledge(
                "knowledge.evidence",
                clue_id="evidence_clue",
                summary="Evidence clue player knowledge.",
            ),
            _knowledge(
                "knowledge.memory_clue",
                clue_id="memory_clue",
                summary="Selected memory clue player knowledge.",
            ),
            _knowledge(
                "knowledge.memory_world",
                world_info_id="memory_world",
                summary="Selected memory world info player knowledge.",
            ),
            _knowledge(
                "knowledge.memory_adjacent",
                clue_id="adjacent_clue",
                summary="Adjacent clue player knowledge.",
            ),
            _knowledge(
                "knowledge.memory_topic",
                clue_id="topic_tag_clue",
                summary="Topic-tagged player knowledge.",
            ),
            _knowledge(
                "knowledge.constraint_clue",
                clue_id="constraint_clue",
                summary="Disclosure constraint clue player knowledge.",
            ),
            _knowledge(
                "knowledge.constraint_world",
                world_info_id="constraint_world",
                summary="Disclosure constraint world info player knowledge.",
            ),
            _knowledge(
                "knowledge.safe_world",
                world_info_id="safe_world",
                summary="Safe fragment world info player knowledge.",
            ),
            _knowledge(
                "knowledge.unrelated",
                clue_id="unrelated_clue",
                world_info_id="unrelated_world",
                summary="SHOULD_NOT_SEND_UNRELATED_PLAYER_KNOWLEDGE",
            ),
        ],
        memory_snapshots=[
            AgentMemorySnapshot(
                memory_id="memory.selected",
                memory_type="episodic",
                memory_scope="npc_private",
                memory_layer="working",
                subject_id="player",
                owner_character_id="npc",
                content="Selected relevant memory.",
                confidence=0.9,
                metadata={
                    "clue_id": "memory_clue",
                    "world_info_id": "memory_world",
                    "adjacent_clue_ids": ["adjacent_clue"],
                    "topic_tags": ["topic_tag_clue"],
                },
                last_updated_event_id="memory.updated",
            )
        ],
        director_safe_fragments=[
            SafeFactFragmentProjection(
                world_info_id="safe_world",
                fragment_id="safe_fragment",
                ref="safe_world.safe_fragment",
                summary="Only this safe fragment is revealable.",
                allowed_modes=[DisclosureMode.HINT],
            )
        ],
    )
    contract_input = build_llm_agent_input(context)
    contract_input = contract_input.model_copy(
        update={
            "disclosure_constraints": [
                *contract_input.disclosure_constraints,
                LLMDisclosureConstraint(
                    item_id="constraint_world",
                    item_kind="world_info",
                    related_clue_ids=["constraint_clue"],
                    related_world_info_ids=["constraint_world"],
                    allowed_modes=[DisclosureMode.HINT],
                    forbidden_modes=[DisclosureMode.FULL],
                    blocked=False,
                ),
            ]
        }
    )

    provider_payload = build_llm_provider_payload(contract_input)
    knowledge_ids = [
        item["knowledge_id"] for item in provider_payload["player_knowledge"]
    ]
    serialized = json.dumps(provider_payload, ensure_ascii=False)

    assert knowledge_ids == [
        "knowledge.claim",
        "knowledge.evidence",
        "knowledge.memory_clue",
        "knowledge.memory_world",
        "knowledge.memory_adjacent",
        "knowledge.memory_topic",
        "knowledge.constraint_clue",
        "knowledge.constraint_world",
        "knowledge.safe_world",
    ]
    assert provider_payload["safe_facts"][0]["world_info_id"] == "safe_world"
    assert "context_layers" not in provider_payload
    assert "knowledge.unrelated" not in serialized
    assert "SHOULD_NOT_SEND_UNRELATED_PLAYER_KNOWLEDGE" not in serialized


def test_provider_payload_keeps_player_knowledge_for_ask_about_clue_subject() -> None:
    context = AgentContext(
        case_id="case",
        session_id="session",
        target_agent_id="npc",
        current_phase="investigation",
        player_action=PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id="npc",
            subject_type=SubjectType.CLUE,
            subject_id="subject_clue",
            text="What do you know about this clue?",
        ),
        player_knowledge=[
            _knowledge(
                "knowledge.subject",
                clue_id="subject_clue",
                summary="Subject clue player knowledge.",
            ),
            _knowledge(
                "knowledge.unrelated_subject",
                clue_id="other_clue",
                summary="SHOULD_NOT_SEND_UNRELATED_SUBJECT_KNOWLEDGE",
            ),
        ],
    )

    provider_payload = build_llm_provider_payload(build_llm_agent_input(context))
    serialized = json.dumps(provider_payload, ensure_ascii=False)

    assert [
        item["knowledge_id"] for item in provider_payload["player_knowledge"]
    ] == ["knowledge.subject"]
    assert "SHOULD_NOT_SEND_UNRELATED_SUBJECT_KNOWLEDGE" not in serialized


def test_provider_payload_scopes_private_context_and_disclosure_limits() -> None:
    context = _build_context_with_private_scope_edges()
    contract_input = build_llm_agent_input(context).model_copy(
        update={
            "output_contract": LLMAgentOutputContract(
                allowed_intents=[AgentIntentType.ANSWER],
                fallback_intent=AgentIntentType.ANSWER,
                allowed_disclosure_modes=[DisclosureMode.HINT],
            )
        }
    )

    provider_payload = build_llm_provider_payload(contract_input)
    serialized = json.dumps(provider_payload, ensure_ascii=False)

    assert "private_context" not in provider_payload
    assert {
        item["ref"] for item in provider_payload["safe_facts"]
    } == {
        "world_focus.safe_fragment:focus",
        "world_skill.safe_fragment:skill",
    }
    assert all(
        item["allowed_modes"] == ["hint"]
        for item in [
            *provider_payload["safe_facts"],
            *provider_payload["disclosure_limits"],
        ]
    )
    assert provider_payload["output_limits"]["allowed_disclosure_modes"] == ["hint"]
    assert "portrait_summary" not in provider_payload
    assert "self_knowledge" not in serialized
    assert "fact_awareness" not in serialized
    assert "disclosure_strategies" not in serialized
    for skill in provider_payload["npc_skills"]:
        assert set(skill) == {
            "skill_id",
            "type",
            "allowed_intents",
            "allowed_tactics",
            "max_disclosure_mode_by_world_info",
            "safe_fragment_refs",
            "allowed_proposed_actions",
        }
        assert "level" not in skill
        assert "signature" not in skill
        assert "memory_plan_id" not in skill
        assert "max_relationship_delta" not in skill
    for safe_fact in provider_payload["safe_facts"]:
        assert "aliases" not in safe_fact
        assert "claim_patterns" not in safe_fact
    for limit in provider_payload["disclosure_limits"]:
        assert "forbidden_modes" not in limit
        assert "related_clue_ids" not in limit
        assert "related_world_info_ids" not in limit
        assert "rhetoric_tactics" not in limit
    assert "UNRELATED_PRIVATE_SECRET_SHOULD_NOT_LEAK" not in serialized
    assert "TAG_ONLY_PRIVATE_SECRET_SHOULD_NOT_LEAK" not in serialized
    assert "The NPC is nervous about the focused clue." not in serialized
    assert "The selected memory is tied to this private knowledge." not in serialized
    assert "The selected skill permits a narrow skill-world evasion." not in serialized
    assert "Detailed player motive should stay local." not in serialized
    assert "Detailed trust boundary should stay local." not in serialized
    assert "character_card" not in serialized
    assert "clue_skill" not in serialized
    assert "full_reveal:world_focus" not in serialized
    assert "world_unrelated" not in serialized
    assert '"partial"' not in serialized


def test_provider_payload_omits_backend_only_forbidden_fact_fields() -> None:
    context = _build_context_with_private_scope_edges().model_copy(
        update={
            "blocked_fact_ids": ["killer_is_x_backend_only"],
            "revealable_fact_ids": ["killer_is_x_reveal_window_backend_only"],
        }
    )
    contract_input = build_llm_agent_input(context)
    contract_input = contract_input.model_copy(
        update={
            "disclosure_constraints": [
                *contract_input.disclosure_constraints,
                LLMDisclosureConstraint(
                    item_id="killer_is_x_backend_only",
                    item_kind="forbidden_fact",
                    must_not_claim=["DO_NOT_SEND_RAW_KILLER_TRUTH"],
                    blocked=True,
                ),
                LLMDisclosureConstraint(
                    item_id="world_focus",
                    item_kind="world_info",
                    related_clue_ids=["clue_focus"],
                    related_world_info_ids=["world_focus"],
                    allowed_modes=[DisclosureMode.HINT],
                    forbidden_modes=[DisclosureMode.FULL],
                    safe_fact_refs=["world_focus.safe_fragment:focus"],
                    must_not_claim=["DO_NOT_SEND_WORLD_INFO_NEGATIVE_CLAIM"],
                    blocked=False,
                ),
            ]
        }
    )

    provider_payload = build_llm_provider_payload(contract_input)
    serialized = json.dumps(provider_payload, ensure_ascii=False)

    assert "blocked_fact_ids" not in serialized
    assert "revealable_fact_ids" not in serialized
    assert "killer_is_x_backend_only" not in serialized
    assert "killer_is_x_reveal_window_backend_only" not in serialized
    assert "DO_NOT_SEND_RAW_KILLER_TRUTH" not in serialized
    assert "DO_NOT_SEND_WORLD_INFO_NEGATIVE_CLAIM" not in serialized
    assert '"must_not_claim"' not in serialized
    assert '"safe_fact_refs"' not in serialized


def test_provider_payload_safe_facts_do_not_send_source_refs() -> None:
    context = _build_context_with_private_scope_edges()

    provider_payload = build_llm_provider_payload(build_llm_agent_input(context))
    safe_facts_serialized = json.dumps(
        provider_payload["safe_facts"],
        ensure_ascii=False,
    )

    assert provider_payload["safe_facts"]
    for safe_fact in provider_payload["safe_facts"]:
        assert "source_refs" not in safe_fact
        assert "aliases" not in safe_fact
        assert "claim_patterns" not in safe_fact
    assert "source_refs" not in safe_facts_serialized
    assert "skill.source" not in safe_facts_serialized


def _knowledge(
    knowledge_id: str,
    *,
    clue_id: str | None = None,
    world_info_id: str | None = None,
    summary: str = "Player knowledge summary.",
) -> PlayerKnowledgeState:
    return PlayerKnowledgeState(
        knowledge_id=knowledge_id,
        clue_id=clue_id,
        world_info_id=world_info_id,
        confidence=1.0,
        acquisition=PlayerKnowledgeAcquisition.DISCOVERED,
        source_type=PlayerKnowledgeSourceType.CLUE,
        title=knowledge_id,
        summary=summary,
        source_event_id=f"{knowledge_id}.event",
    )


def _build_context_with_private_scope_edges() -> AgentContext:
    return AgentContext(
        case_id="case",
        session_id="session",
        target_agent_id="npc",
        current_phase="investigation",
        player_action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id="npc",
            clue_id="clue_focus",
            text="Look at this clue.",
        ),
        player_knowledge=[
            _knowledge(
                "knowledge.focus",
                clue_id="clue_focus",
                world_info_id="world_focus",
                summary="The player has the focus clue.",
            )
        ],
        memory_snapshots=[
            AgentMemorySnapshot(
                memory_id="memory.private_scope",
                memory_type="belief",
                memory_scope="npc_private",
                memory_layer="working",
                subject_id="player",
                owner_character_id="npc",
                content="Selected memory about the memory world.",
                confidence=0.9,
                metadata={
                    "world_info_id": "world_memory",
                    "topic_tags": ["topic_tag_only"],
                },
                last_updated_event_id="memory.private_scope.updated",
            )
        ],
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_secrets=[
                SelfKnowledgeItem(
                    id="secret.focus",
                    kind="secret",
                    summary="The NPC is nervous about the focused clue.",
                    related_clue_ids=["clue_focus"],
                    disclosure_policy=DisclosurePolicy(
                        allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL]
                    ),
                ),
                SelfKnowledgeItem(
                    id="secret.skill",
                    kind="secret",
                    summary="The selected skill permits a narrow skill-world evasion.",
                    related_world_info_ids=["world_skill"],
                    disclosure_policy=DisclosurePolicy(
                        allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL]
                    ),
                ),
                SelfKnowledgeItem(
                    id="secret.unrelated",
                    kind="secret",
                    summary="UNRELATED_PRIVATE_SECRET_SHOULD_NOT_LEAK",
                    related_world_info_ids=["world_unrelated"],
                    disclosure_policy=DisclosurePolicy(
                        allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL]
                    ),
                ),
                SelfKnowledgeItem(
                    id="secret.tag_only",
                    kind="secret",
                    summary="TAG_ONLY_PRIVATE_SECRET_SHOULD_NOT_LEAK",
                    tags=["topic_tag_only"],
                    disclosure_policy=DisclosurePolicy(
                        allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL]
                    ),
                ),
            ],
            inner_knowledge=[
                SelfKnowledgeItem(
                    id="knowledge.memory",
                    kind="knowledge",
                    summary="The selected memory is tied to this private knowledge.",
                    related_world_info_ids=["world_memory"],
                    disclosure_policy=DisclosurePolicy(
                        allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL]
                    ),
                )
            ],
            fact_awareness=[
                _awareness("world_focus", ["clue_focus"]),
                _awareness("world_memory", ["clue_memory"]),
                _awareness("world_skill", ["clue_skill"]),
                _awareness("world_unrelated", ["clue_unrelated"]),
            ],
            fact_disclosure_strategies=[
                _strategy("world_focus", ["clue_focus"]),
                _strategy("world_memory", ["clue_memory"]),
                _strategy("world_skill", ["clue_skill"]),
                _strategy("world_unrelated", ["clue_unrelated"]),
            ],
            inner_portraits=[
                CharacterImpression(
                    owner_character_id="npc",
                    subject_id="player",
                    observer_id="npc",
                    target_id="player",
                    trust=0.1,
                    suspicion=0.4,
                    fear=0.0,
                    personality_impression="Detailed player motive should stay local.",
                    perceived_motive="Detailed player motive should stay local.",
                    trust_boundary="Detailed trust boundary should stay local.",
                    threat_level=0.6,
                    manipulation_risk=0.4,
                    usefulness=0.3,
                    confidence=0.7,
                    source_event_ids=["portrait.private.event"],
                    last_updated_event_id="portrait.private.updated",
                )
            ],
        ),
        portrait_summary="Coarse player stance only.",
        director_safe_fragments=[
            SafeFactFragmentProjection(
                world_info_id="world_focus",
                fragment_id="focus",
                ref="world_focus.safe_fragment:focus",
                summary="The focus safe fragment is authorized.",
                allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL],
                source_refs=["knowledge.focus"],
            ),
            SafeFactFragmentProjection(
                world_info_id="world_skill",
                fragment_id="skill",
                ref="world_skill.safe_fragment:skill",
                summary="The skill safe fragment is authorized.",
                allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL],
                source_refs=["skill.source"],
            ),
        ],
        npc_skill_projections=[
            NpcSkillProjection(
                skill_id="skill.safe_ref",
                type=NpcSkillType.DIALOGUE,
                level=1,
                allowed_intents=[AgentIntentType.ANSWER],
                allowed_tactics=[RhetoricTactic.QUALIFY_CERTAINTY],
                max_disclosure_mode_by_world_info={
                    "world_skill": DisclosureMode.HINT
                },
                safe_fragment_refs=["world_skill.safe_fragment:skill"],
            )
        ],
    )


def _awareness(
    world_info_id: str,
    evidence_clue_ids: list[str],
) -> CharacterFactAwarenessState:
    return CharacterFactAwarenessState(
        awareness_id=f"awareness.npc.{world_info_id}",
        character_id="npc",
        world_info_id=world_info_id,
        stance=CharacterFactStance.KNOWS,
        confidence=0.9,
        source_type=CharacterFactAwarenessSourceType.CHARACTER_CARD,
        evidence_clue_ids=evidence_clue_ids,
        source_event_ids=["case_package"],
        last_updated_event_id="case_package",
    )


def _strategy(
    world_info_id: str,
    evidence_clue_ids: list[str],
) -> FactDisclosureStrategy:
    return FactDisclosureStrategy(
        world_info_id=world_info_id,
        stance=CharacterFactStance.KNOWS,
        allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL],
        forbidden_modes=[DisclosureMode.FULL],
        rhetoric_tactics=[RhetoricTactic.QUALIFY_CERTAINTY],
        must_not_claim=[f"full_reveal:{world_info_id}"],
        safe_fact_refs=[*evidence_clue_ids],
        evidence_clue_ids=evidence_clue_ids,
        confidence=0.9,
        source_awareness_id=f"awareness.npc.{world_info_id}",
    )


def _build_context_with_audit_only_fields() -> AgentContext:
    action = PlayerAction(
        type=ActionType.TALK,
        target_id="npc",
        text="Where were you?",
    )
    return AgentContext(
        case_id="case",
        session_id="session.audit.secret",
        target_agent_id="npc",
        current_phase="opening",
        completed_beats=["intro_complete"],
        discovered_clues=["locked_room"],
        player_knowledge=[
            PlayerKnowledgeState(
                knowledge_id="knowledge.locked_room",
                clue_id="locked_room",
                world_info_id="door_was_locked",
                confidence=1.0,
                acquisition=PlayerKnowledgeAcquisition.DISCOVERED,
                source_type=PlayerKnowledgeSourceType.CLUE,
                title="Locked room",
                summary="The player knows the door was locked.",
                source_event_id="knowledge.event.secret",
            )
        ],
        relationship_to_player=RelationshipState(
            source_id="npc",
            target_id="player",
            trust=0.1,
            suspicion=0.4,
        ),
        recent_events=[
            WorldEvent(
                id="event.recent",
                case_id="case",
                session_id="session.audit.secret",
                actor_id="player",
                type=EventType.PLAYER_TALKED,
                payload={
                    "secret_payload": "SHOULD_NOT_LEAK_EVENT_PAYLOAD",
                    "source_event_ids": ["event.payload.secret"],
                    "source_memory_ids": ["memory.payload.secret"],
                    "rule_id": "rule.secret",
                },
                created_at="2026-06-26T12:00:00Z",
            )
        ],
        memory_snapshots=[
            AgentMemorySnapshot(
                memory_id="memory.selected",
                rule_id="rule.secret",
                memory_type="episodic",
                memory_scope="npc_private",
                memory_layer="working",
                subject_id="player",
                owner_character_id="npc",
                visible_to_character_ids=["npc"],
                content="Selected memory content.",
                source_event_ids=["memory.event.secret"],
                source_memory_ids=["memory.source.secret"],
                confidence=0.8,
                metadata={
                    "case_thread_id": "thread.locked_room",
                    "topic_tags": ["locked_room"],
                    "authority_source": "world_event",
                },
                last_updated_event_id="memory.updated.secret",
                created_at="2026-06-26T12:01:00Z",
                updated_at="2026-06-26T12:02:00Z",
            )
        ],
        player_action=action,
        target_profile=AgentCharacterView(
            id="npc",
            display_name="NPC",
            public_role="Witness",
            defensive_style=DefensiveStyle.NEUTRAL,
            pressure_response=CharacterResponseStyle.ANSWER,
        ),
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_secrets=[
                SelfKnowledgeItem(
                    id="secret.safe",
                    kind="secret",
                    summary="The NPC has a private motive.",
                    disclosure_policy=DisclosurePolicy(direct_reveal_allowed=False),
                )
            ],
            inner_portraits=[
                CharacterImpression(
                    owner_character_id="npc",
                    subject_id="player",
                    observer_id="npc",
                    target_id="player",
                    trust=0.1,
                    suspicion=0.3,
                    fear=0.0,
                    personality_impression="The player is persistent.",
                    perceived_motive="The player is testing gaps.",
                    trust_boundary="Do not volunteer unasked details.",
                    threat_level=0.5,
                    manipulation_risk=0.4,
                    usefulness=0.2,
                    confidence=0.7,
                    source_event_ids=["portrait.event.secret"],
                    last_updated_event_id="portrait.updated.secret",
                )
            ],
        ),
        portrait_summary="The player is persistent but still missing evidence.",
        default_speech="Default fallback.",
        default_intent=AgentIntentType.ANSWER,
        reply_options=[
            MockReplyConfig(speech="SHOULD_NOT_LEAK_REPLY_OPTIONS"),
        ],
    )
