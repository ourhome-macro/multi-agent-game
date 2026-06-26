from __future__ import annotations

from typing import Any

from app.domain.models import (
    LLMAgentContractInput,
    LLMAgentOutputContract,
    LLMDisclosureConstraint,
)

RELATIONSHIP_DELTA_METRICS = [
    "trust",
    "suspicion",
    "fear",
    "intimacy",
    "hostility",
]


def agent_intent_json_schema(
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
