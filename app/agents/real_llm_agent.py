from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urljoin

import httpx

from app.agents.llm_contract import build_llm_agent_input, validate_llm_agent_output
from app.agents.prompt_builder import load_agent_system_prompt
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    LLMAgentContractInput,
    LLMAgentOutputContract,
    LLMDisclosureConstraint,
)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
LLM_API_STYLE_ENV = "LLM_API_STYLE"
LLM_ALLOW_JSON_OBJECT_FALLBACK_ENV = "LLM_ALLOW_JSON_OBJECT_FALLBACK"
LLM_API_STYLE_RESPONSES = "responses"
LLM_API_STYLE_CHAT_COMPLETIONS = "chat_completions"
LLM_API_STYLE_AUTO = "auto"
LLM_API_STYLES = {
    LLM_API_STYLE_RESPONSES,
    LLM_API_STYLE_CHAT_COMPLETIONS,
    LLM_API_STYLE_AUTO,
}


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
        self._api_style = _api_style_from_env()
        self._timeout_seconds = timeout_seconds
        self._client = client

    def generate(self, context: AgentContext) -> AgentIntent:
        if not self._api_key:
            return self._safe_fallback(context)

        try:
            contract_input = build_llm_agent_input(context)
            response_payload = self._create_response(contract_input)
            output_payload = self._extract_json_payload(response_payload)
            return validate_llm_agent_output(output_payload, contract_input)
        except Exception:
            return self._safe_fallback(context)

    def _create_response(
        self,
        contract_input: LLMAgentContractInput | dict[str, Any],
    ) -> dict[str, Any]:
        contract_input = _ensure_contract_input(contract_input)
        contract_payload = contract_input.model_dump(mode="json")
        response_schema = _agent_intent_json_schema(contract_input)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._api_style == LLM_API_STYLE_CHAT_COMPLETIONS:
            return self._create_chat_completion(contract_input, headers)

        request_payload = {
            "model": self._model,
            "instructions": load_agent_system_prompt(),
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
                    "schema": response_schema,
                }
            },
        }
        try:
            return self._post_json(self._responses_url(), headers, request_payload)
        except httpx.HTTPStatusError as exc:
            if (
                self._api_style == LLM_API_STYLE_RESPONSES
                or not self._should_try_chat_completions(exc)
            ):
                raise
        return self._create_chat_completion(contract_input, headers)

    def _create_chat_completion(
        self,
        contract_input: LLMAgentContractInput,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        contract_payload = contract_input.model_dump(mode="json")
        request_payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": load_agent_system_prompt(),
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
                    "schema": _agent_intent_json_schema(contract_input),
                },
            },
        }
        try:
            return self._post_json(self._chat_completions_url(), headers, request_payload)
        except httpx.HTTPStatusError as exc:
            if (
                exc.response.status_code not in {400, 422}
                or not _json_object_fallback_enabled()
            ):
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


def _api_style_from_env() -> str:
    value = os.getenv(LLM_API_STYLE_ENV, LLM_API_STYLE_AUTO).strip().lower().replace("-", "_")
    if value in {"chat", "chat_completion"}:
        return LLM_API_STYLE_CHAT_COMPLETIONS
    if value in LLM_API_STYLES:
        return value
    return LLM_API_STYLE_AUTO


def _json_object_fallback_enabled() -> bool:
    return os.getenv(LLM_ALLOW_JSON_OBJECT_FALLBACK_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _ensure_contract_input(
    contract_input: LLMAgentContractInput | dict[str, Any],
) -> LLMAgentContractInput:
    if isinstance(contract_input, LLMAgentContractInput):
        return contract_input
    return LLMAgentContractInput.model_validate(contract_input)


def _agent_intent_json_schema(
    contract_input: LLMAgentContractInput | None = None,
) -> dict[str, Any]:
    output_contract = (
        contract_input.output_contract
        if contract_input is not None
        else LLMAgentOutputContract()
    )
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
                "enum": [intent.value for intent in output_contract.allowed_intents],
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
                "items": _disclosure_claim_json_schema(contract_input, output_contract),
            },
        },
    }


def _disclosure_claim_json_schema(
    contract_input: LLMAgentContractInput | None,
    output_contract: LLMAgentOutputContract,
) -> dict[str, Any]:
    world_info_constraints = _world_info_constraints(contract_input)
    claim_schemas = [
        _disclosure_claim_json_schema_for_constraint(constraint, output_contract)
        for constraint in world_info_constraints
    ]
    claim_schemas = [schema for schema in claim_schemas if schema is not None]
    if not claim_schemas:
        return _generic_disclosure_claim_json_schema(output_contract)
    if len(claim_schemas) == 1:
        return claim_schemas[0]
    return {"anyOf": claim_schemas}


def _disclosure_claim_json_schema_for_constraint(
    constraint: LLMDisclosureConstraint,
    output_contract: LLMAgentOutputContract,
) -> dict[str, Any] | None:
    allowed_modes = [
        mode.value
        for mode in constraint.allowed_modes
        if mode in output_contract.allowed_disclosure_modes
        and mode not in constraint.forbidden_modes
    ]
    if not allowed_modes:
        return None
    tactic_values = [
        tactic.value
        for tactic in (
            constraint.rhetoric_tactics or output_contract.allowed_rhetoric_tactics
        )
        if tactic in output_contract.allowed_rhetoric_tactics
    ]
    return _disclosure_claim_object_schema(
        world_info_id_schema={"type": "string", "enum": [constraint.item_id]},
        mode_values=allowed_modes,
        tactic_values=tactic_values,
    )


def _generic_disclosure_claim_json_schema(
    output_contract: LLMAgentOutputContract,
) -> dict[str, Any]:
    return _disclosure_claim_object_schema(
        world_info_id_schema={"type": "string"},
        mode_values=[mode.value for mode in output_contract.allowed_disclosure_modes],
        tactic_values=[
            tactic.value for tactic in output_contract.allowed_rhetoric_tactics
        ],
    )


def _disclosure_claim_object_schema(
    *,
    world_info_id_schema: dict[str, Any],
    mode_values: list[str],
    tactic_values: list[str],
) -> dict[str, Any]:
    return {
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
            "world_info_id": world_info_id_schema,
            "mode": {
                "type": "string",
                "enum": mode_values,
            },
            "tactic": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": tactic_values,
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
    }


def _world_info_constraints(
    contract_input: LLMAgentContractInput | None,
) -> list[LLMDisclosureConstraint]:
    if contract_input is None:
        return []
    return [
        constraint
        for constraint in contract_input.disclosure_constraints
        if constraint.item_kind == "world_info"
    ]
