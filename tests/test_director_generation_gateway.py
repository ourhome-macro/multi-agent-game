from __future__ import annotations

import pytest

from app.agents.llm_contract import (
    LLMAgentPolicyViolationError,
    build_llm_agent_input,
    validate_llm_agent_output,
)
from app.director.narrative_director import NarrativeDirector
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    CaseMeta,
    CasePackage,
    CharacterFactStance,
    CharacterInnerContext,
    ClaimGraphConfig,
    DisclosureMode,
    FactDisclosureStrategy,
    FactUnlockConditionConfig,
    NarrativeState,
    PlayerAction,
    SafeFactFragmentConfig,
    WorldInfoConfig,
)

WORLD_INFO_ID = "clock_alibi_truth"
FRAGMENT_ID = "clock_time_unreliable"
FRAGMENT_REF = f"{WORLD_INFO_ID}.safe_fragment:{FRAGMENT_ID}"


def test_director_pre_generation_safe_fragment_enters_llm_contract() -> None:
    context = _context(discovered_clues=["broken_clock"])
    contract_input = build_llm_agent_input(context)
    constraint = next(
        item
        for item in contract_input.disclosure_constraints
        if item.item_id == WORLD_INFO_ID
    )

    assert [fragment.ref for fragment in constraint.safe_fragments] == [FRAGMENT_REF]
    assert FRAGMENT_REF in constraint.safe_fact_refs
    assert constraint.safe_fragments[0].summary == "The clock time is unreliable."
    assert constraint.safe_fragments[0].allowed_modes == [
        DisclosureMode.HINT,
        DisclosureMode.PARTIAL,
    ]


def test_partial_disclosure_requires_authorized_safe_fragment_ref() -> None:
    contract_input = build_llm_agent_input(_context(discovered_clues=["broken_clock"]))
    payload = AgentIntent(
        speech="The clock time is unreliable, but I will not say more.",
        intent=AgentIntentType.ANSWER,
        disclosure_claims=[
            {
                "world_info_id": WORLD_INFO_ID,
                "mode": DisclosureMode.PARTIAL,
                "claim_refs": [],
                "source_refs": [],
            }
        ],
    ).model_dump(mode="json", exclude={"llm_error"})

    with pytest.raises(LLMAgentPolicyViolationError, match="safe fragment"):
        validate_llm_agent_output(payload, contract_input)


def test_partial_disclosure_allows_authorized_safe_fragment_ref() -> None:
    contract_input = build_llm_agent_input(_context(discovered_clues=["broken_clock"]))
    payload = AgentIntent(
        speech="The clock time is unreliable, but I will not say more.",
        intent=AgentIntentType.ANSWER,
        disclosure_claims=[
            {
                "world_info_id": WORLD_INFO_ID,
                "mode": DisclosureMode.PARTIAL,
                "claim_refs": [FRAGMENT_REF],
                "source_refs": [],
            }
        ],
    ).model_dump(mode="json", exclude={"llm_error"})

    intent = validate_llm_agent_output(payload, contract_input)

    assert intent.disclosure_claims[0].claim_refs == [FRAGMENT_REF]


def test_locked_safe_fragment_is_not_projected_to_llm_contract() -> None:
    context = _context(discovered_clues=[])
    contract_input = build_llm_agent_input(context)
    constraint = next(
        item
        for item in contract_input.disclosure_constraints
        if item.item_id == WORLD_INFO_ID
    )

    assert constraint.safe_fragments == []
    assert FRAGMENT_REF not in constraint.safe_fact_refs


def _context(*, discovered_clues: list[str]) -> AgentContext:
    base_context = AgentContext(
        case_id="director_generation_gateway",
        session_id="session.director_generation_gateway",
        target_agent_id="butler",
        current_phase="opening",
        discovered_clues=discovered_clues,
        player_action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="What about the clock?",
        ),
        inner_context=CharacterInnerContext(
            character_id="butler",
            fact_disclosure_strategies=[
                FactDisclosureStrategy(
                    world_info_id=WORLD_INFO_ID,
                    stance=CharacterFactStance.KNOWS,
                    allowed_modes=[DisclosureMode.HINT, DisclosureMode.PARTIAL],
                    forbidden_modes=[DisclosureMode.FULL],
                    source_awareness_id="awareness.butler.clock_alibi_truth",
                )
            ],
        ),
    )
    safe_fragments = NarrativeDirector().safe_fragment_constraints(
        _case(),
        NarrativeState(
            phase="opening",
            discovered_clues=set(discovered_clues),
        ),
        base_context,
    )
    return base_context.model_copy(
        update={"director_safe_fragments": list(safe_fragments)}
    )


def _case() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id="director_generation_gateway",
            title="Director Generation Gateway",
            initial_phase="opening",
        ),
        world_info=[
            WorldInfoConfig(
                id=WORLD_INFO_ID,
                title="Clock Alibi Truth",
                claim_graph=ClaimGraphConfig(
                    safe_fragments=[
                        SafeFactFragmentConfig(
                            id=FRAGMENT_ID,
                            summary="The clock time is unreliable.",
                            aliases=["clock time is unreliable"],
                            allowed_modes=[
                                DisclosureMode.HINT,
                                DisclosureMode.PARTIAL,
                            ],
                            unlock_conditions=FactUnlockConditionConfig(
                                discovered_clues=["broken_clock"],
                            ),
                        )
                    ]
                ),
            )
        ],
        characters=[],
        scenes=[],
        clues=[],
        forbidden_facts=[],
    )
