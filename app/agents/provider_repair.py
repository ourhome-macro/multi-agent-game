from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.agents.llm_contract import (
    LLMAgentPolicyViolationError,
    LLMAgentSchemaError,
    validate_llm_agent_output,
)
from app.agents.provider_schema import RELATIONSHIP_DELTA_METRICS
from app.domain.models import (
    AgentIntent,
    AgentIntentType,
    DisclosureMode,
    LLMAgentContractInput,
    LLMAgentOutputContract,
    LLMDisclosureConstraint,
    ProposedActionType,
)


def trim_repair_text(text: str, *, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def json_error_summary(exc: json.JSONDecodeError) -> str:
    return f"{exc.msg} at line {exc.lineno} column {exc.colno}"


def schema_error_summary(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if not errors:
            return f"{exc.error_count()} validation errors"
        first_error = errors[0]
        error_type = str(first_error.get("type", "unknown"))
        return f"{exc.error_count()} validation errors; first_error_type={error_type}"
    message = str(exc).splitlines()[0]
    return message[:160]


def validate_llm_output_with_local_projection(
    payload: dict[str, Any],
    contract_input: LLMAgentContractInput,
) -> AgentIntent:
    projected = project_and_validate_llm_output(payload, contract_input)
    if projected is not None:
        return projected
    try:
        return validate_llm_agent_output(payload, contract_input)
    except LLMAgentPolicyViolationError as exc:
        projected = project_and_validate_llm_output(
            payload,
            contract_input,
            error=exc,
        )
        if projected is None:
            raise
        return projected
    except (LLMAgentSchemaError, ValidationError):
        projected = project_and_validate_llm_output(payload, contract_input)
        if projected is None:
            raise
        return projected


def project_and_validate_llm_output(
    payload: dict[str, Any],
    contract_input: LLMAgentContractInput,
    *,
    error: Exception | None = None,
) -> AgentIntent | None:
    if error is not None and "narrative phase changes" in str(error):
        return None
    if not isinstance(payload.get("speech"), str):
        return None
    projected = contract_repair_projection(payload, contract_input=contract_input)
    if projected == payload:
        return None
    try:
        return validate_llm_agent_output(projected, contract_input)
    except (ValidationError, LLMAgentSchemaError, LLMAgentPolicyViolationError):
        return None


def contract_repair_projection(
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


def allowed_disclosure_mode_matrix(contract_input: LLMAgentContractInput) -> str:
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


def relationship_delta_cap_matrix(contract_input: LLMAgentContractInput) -> str:
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
