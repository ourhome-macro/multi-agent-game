from __future__ import annotations

import json
from typing import Any

import httpx

from app.agents.llm_contract import build_llm_agent_input
from app.agents.real_llm_agent import OpenAILLMAgent
from app.domain.models import (
    ActionType,
    AgentCharacterView,
    AgentContext,
    AgentIntentType,
    AgentMemorySnapshot,
    CharacterImpression,
    CharacterInnerContext,
    CharacterResponseStyle,
    DefensiveStyle,
    DisclosurePolicy,
    EventType,
    MockReplyConfig,
    PlayerAction,
    PlayerKnowledgeAcquisition,
    PlayerKnowledgeSourceType,
    PlayerKnowledgeState,
    RelationshipState,
    SelfKnowledgeItem,
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
    assert provider_payload["memories"][0]["content"] == "Selected memory content."
    assert set(provider_payload["recent_events"][0]) == {
        "id",
        "type",
        "actor_id",
        "safe_summary",
    }
    assert "SHOULD_NOT_LEAK_REPLY_OPTIONS" not in serialized
    assert "SHOULD_NOT_LEAK_EVENT_PAYLOAD" not in serialized
    assert "event.payload.secret" not in serialized
    assert "rule.secret" not in serialized
    for field_name in AUDIT_FIELD_NAMES:
        assert field_name not in serialized


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
