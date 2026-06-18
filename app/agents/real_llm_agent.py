from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import ValidationError

from app.agents.llm_contract import (
    LLMAgentPolicyViolationError,
    LLMAgentPrivateLeakError,
    LLMAgentSchemaError,
    build_llm_agent_input,
    validate_llm_agent_output,
)
from app.agents.prompt_builder import load_agent_system_prompt
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    DisclosureMode,
    LLMAgentContractInput,
    LLMAgentOutputContract,
    LLMDisclosureConstraint,
    LLMErrorSummary,
    LLMErrorType,
    LLMSchemaValidationError,
    ProposedActionType,
)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
XIAOMI_MIMO_HOST = "api.xiaomimimo.com"
XIAOMI_MIMO_DEFAULT_MODEL = "mimo-v2.5"
OPENAI_BACKEND_NAME = "openai"
LLM_API_STYLE_ENV = "LLM_API_STYLE"
LLM_ALLOW_JSON_OBJECT_FALLBACK_ENV = "LLM_ALLOW_JSON_OBJECT_FALLBACK"
LLM_SCHEMA_REPAIR_ATTEMPTS_ENV = "LLM_SCHEMA_REPAIR_ATTEMPTS"
LLM_HTTP_RETRY_ATTEMPTS_ENV = "LLM_HTTP_RETRY_ATTEMPTS"
LLM_TIMEOUT_SECONDS_ENV = "LLM_TIMEOUT_SECONDS"
LLM_API_STYLE_RESPONSES = "responses"
LLM_API_STYLE_CHAT_COMPLETIONS = "chat_completions"
LLM_API_STYLE_AUTO = "auto"
DEFAULT_SCHEMA_REPAIR_ATTEMPTS = 1
DEFAULT_HTTP_RETRY_ATTEMPTS = 2
DEFAULT_TIMEOUT_SECONDS = 20.0
RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
RELATIONSHIP_DELTA_METRICS = [
    "trust",
    "suspicion",
    "fear",
    "intimacy",
    "hostility",
]
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
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
        schema_repair_attempts: int | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self._base_url = (
            base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or DEFAULT_OPENAI_BASE_URL
        )
        self._model = (
            model or os.getenv("OPENAI_MODEL") or _default_model_for_base_url(self._base_url)
        )
        self._api_style = _api_style_from_env(self._base_url)
        self._timeout_seconds = (
            _timeout_seconds_from_env()
            if timeout_seconds is None
            else max(0.1, float(timeout_seconds))
        )
        self._client = client
        self._schema_repair_attempts = (
            _schema_repair_attempts_from_env()
            if schema_repair_attempts is None
            else max(0, schema_repair_attempts)
        )
        self._http_retry_attempts = _http_retry_attempts_from_env()

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        if not self._api_key:
            return self._safe_fallback(
                context,
                contract_input=contract_input,
                error_summary=LLMErrorSummary(
                    backend=OPENAI_BACKEND_NAME,
                    error_type=LLMErrorType.CONFIGURATION_ERROR,
                    error_message_sanitized=(
                        "OPENAI_API_KEY is required for real LLM generation"
                    ),
                    fallback_used=True,
                ),
            )

        try:
            return self.generate_strict(context, contract_input=contract_input)
        except Exception as exc:
            return self._safe_fallback(
                context,
                contract_input=contract_input,
                error_summary=_llm_error_summary(exc, backend=OPENAI_BACKEND_NAME),
            )

    def generate_strict(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is required for strict LLM generation")
        contract_input = contract_input or build_llm_agent_input(context)
        response_payload = self._create_response(contract_input)
        for attempt in range(self._schema_repair_attempts + 1):
            output_payload: dict[str, Any] = {}
            try:
                output_payload = self._extract_json_payload(response_payload)
                return _validate_llm_output_with_local_projection(
                    output_payload,
                    contract_input,
                )
            except json.JSONDecodeError as exc:
                if attempt >= self._schema_repair_attempts:
                    raise
                response_payload = self._create_json_repair_response(
                    contract_input=contract_input,
                    invalid_text=_extract_text_output(response_payload),
                    error_summary=_json_error_summary(exc),
                )
            except ValidationError as exc:
                projected_intent = _project_and_validate_llm_output(
                    output_payload,
                    contract_input,
                )
                if projected_intent is not None:
                    return projected_intent
                if attempt >= self._schema_repair_attempts:
                    raise
                response_payload = self._create_schema_repair_response(
                    contract_input=contract_input,
                    invalid_output=output_payload,
                    error_summary=_schema_error_summary(exc),
                )
            except LLMAgentPrivateLeakError:
                raise
            except LLMAgentPolicyViolationError as exc:
                projected_intent = _project_and_validate_llm_output(
                    output_payload,
                    contract_input,
                    error=exc,
                )
                if projected_intent is not None:
                    return projected_intent
                if attempt >= self._schema_repair_attempts:
                    raise
                response_payload = self._create_schema_repair_response(
                    contract_input=contract_input,
                    invalid_output=output_payload,
                    error_summary=_schema_error_summary(exc),
                )
            except ValueError as exc:
                if attempt >= self._schema_repair_attempts:
                    raise
                response_payload = self._create_schema_repair_response(
                    contract_input=contract_input,
                    invalid_output=output_payload,
                    error_summary=_schema_error_summary(exc),
                )
        raise RuntimeError("unreachable schema repair state")

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
        repair_instruction: str | None = None,
    ) -> dict[str, Any]:
        contract_payload = contract_input.model_dump(mode="json")
        messages = [
            {
                "role": "system",
                "content": load_agent_system_prompt(),
            },
            {
                "role": "user",
                "content": json.dumps(contract_payload, ensure_ascii=False),
            },
        ]
        if repair_instruction is not None:
            messages.append(
                {
                    "role": "user",
                    "content": repair_instruction,
                }
            )
        request_payload = {
            "model": self._model,
            "messages": messages,
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

    def _create_schema_repair_response(
        self,
        *,
        contract_input: LLMAgentContractInput,
        invalid_output: dict[str, Any],
        error_summary: str,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        allowed_intents = ", ".join(
            intent.value for intent in contract_input.output_contract.allowed_intents
        )
        disclosure_modes = ", ".join(mode.value for mode in DisclosureMode)
        disclosure_matrix = _allowed_disclosure_mode_matrix(contract_input)
        repair_draft = _contract_repair_projection(
            invalid_output,
            contract_input=contract_input,
        )
        repair_instruction = (
            "Schema repair required. Return the same NPC turn as a single corrected "
            "AgentIntent JSON object. Do not add new facts. Do not add markdown. "
            "Do not include any keys outside the contract. "
            f"Allowed top-level intent values: {allowed_intents}. "
            "deflect is a disclosure_claims[].mode value, never the top-level intent. "
            f"Disclosure mode values are only for disclosure_claims[].mode: "
            f"{disclosure_modes}. "
            "Allowed disclosure modes by world_info_id:\n"
            f"{disclosure_matrix}\n"
            "Allowed relationship delta caps by metric:\n"
            f"{_relationship_delta_cap_matrix(contract_input)}\n"
            "For every disclosure_claim, mode must be allowed for that exact "
            "world_info_id. If unsure, delete that disclosure_claim. "
            "For every relationship.change proposed_action, each absolute delta "
            "must be less than or equal to its listed cap; if unsure, delete that "
            "proposed_action. "
            "If the rejected output used a disclosure mode as top-level intent, choose "
            "the nearest valid intent such as conceal, refuse, answer, probe, lie, or "
            "panic while preserving the safe speech meaning. Validation error summary: "
            f"{error_summary}. Contract-shaped draft JSON with illegal extra keys removed: "
            f"{json.dumps(repair_draft, ensure_ascii=False)}"
        )
        if self._api_style == LLM_API_STYLE_RESPONSES:
            return self._create_response_schema_repair(
                contract_input=contract_input,
                headers=headers,
                repair_instruction=repair_instruction,
            )
        return self._create_chat_completion(
            contract_input,
            headers,
            repair_instruction=repair_instruction,
        )

    def _create_json_repair_response(
        self,
        *,
        contract_input: LLMAgentContractInput,
        invalid_text: str,
        error_summary: str,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        allowed_intents = ", ".join(
            intent.value for intent in contract_input.output_contract.allowed_intents
        )
        repair_instruction = (
            "JSON repair required. The previous model response was not a single JSON "
            "object. Return exactly one AgentIntent JSON object and no markdown, no "
            "explanation, no trailing text. Do not add new facts. "
            f"Allowed top-level intent values: {allowed_intents}. "
            f"Parse error summary: {error_summary}. Previous response text: "
            f"{_trim_repair_text(invalid_text)}"
        )
        if self._api_style == LLM_API_STYLE_RESPONSES:
            return self._create_response_schema_repair(
                contract_input=contract_input,
                headers=headers,
                repair_instruction=repair_instruction,
            )
        return self._create_chat_completion(
            contract_input,
            headers,
            repair_instruction=repair_instruction,
        )

    def _create_response_schema_repair(
        self,
        *,
        contract_input: LLMAgentContractInput,
        headers: dict[str, str],
        repair_instruction: str,
    ) -> dict[str, Any]:
        contract_payload = contract_input.model_dump(mode="json")
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
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": repair_instruction,
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "agent_intent",
                    "strict": True,
                    "schema": _agent_intent_json_schema(contract_input),
                }
            },
        }
        return self._post_json(self._responses_url(), headers, request_payload)

    def _post_json(
        self,
        url: str,
        headers: dict[str, str],
        request_payload: dict[str, Any],
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self._http_retry_attempts + 1):
            try:
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
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self._http_retry_attempts or not _retryable_http_error(exc):
                    raise
                time.sleep(_http_retry_delay_seconds(attempt, exc))
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM provider request did not return a response")

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

    def _safe_fallback(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
        error_summary: LLMErrorSummary,
    ) -> AgentIntent:
        context = contract_input.agent_context if contract_input is not None else context
        return AgentIntent(
            speech=f"{context.target_agent_id} cannot answer through the LLM backend.",
            intent=_safe_fallback_intent(contract_input),
            emotional_shift={},
            proposed_actions=[],
            memory_refs=[],
            disclosure_claims=[],
            llm_error=error_summary,
        )


