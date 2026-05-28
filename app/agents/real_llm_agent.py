from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.agents.llm_contract import build_llm_agent_input, validate_llm_agent_output
from app.domain.models import AgentContext, AgentIntent, AgentIntentType

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


class OpenAILLMAgent:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self._model = model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        self._timeout_seconds = timeout_seconds
        self._client = client

    def generate(self, context: AgentContext) -> AgentIntent:
        if not self._api_key:
            return self._safe_fallback(context)

        try:
            contract_input = build_llm_agent_input(context)
            response_payload = self._create_response(contract_input.model_dump(mode="json"))
            output_payload = self._extract_json_payload(response_payload)
            return validate_llm_agent_output(output_payload, contract_input)
        except Exception:
            return self._safe_fallback(context)

    def _create_response(self, contract_payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = {
            "model": self._model,
            "instructions": (
                "You are a controlled NPC agent for an event-sourced mystery runtime. "
                "Return only JSON matching the AgentIntent schema. Do not reveal raw "
                "private text. Do not propose narrative phase changes. Any real state "
                "change must be requested only through allowed proposed_actions."
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(contract_payload, ensure_ascii=False),
                        }
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "agent_intent",
                    "strict": True,
                    "schema": _agent_intent_json_schema(),
                }
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = self._client.post(
                OPENAI_RESPONSES_URL,
                headers=headers,
                json=request_payload,
                timeout=self._timeout_seconds,
            )
        else:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    OPENAI_RESPONSES_URL,
                    headers=headers,
                    json=request_payload,
                )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("OpenAI response payload must be an object")
        return payload

    def _extract_json_payload(self, response_payload: dict[str, Any]) -> dict[str, Any]:
        output_text = response_payload.get("output_text")
        if isinstance(output_text, str):
            parsed = json.loads(output_text)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("OpenAI output_text must decode to a JSON object")

        for output_item in response_payload.get("output", []):
            if not isinstance(output_item, dict):
                continue
            for content_item in output_item.get("content", []):
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str):
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
        raise ValueError("OpenAI response did not contain JSON text output")

    def _safe_fallback(self, context: AgentContext) -> AgentIntent:
        return AgentIntent(
            speech=f"{context.target_agent_id} cannot answer through the LLM backend.",
            intent=AgentIntentType.REFUSE,
            emotional_shift={},
            proposed_actions=[],
            memory_refs=[],
        )


def _agent_intent_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "speech",
            "intent",
            "emotional_shift",
            "proposed_actions",
            "memory_refs",
        ],
        "properties": {
            "speech": {"type": "string"},
            "intent": {
                "type": "string",
                "enum": ["answer", "conceal", "lie", "refuse", "probe", "panic"],
            },
            "emotional_shift": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                "required": [],
            },
            "proposed_actions": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type", "clue_id"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["clue.discover"],
                                },
                                "clue_id": {"type": "string"},
                            },
                        },
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type", "source_id", "target_id", "deltas"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["relationship.change"],
                                },
                                "source_id": {"type": "string"},
                                "target_id": {"type": "string"},
                                "deltas": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [
                                        "trust",
                                        "suspicion",
                                        "fear",
                                        "intimacy",
                                        "hostility",
                                    ],
                                    "properties": {
                                        "trust": {"type": "number"},
                                        "suspicion": {"type": "number"},
                                        "fear": {"type": "number"},
                                        "intimacy": {"type": "number"},
                                        "hostility": {"type": "number"},
                                    },
                                },
                            },
                        },
                    ]
                },
            },
            "memory_refs": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }
