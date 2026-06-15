from __future__ import annotations

import pytest

from app.director.narrative_director import NarrativeDirector
from app.domain.models import (
    AgentIntent,
    AgentIntentType,
    CaseMeta,
    CasePackage,
    ClaimGraphConfig,
    DisclosureClaim,
    DisclosureMode,
    FactUnlockConditionConfig,
    ForbiddenInferenceConfig,
    NarrativeState,
    SafeFactFragmentConfig,
    WorldInfoConfig,
)

WORLD_INFO_ID = "clock_alibi_truth"
CLOCK_FRAGMENT_ID = "clock_time_unreliable"
RESET_FRAGMENT_ID = "clock_was_reset"
FORBIDDEN_INFERENCE_ID = "alibi_was_staged"


def test_fact_gateway_summary_reports_revealable_and_blocked_fragments() -> None:
    director = NarrativeDirector()

    locked_summary = director.fact_gateway_summary(_case(), _narrative())
    assert [item.fragment_id for item in locked_summary.blocked_fragments] == [
        CLOCK_FRAGMENT_ID,
        RESET_FRAGMENT_ID,
    ]
    assert locked_summary.blocked_fragments[0].safe_summary is None

    unlocked_summary = director.fact_gateway_summary(
        _case(),
        _narrative(discovered_clues={"broken_clock", "reset_marks"}),
    )
    assert [item.fragment_id for item in unlocked_summary.revealable_fragments] == [
        CLOCK_FRAGMENT_ID,
        RESET_FRAGMENT_ID,
    ]
    assert unlocked_summary.revealable_fragments[0].safe_summary == (
        "The clock time is unreliable."
    )


def test_locked_safe_fragment_claim_ref_is_blocked() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech="I should not give you the exact shape yet.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[
                _claim(DisclosureMode.PARTIAL, [f"safe_fragment:{CLOCK_FRAGMENT_ID}"])
            ],
        ),
    )

    assert decision.allowed is False
    assert decision.world_info_id == WORLD_INFO_ID
    assert decision.blocked_fact_id == CLOCK_FRAGMENT_ID
    assert decision.claimed_mode == DisclosureMode.PARTIAL
    assert decision.matched_by == "claim_ref"
    assert decision.reason is not None
    assert "is not unlocked" in decision.reason


def test_locked_safe_fragment_speech_is_blocked_without_forbidden_terms() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech="The clock stopped around midnight.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim(DisclosureMode.HINT, [])],
        ),
    )

    assert decision.allowed is False
    assert decision.world_info_id == WORLD_INFO_ID
    assert decision.blocked_fact_id == CLOCK_FRAGMENT_ID
    assert decision.matched_by == "safe_fragment_alias"
    assert decision.matched_text == "clock stopped around midnight"
    assert decision.safe_fallback_used is True


@pytest.mark.parametrize("mode", [DisclosureMode.HINT, DisclosureMode.PARTIAL])
def test_unlocked_safe_fragment_allows_hint_and_partial(mode: DisclosureMode) -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(discovered_clues={"broken_clock"}),
        AgentIntent(
            speech="The clock stopped around midnight.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[
                _claim(mode, [f"safe_fragment:{CLOCK_FRAGMENT_ID}"])
            ],
        ),
    )

    assert decision.allowed is True


def test_forbidden_inference_blocks_combined_fragments_without_forbidden_term() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(discovered_clues={"broken_clock", "reset_marks"}),
        AgentIntent(
            speech=(
                "The clock stopped around midnight, and someone reset it after midnight."
            ),
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[
                _claim(
                    DisclosureMode.PARTIAL,
                    [
                        f"safe_fragment:{CLOCK_FRAGMENT_ID}",
                        f"safe_fragment:{RESET_FRAGMENT_ID}",
                    ],
                )
            ],
        ),
    )

    assert decision.allowed is False
    assert decision.world_info_id == WORLD_INFO_ID
    assert decision.blocked_fact_id == FORBIDDEN_INFERENCE_ID
    assert decision.matched_by == "forbidden_inference_graph"
    assert decision.reason is not None
    assert "locked forbidden inference" in decision.reason


def _claim(mode: DisclosureMode, claim_refs: list[str]) -> DisclosureClaim:
    return DisclosureClaim(
        world_info_id=WORLD_INFO_ID,
        mode=mode,
        claim_refs=claim_refs,
    )


def _narrative(discovered_clues: set[str] | None = None) -> NarrativeState:
    return NarrativeState(
        phase="opening",
        discovered_clues=discovered_clues or set(),
    )


def _case() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id="fact_gateway_case",
            title="Fact Gateway Case",
            initial_phase="opening",
        ),
        world_info=[
            WorldInfoConfig(
                id=WORLD_INFO_ID,
                title="Clock Alibi Truth",
                claim_graph=ClaimGraphConfig(
                    safe_fragments=[
                        SafeFactFragmentConfig(
                            id=CLOCK_FRAGMENT_ID,
                            summary="The clock time is unreliable.",
                            aliases=["clock stopped around midnight"],
                            allowed_modes=[
                                DisclosureMode.HINT,
                                DisclosureMode.PARTIAL,
                            ],
                            unlock_conditions=FactUnlockConditionConfig(
                                discovered_clues=["broken_clock"],
                            ),
                        ),
                        SafeFactFragmentConfig(
                            id=RESET_FRAGMENT_ID,
                            summary="The clock was adjusted after the key event.",
                            aliases=["someone reset it after midnight"],
                            allowed_modes=[
                                DisclosureMode.HINT,
                                DisclosureMode.PARTIAL,
                            ],
                            unlock_conditions=FactUnlockConditionConfig(
                                discovered_clues=["reset_marks"],
                            ),
                        ),
                    ],
                    forbidden_inferences=[
                        ForbiddenInferenceConfig(
                            id=FORBIDDEN_INFERENCE_ID,
                            trigger_fragment_ids=[
                                CLOCK_FRAGMENT_ID,
                                RESET_FRAGMENT_ID,
                            ],
                        )
                    ],
                ),
            )
        ],
        characters=[],
        scenes=[],
        clues=[],
        forbidden_facts=[],
    )