def _llm_error_summary(exc: Exception, *, backend: str) -> LLMErrorSummary:
    error_type = _classify_llm_error(exc)
    return LLMErrorSummary(
        backend=backend,
        error_type=error_type,
        error_message_sanitized=_sanitized_llm_error_message(exc, error_type),
        fallback_used=True,
        schema_validation_errors=_schema_validation_error_details(exc),
    )


def _safe_fallback_intent(
    contract_input: LLMAgentContractInput | None,
) -> AgentIntentType:
    if contract_input is None:
        return AgentIntentType.REFUSE
    return contract_input.output_contract.fallback_intent


def _classify_llm_error(exc: Exception) -> LLMErrorType:
    if isinstance(exc, httpx.TimeoutException):
        return LLMErrorType.TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError | httpx.TransportError):
        return LLMErrorType.NETWORK_ERROR
    if isinstance(exc, json.JSONDecodeError):
        return LLMErrorType.INVALID_JSON
    if isinstance(exc, LLMAgentPrivateLeakError):
        return LLMErrorType.PRIVATE_LEAK_DETECTED
    if isinstance(exc, LLMAgentPolicyViolationError):
        return LLMErrorType.POLICY_VIOLATION
    if isinstance(exc, ValidationError | LLMAgentSchemaError):
        return LLMErrorType.SCHEMA_ERROR
    if isinstance(exc, ValueError):
        return LLMErrorType.INVALID_JSON
    if isinstance(exc, RuntimeError) and "OPENAI_API_KEY" in str(exc):
        return LLMErrorType.CONFIGURATION_ERROR
    return LLMErrorType.UNKNOWN_ERROR


