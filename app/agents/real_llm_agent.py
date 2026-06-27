from __future__ import annotations

import json
import os
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
)
from app.agents.prompt_builder import load_agent_system_prompt
from app.agents.provider_payload import build_llm_provider_payload
from app.agents.provider_repair import (
    allowed_disclosure_mode_matrix as _allowed_disclosure_mode_matrix,
)
from app.agents.provider_repair import (
    contract_repair_projection as _contract_repair_projection,
)
from app.agents.provider_repair import (
    json_error_summary as _json_error_summary,
)
from app.agents.provider_repair import (
    project_and_validate_llm_output as _project_and_validate_llm_output,
)
from app.agents.provider_repair import (
    relationship_delta_cap_matrix as _relationship_delta_cap_matrix,
)
from app.agents.provider_repair import (
    schema_error_summary as _schema_error_summary,
)
from app.agents.provider_repair import (
    trim_repair_text as _trim_repair_text,
)
from app.agents.provider_repair import (
    validate_llm_output_with_local_projection as _validate_llm_output_with_local_projection,
)
from app.agents.provider_schema import (
    agent_intent_json_schema as _agent_intent_json_schema,
)
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    DisclosureMode,
    LLMAgentContractInput,
    LLMErrorSummary,
    LLMErrorType,
    LLMSchemaValidationError,
)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEEPSEEK_HOST = "api.deepseek.com"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
OPENAI_BACKEND_NAME = "openai"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
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
        self._api_key = (
            api_key
            if api_key is not None
            else os.getenv("OPENAI_API_KEY") or os.getenv(DEEPSEEK_API_KEY_ENV)
        )
        self._base_url = (
            base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or _default_base_url_from_env()
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

    @property
    def provider_name(self) -> str:
        return _provider_name_for_base_url(self._base_url)

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
        provider_payload_text = _provider_payload_json(contract_input)
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
                            "text": provider_payload_text,
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
        provider_payload_text = _provider_payload_json(contract_input)
        messages = [
            {
                "role": "system",
                "content": load_agent_system_prompt(),
            },
            {
                "role": "user",
                "content": provider_payload_text,
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
        provider_payload_text = _provider_payload_json(contract_input)
        request_payload = {
            "model": self._model,
            "instructions": load_agent_system_prompt(),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": provider_payload_text,
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


def _default_model_for_base_url(base_url: str) -> str:
    if _is_deepseek_base_url(base_url):
        return DEEPSEEK_DEFAULT_MODEL
    return DEFAULT_OPENAI_MODEL


def _default_base_url_from_env() -> str:
    if not os.getenv("OPENAI_API_KEY") and os.getenv(DEEPSEEK_API_KEY_ENV):
        return DEEPSEEK_BASE_URL
    return DEFAULT_OPENAI_BASE_URL


def _provider_name_for_base_url(base_url: str) -> str:
    if _is_deepseek_base_url(base_url):
        return "deepseek"
    if _is_default_openai_base_url(base_url):
        return "openai"
    return "openai-compatible"


def _is_default_openai_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    return base_url.rstrip("/") + "/" == DEFAULT_OPENAI_BASE_URL.rstrip("/") + "/"


def _api_style_from_env(base_url: str | None = None) -> str:
    value = os.getenv(LLM_API_STYLE_ENV, "").strip().lower().replace("-", "_")
    if value in {"chat", "chat_completion"}:
        return LLM_API_STYLE_CHAT_COMPLETIONS
    if value in {LLM_API_STYLE_RESPONSES, LLM_API_STYLE_CHAT_COMPLETIONS}:
        return value
    if value in {"", LLM_API_STYLE_AUTO} and _is_deepseek_base_url(base_url):
        return LLM_API_STYLE_CHAT_COMPLETIONS
    if value == LLM_API_STYLE_AUTO:
        return LLM_API_STYLE_AUTO
    return LLM_API_STYLE_AUTO


def _is_deepseek_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    try:
        return urlparse(base_url).hostname == DEEPSEEK_HOST
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


def _provider_payload_json(contract_input: LLMAgentContractInput) -> str:
    return json.dumps(
        build_llm_provider_payload(contract_input),
        ensure_ascii=False,
    )


