from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urljoin

import httpx

from app.agents.llm_contract import build_llm_agent_input, validate_llm_agent_output
from app.domain.models import AgentContext, AgentIntent, AgentIntentType

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


class OpenAILLMAgent:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self._base_url = (
            base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or DEFAULT_OPENAI_BASE_URL
        )
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
            "instructions": _agent_intent_system_prompt(),
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
        try:
            return self._post_json(self._responses_url(), headers, request_payload)
        except httpx.HTTPStatusError as exc:
            if not self._should_try_chat_completions(exc):
                raise
        return self._create_chat_completion(contract_payload, headers)

    def _create_chat_completion(
        self,
        contract_payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        request_payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": _agent_intent_system_prompt(),
                },
                {
                    "role": "user",
                    "content": json.dumps(contract_payload, ensure_ascii=False),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_intent",
                    "strict": True,
                    "schema": _agent_intent_json_schema(),
                },
            },
        }
        try:
            return self._post_json(self._chat_completions_url(), headers, request_payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {400, 422}:
                raise
        fallback_payload = dict(request_payload)
        fallback_payload["response_format"] = {"type": "json_object"}
        return self._post_json(self._chat_completions_url(), headers, fallback_payload)

    def _post_json(
        self,
        url: str,
        headers: dict[str, str],
        request_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._client is not None:
            response = self._client.post(
                url,
                headers=headers,
                json=request_payload,
                timeout=self._timeout_seconds,
            )
        else:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    url,
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
            return _parse_json_object_text(output_text, "OpenAI output_text")

        for output_item in response_payload.get("output", []):
            if not isinstance(output_item, dict):
                continue
            for content_item in output_item.get("content", []):
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str):
                    return _parse_json_object_text(text, "OpenAI response content")
        choices = response_payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    return _parse_json_object_text(content, "Chat completion content")
                if isinstance(content, list):
                    for content_item in content:
                        if not isinstance(content_item, dict):
                            continue
                        text = content_item.get("text")
                        if isinstance(text, str):
                            return _parse_json_object_text(text, "Chat completion content")
        raise ValueError("OpenAI response did not contain JSON text output")

    def _responses_url(self) -> str:
        base_url = self._base_url.rstrip("/") + "/"
        if base_url.endswith("/responses/"):
            return base_url.rstrip("/")
        if base_url == DEFAULT_OPENAI_BASE_URL.rstrip("/") + "/":
            return OPENAI_RESPONSES_URL
        return urljoin(base_url, "responses")

    def _chat_completions_url(self) -> str:
        base_url = self._base_url.rstrip("/") + "/"
        if base_url.endswith("/chat/completions/"):
            return base_url.rstrip("/")
        return urljoin(base_url, "chat/completions")

    def _should_try_chat_completions(self, exc: httpx.HTTPStatusError) -> bool:
        base_url = self._base_url.rstrip("/") + "/"
        default_base_url = DEFAULT_OPENAI_BASE_URL.rstrip("/") + "/"
        return (
            base_url != default_base_url
            and exc.response.status_code in {400, 404, 405, 422}
        )

    def _safe_fallback(self, context: AgentContext) -> AgentIntent:
        return AgentIntent(
            speech=f"{context.target_agent_id} cannot answer through the LLM backend.",
            intent=AgentIntentType.REFUSE,
            emotional_shift={},
            proposed_actions=[],
            memory_refs=[],
        )


def _parse_json_object_text(text: str, source: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1]).strip()
            parsed = json.loads(stripped)
        else:
            raise
    if not isinstance(parsed, dict):
        raise ValueError(f"{source} must decode to a JSON object")
    return parsed


def _agent_intent_system_prompt() -> str:
    return (
        "You are a controlled NPC agent for an event-sourced mystery runtime. "
        "Return a single JSON object and no markdown. The top-level keys must be exactly: "
        "speech, intent, emotional_shift, proposed_actions, memory_refs, disclosure_claims. "
        "Do not include thoughts, reasoning, analysis, agent_id, character_name, metadata, "
        "or any other extra key. speech must be a string. intent must be one of: answer, "
        "conceal, lie, refuse, probe, panic. emotional_shift must be an object; use {} "
        "when there is no shift. proposed_actions must be an array; use [] when there is "
        "no allowed state proposal. proposed_actions may only contain clue.discover "
        "objects with clue_id, or relationship.change objects with source_id, target_id, "
        "and numeric deltas for trust, suspicion, fear, intimacy, hostility. memory_refs "
        "must be an array of strings. disclosure_claims must be an array; each item must "
        "have world_info_id, mode, tactic, source_refs, claim_refs. mode must be one of: "
        "none, deny, deflect, hint, partial, full. tactic must be null or one of: "
        "answer_adjacent_truth, shift_focus, counter_question, qualify_certainty, "
        "emotional_screen, silence. For disclosure_claims, only use world_info_id values "
        "that appear in disclosure_constraints, and only use modes listed in that item's "
        "allowed_modes. Never use a mode listed in forbidden_modes. Never use mode full. "
        "If the allowed mode is unclear, omit the disclosure claim and avoid mentioning "
        "that WorldInfo in speech. Do not reveal raw private text. Do not propose narrative "
        "phase changes. Any real state change must be requested only through allowed "
        "proposed_actions. If uncertain, return intent refuse with empty arrays."
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
            "disclosure_claims",
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
            "disclosure_claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "world_info_id",
                        "mode",
                        "tactic",
                        "source_refs",
                        "claim_refs",
                    ],
                    "properties": {
                        "world_info_id": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": [
                                "none",
                                "deny",
                                "deflect",
                                "hint",
                                "partial",
                                "full",
                            ],
                        },
                        "tactic": {
                            "anyOf": [
                                {
                                    "type": "string",
                                    "enum": [
                                        "answer_adjacent_truth",
                                        "shift_focus",
                                        "counter_question",
                                        "qualify_certainty",
                                        "emotional_screen",
                                        "silence",
                                    ],
                                },
                                {"type": "null"},
                            ],
                        },
                        "source_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "claim_refs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
        },
    }