def _sanitized_llm_error_message(exc: Exception, error_type: LLMErrorType) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "LLM provider request timed out"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"LLM provider returned HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TransportError):
        return f"LLM provider transport error: {type(exc).__name__}"
    if isinstance(exc, json.JSONDecodeError):
        return f"LLM output was not valid JSON: {_json_error_summary(exc)}"
    if isinstance(exc, ValidationError):
        return _schema_error_summary(exc)
    if isinstance(
        exc,
        LLMAgentSchemaError | LLMAgentPolicyViolationError | LLMAgentPrivateLeakError,
    ):
        return _trim_sanitized_message(str(exc))
    if error_type == LLMErrorType.INVALID_JSON:
        return "LLM response did not contain a valid AgentIntent JSON object"
    if error_type == LLMErrorType.CONFIGURATION_ERROR:
        return "OPENAI_API_KEY is required for real LLM generation"
    return f"Unhandled LLM error: {type(exc).__name__}"


def _schema_validation_error_details(exc: Exception) -> list[LLMSchemaValidationError]:
    if isinstance(exc, ValidationError):
        return [
            LLMSchemaValidationError(
                loc=[str(part) for part in error.get("loc", [])],
                error_type=str(error.get("type", "unknown")),
                message_sanitized=_trim_sanitized_message(str(error.get("msg", ""))),
            )
            for error in exc.errors()[:8]
        ]
    if isinstance(exc, LLMAgentSchemaError):
        return [
            LLMSchemaValidationError(
                loc=[],
                error_type="schema_error",
                message_sanitized=_trim_sanitized_message(str(exc)),
            )
        ]
    return []


def _trim_sanitized_message(message: str, *, limit: int = 180) -> str:
    normalized = " ".join(message.split())
    if not normalized:
        return "LLM error"
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "...[truncated]"


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


def _extract_text_output(response_payload: dict[str, Any]) -> str:
    output_text = response_payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    for output_item in response_payload.get("output", []):
        if not isinstance(output_item, dict):
            continue
        for content_item in output_item.get("content", []):
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str):
                return text

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
                return content
            if isinstance(content, list):
                for content_item in content:
                    if not isinstance(content_item, dict):
                        continue
                    text = content_item.get("text")
                    if isinstance(text, str):
                        return text
    return json.dumps(response_payload, ensure_ascii=False)


def _trim_repair_text(text: str, *, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _json_error_summary(exc: json.JSONDecodeError) -> str:
    return f"{exc.msg} at line {exc.lineno} column {exc.colno}"


def _schema_error_summary(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if not errors:
            return f"{exc.error_count()} validation errors"
        first_error = errors[0]
        error_type = str(first_error.get("type", "unknown"))
        return f"{exc.error_count()} validation errors; first_error_type={error_type}"
    message = str(exc).splitlines()[0]
    return message[:160]


def _validate_llm_output_with_local_projection(
    payload: dict[str, Any],
    contract_input: LLMAgentContractInput,
) -> AgentIntent:
    projected = _project_and_validate_llm_output(payload, contract_input)
    if projected is not None:
        return projected
    try:
        return validate_llm_agent_output(payload, contract_input)
    except LLMAgentPolicyViolationError as exc:
        projected = _project_and_validate_llm_output(
            payload,
            contract_input,
            error=exc,
        )
        if projected is None:
            raise
        return projected
    except (LLMAgentSchemaError, ValidationError):
        projected = _project_and_validate_llm_output(payload, contract_input)
        if projected is None:
            raise
        return projected


def _project_and_validate_llm_output(
    payload: dict[str, Any],
    contract_input: LLMAgentContractInput,
    *,
    error: Exception | None = None,
) -> AgentIntent | None:
    if error is not None and "narrative phase changes" in str(error):
        return None
    if not isinstance(payload.get("speech"), str):
        return None
    projected = _contract_repair_projection(payload, contract_input=contract_input)
    if projected == payload:
        return None
    try:
        return validate_llm_agent_output(projected, contract_input)
    except (ValidationError, LLMAgentSchemaError, LLMAgentPolicyViolationError):
        return None


def _contract_repair_projection(
    payload: dict[str, Any],
    *,
    contract_input: LLMAgentContractInput | None = None,
) -> dict[str, Any]:
    output_contract = contract_input.output_contract if contract_input is not None else None
    allowed_intents = set(output_contract.allowed_intents) if output_contract is not None else set()
    raw_intent = payload.get("intent")
    intent = (
        raw_intent
        if isinstance(raw_intent, str)
        and (not allowed_intents or raw_intent in {item.value for item in allowed_intents})
        else _contract_fallback_intent_value(output_contract)
    )
    speech = (
        payload.get("speech")
        if isinstance(payload.get("speech"), str)
        else "I cannot answer that safely."
    )
    disclosure_claims = _project_disclosure_claims(
        payload.get("disclosure_claims"),
        contract_input=contract_input,
    )
    disclosure_claims.extend(
        _infer_safe_fragment_disclosure_claims(
            speech,
            contract_input=contract_input,
            existing_claims=disclosure_claims,
        )
    )
    return {
        "speech": speech,
        "intent": intent,
        "emotional_shift": _numeric_mapping(payload.get("emotional_shift")),
        "proposed_actions": _project_proposed_actions(
            payload.get("proposed_actions"),
            output_contract=output_contract,
        ),
        "memory_refs": _string_list(payload.get("memory_refs")),
        "disclosure_claims": disclosure_claims,
    }


def _contract_fallback_intent_value(
    output_contract: LLMAgentOutputContract | None,
) -> str:
    if output_contract is None:
        return AgentIntentType.REFUSE.value
    allowed_values = {intent.value for intent in output_contract.allowed_intents}
    for preferred in (
        output_contract.fallback_intent,
        AgentIntentType.REFUSE,
        AgentIntentType.CONCEAL,
        AgentIntentType.ANSWER,
    ):
        if preferred.value in allowed_values:
            return preferred.value
    if output_contract.allowed_intents:
        return output_contract.allowed_intents[0].value
    return AgentIntentType.REFUSE.value


def _allowed_disclosure_mode_matrix(contract_input: LLMAgentContractInput) -> str:
    lines: list[str] = []
    for constraint in contract_input.disclosure_constraints:
        if constraint.item_kind != "world_info":
            continue
        allowed_modes = [
            mode.value
            for mode in constraint.allowed_modes
            if mode not in set(constraint.forbidden_modes) and mode != DisclosureMode.FULL
        ]
        if not allowed_modes:
            allowed_modes = ["none"]
        safe_refs = ", ".join(constraint.safe_fact_refs) or "none"
        lines.append(
            f"- {constraint.item_id}: modes={', '.join(allowed_modes)}; "
            f"safe_refs={safe_refs}"
        )
    if not lines:
        return "- no world_info disclosure_claim is allowed; use []"
    return "\n".join(lines)


def _relationship_delta_cap_matrix(contract_input: LLMAgentContractInput) -> str:
    if ProposedActionType.RELATIONSHIP_CHANGE not in set(
        contract_input.output_contract.allowed_proposed_action_types
    ):
        return "- relationship.change is not allowed; use []"
    caps = contract_input.output_contract.max_relationship_delta
    lines = [
        f"- {metric}: max_abs_delta={abs(float(caps[metric])):.4f}"
        for metric in RELATIONSHIP_DELTA_METRICS
        if metric in caps
    ]
    if not lines:
        return "- relationship.change has no allowed non-zero deltas; delete it"
    return "\n".join(lines)


def _numeric_mapping(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): float(item)
        for key, item in value.items()
        if isinstance(item, int | float)
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _project_proposed_actions(
    value: object,
    *,
    output_contract: LLMAgentOutputContract | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        projected
        for item in value
        if isinstance(item, dict)
        for projected in [
            _project_proposed_action(item, output_contract=output_contract)
        ]
        if projected
    ]


def _project_proposed_action(
    item: dict[str, Any],
    *,
    output_contract: LLMAgentOutputContract | None = None,
) -> dict[str, Any]:
    action_type = item.get("type")
    if output_contract is not None:
        allowed_action_values = {
            action_type.value
            for action_type in output_contract.allowed_proposed_action_types
        }
        if action_type not in allowed_action_values:
            return {}
    if action_type == "clue.discover":
        return {
            key: item[key]
            for key in ("type", "clue_id")
            if key in item and isinstance(item[key], str)
        }
    if action_type == "relationship.change":
        projected = {
            key: item[key]
            for key in ("type", "source_id", "target_id")
            if key in item and isinstance(item[key], str)
        }
        deltas = item.get("deltas")
        if isinstance(deltas, dict):
            projected["deltas"] = {
                key: float(deltas[key])
                for key in ("trust", "suspicion", "fear", "intimacy", "hostility")
                if key in deltas and isinstance(deltas[key], int | float)
            }
            if not _relationship_deltas_fit_contract(
                projected["deltas"],
                output_contract,
            ):
                return {}
        return projected
    if isinstance(action_type, str):
        return {"type": action_type}
    return {}


def _project_disclosure_claims(
    value: object,
    *,
    contract_input: LLMAgentContractInput | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    constraints = _world_info_constraints_by_id(contract_input)
    return [
        projected
        for item in value
        if isinstance(item, dict)
        for projected in [_project_disclosure_claim(item, contract_input, constraints)]
        if projected is not None
    ]


def _project_disclosure_claim(
    item: dict[str, Any],
    contract_input: LLMAgentContractInput | None,
    constraints: dict[str, LLMDisclosureConstraint],
) -> dict[str, Any] | None:
    world_info_id = item.get("world_info_id")
    if not isinstance(world_info_id, str):
        return None
    mode = item.get("mode") if isinstance(item.get("mode"), str) else "none"
    tactic = item.get("tactic") if isinstance(item.get("tactic"), str) else None
    source_refs = _string_list(item.get("source_refs"))
    claim_refs = _string_list(item.get("claim_refs"))
    if contract_input is None:
        return {
            "world_info_id": world_info_id,
            "mode": mode,
            "tactic": tactic,
            "source_refs": source_refs,
            "claim_refs": claim_refs,
        }
    output_contract = contract_input.output_contract
    constraint = constraints.get(world_info_id)
    if constraint is None:
        return None
    allowed_modes = {
        mode.value
        for mode in constraint.allowed_modes
        if mode in output_contract.allowed_disclosure_modes
        and mode not in constraint.forbidden_modes
        and mode != DisclosureMode.FULL
    }
    projected_mode = _safe_fragment_projection_claim_mode(
        mode,
        constraint,
        output_contract,
    )
    if projected_mode is not None:
        mode = projected_mode.value
    if mode not in allowed_modes:
        return None
    if tactic is not None and tactic not in {
        item.value for item in output_contract.allowed_rhetoric_tactics
    }:
        tactic = None
    authorized_refs = _authorized_disclosure_refs(constraint)
    if authorized_refs:
        source_refs = [ref for ref in source_refs if ref in authorized_refs]
        claim_refs = [ref for ref in claim_refs if ref in authorized_refs]
    if _should_fill_single_safe_fragment_ref(mode, constraint):
        source_refs, claim_refs = _ensure_single_safe_fragment_ref(
            constraint,
            source_refs=source_refs,
            claim_refs=claim_refs,
        )
    return {
        "world_info_id": world_info_id,
        "mode": mode,
        "tactic": tactic,
        "source_refs": source_refs,
        "claim_refs": claim_refs,
    }


def _safe_fragment_projection_claim_mode(
    mode: str,
    constraint: LLMDisclosureConstraint,
    output_contract: LLMAgentOutputContract,
) -> DisclosureMode | None:
    if mode not in {
        DisclosureMode.NONE.value,
        DisclosureMode.DENY.value,
        DisclosureMode.DEFLECT.value,
        DisclosureMode.HINT.value,
    }:
        return None
    if not constraint.safe_fragments:
        return None
    for preferred in (DisclosureMode.PARTIAL, DisclosureMode.HINT):
        if (
            preferred in constraint.allowed_modes
            and preferred not in constraint.forbidden_modes
            and preferred in output_contract.allowed_disclosure_modes
            and any(preferred in fragment.allowed_modes for fragment in constraint.safe_fragments)
        ):
            return preferred
    return None


def _should_fill_single_safe_fragment_ref(
    mode: str,
    constraint: LLMDisclosureConstraint,
) -> bool:
    return (
        mode in {DisclosureMode.PARTIAL.value, DisclosureMode.HINT.value}
        and bool(constraint.safe_fragments)
    )


def _ensure_single_safe_fragment_ref(
    constraint: LLMDisclosureConstraint,
    *,
    source_refs: list[str],
    claim_refs: list[str],
) -> tuple[list[str], list[str]]:
    if len(constraint.safe_fragments) != 1:
        return source_refs, claim_refs
    safe_fragment_refs = _authorized_safe_fragment_reference_refs(constraint)
    if set([*source_refs, *claim_refs]) & safe_fragment_refs:
        return source_refs, claim_refs
    fragment_ref = constraint.safe_fragments[0].ref
    return [*source_refs, fragment_ref], [*claim_refs, fragment_ref]


def _infer_safe_fragment_disclosure_claims(
    speech: str,
    *,
    contract_input: LLMAgentContractInput | None,
    existing_claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if contract_input is None or not speech:
        return []
    claimed_world_info_ids = {
        claim.get("world_info_id")
        for claim in existing_claims
        if isinstance(claim.get("world_info_id"), str)
    }
    inferred: list[dict[str, Any]] = []
    for constraint in _world_info_constraints_by_id(contract_input).values():
        if constraint.item_id in claimed_world_info_ids:
            continue
        match = _matching_safe_fragment_for_speech(speech, constraint)
        if match is None:
            continue
        fragment, mode = match
        inferred.append(
            {
                "world_info_id": constraint.item_id,
                "mode": mode.value,
                "tactic": None,
                "source_refs": [fragment.ref],
                "claim_refs": [fragment.ref],
            }
        )
        claimed_world_info_ids.add(constraint.item_id)
    return inferred


def _matching_safe_fragment_for_speech(
    speech: str,
    constraint: LLMDisclosureConstraint,
) -> tuple[Any, DisclosureMode] | None:
    for fragment in constraint.safe_fragments:
        mode = _safe_fragment_projection_mode(fragment, constraint)
        if mode is None:
            continue
        if _speech_matches_safe_fragment_projection(speech, fragment):
            return fragment, mode
    return None


def _safe_fragment_projection_mode(
    fragment: Any,
    constraint: LLMDisclosureConstraint,
) -> DisclosureMode | None:
    allowed_modes = [
        mode
        for mode in fragment.allowed_modes
        if mode in constraint.allowed_modes
        and mode not in constraint.forbidden_modes
        and mode != DisclosureMode.FULL
    ]
    for preferred in (DisclosureMode.PARTIAL, DisclosureMode.HINT):
        if preferred in allowed_modes:
            return preferred
    return allowed_modes[0] if allowed_modes else None


def _speech_matches_safe_fragment_projection(speech: str, fragment: Any) -> bool:
    normalized_speech = _normalize_claim_text(speech)
    for alias in getattr(fragment, "aliases", []):
        normalized_alias = _normalize_claim_text(str(alias))
        if normalized_alias and normalized_alias in normalized_speech:
            return True
    for pattern in getattr(fragment, "claim_patterns", []):
        try:
            if re.search(str(pattern), speech, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _normalize_claim_text(value: str) -> str:
    return "".join(value.casefold().split())


def _relationship_deltas_fit_contract(
    deltas: dict[str, float],
    output_contract: LLMAgentOutputContract | None,
) -> bool:
    if output_contract is None:
        return True
    caps = output_contract.max_relationship_delta
    for metric, value in deltas.items():
        numeric = abs(float(value))
        if numeric == 0:
            continue
        cap = caps.get(str(metric))
        if cap is None or numeric > abs(float(cap)):
            return False
    return True


def _world_info_constraints_by_id(
    contract_input: LLMAgentContractInput | None,
) -> dict[str, LLMDisclosureConstraint]:
    if contract_input is None:
        return {}
    return {
        constraint.item_id: constraint
        for constraint in contract_input.disclosure_constraints
        if constraint.item_kind == "world_info"
    }


def _authorized_disclosure_refs(constraint: LLMDisclosureConstraint) -> set[str]:
    refs = set(constraint.safe_fact_refs)
    refs.update(_authorized_safe_fragment_reference_refs(constraint))
    return refs


def _authorized_safe_fragment_reference_refs(
    constraint: LLMDisclosureConstraint,
) -> set[str]:
    refs: set[str] = set()
    for fragment in constraint.safe_fragments:
        refs.add(fragment.ref)
        refs.add(fragment.fragment_id)
        refs.add(f"safe_fragment:{fragment.fragment_id}")
        refs.add(f"{fragment.world_info_id}.{fragment.fragment_id}")
        refs.add(f"{fragment.world_info_id}:{fragment.fragment_id}")
        refs.update(fragment.source_refs)
    return refs


def _default_model_for_base_url(base_url: str) -> str:
    if _is_xiaomi_mimo_base_url(base_url):
        return XIAOMI_MIMO_DEFAULT_MODEL
    return DEFAULT_OPENAI_MODEL


def _api_style_from_env(base_url: str | None = None) -> str:
    value = os.getenv(LLM_API_STYLE_ENV, "").strip().lower().replace("-", "_")
    if value in {"chat", "chat_completion"}:
        return LLM_API_STYLE_CHAT_COMPLETIONS
    if value in {LLM_API_STYLE_RESPONSES, LLM_API_STYLE_CHAT_COMPLETIONS}:
        return value
    if value in {"", LLM_API_STYLE_AUTO} and _is_xiaomi_mimo_base_url(base_url):
        return LLM_API_STYLE_CHAT_COMPLETIONS
    if value == LLM_API_STYLE_AUTO:
        return LLM_API_STYLE_AUTO
    return LLM_API_STYLE_AUTO


def _is_xiaomi_mimo_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    try:
        return urlparse(base_url).hostname == XIAOMI_MIMO_HOST
    except ValueError:
        return False


def _schema_repair_attempts_from_env() -> int:
    value = os.getenv(LLM_SCHEMA_REPAIR_ATTEMPTS_ENV)
    if value is None or value.strip() == "":
        return DEFAULT_SCHEMA_REPAIR_ATTEMPTS
    try:
        return max(0, int(value))
    except ValueError:
        return DEFAULT_SCHEMA_REPAIR_ATTEMPTS


def _http_retry_attempts_from_env() -> int:
    value = os.getenv(LLM_HTTP_RETRY_ATTEMPTS_ENV)
    if value is None or value.strip() == "":
        return DEFAULT_HTTP_RETRY_ATTEMPTS
    try:
        return max(0, int(value))
    except ValueError:
        return DEFAULT_HTTP_RETRY_ATTEMPTS


def _timeout_seconds_from_env() -> float:
    value = os.getenv(LLM_TIMEOUT_SECONDS_ENV)
    if value is None or value.strip() == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(0.1, float(value))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _retryable_http_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_HTTP_STATUS_CODES
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


def _http_retry_delay_seconds(attempt: int, exc: Exception) -> float:
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("retry-after")
        if retry_after is not None:
            try:
                return min(2.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
    return min(2.0, 0.25 * (2**attempt))


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
                "items": _proposed_action_json_schema(output_contract),
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


def _proposed_action_json_schema(
    output_contract: LLMAgentOutputContract,
) -> dict[str, Any]:
    schemas: list[dict[str, Any]] = []
    allowed = set(output_contract.allowed_proposed_action_types)
    if any(action_type.value == "clue.discover" for action_type in allowed):
        schemas.append(
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
            }
        )
    if any(action_type.value == "relationship.change" for action_type in allowed):
        schemas.append(
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
                        "required": RELATIONSHIP_DELTA_METRICS,
                        "properties": {
                            metric: _relationship_delta_metric_json_schema(
                                output_contract,
                                metric,
                            )
                            for metric in RELATIONSHIP_DELTA_METRICS
                        },
                    },
                },
            }
        )
    if not schemas:
        return {"not": {}}
    if len(schemas) == 1:
        return schemas[0]
    return {"anyOf": schemas}


def _relationship_delta_metric_json_schema(
    output_contract: LLMAgentOutputContract,
    metric: str,
) -> dict[str, Any]:
    cap = output_contract.max_relationship_delta.get(metric)
    if cap is None:
        return {"type": "number", "minimum": 0, "maximum": 0}
    max_abs_delta = round(abs(float(cap)), 4)
    return {
        "type": "number",
        "minimum": -max_abs_delta,
        "maximum": max_abs_delta,
    }


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
        ref_values=constraint.safe_fact_refs,
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
        ref_values=None,
    )


def _disclosure_claim_object_schema(
    *,
    world_info_id_schema: dict[str, Any],
    mode_values: list[str],
    tactic_values: list[str],
    ref_values: list[str] | None,
) -> dict[str, Any]:
    ref_item_schema = (
        {"type": "string", "enum": ref_values}
        if ref_values
        else {"type": "string"}
    )
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
                "items": ref_item_schema,
            },
            "claim_refs": {
                "type": "array",
                "items": ref_item_schema,
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



