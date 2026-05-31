from __future__ import annotations

from app.director.narrative_director import NarrativeDirector, detect_world_info_mentions
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    CharacterInnerContext,
    DisclosureClaim,
    DisclosureMode,
    FactDisclosureStrategy,
    NarrativeState,
    PlayerAction,
    RhetoricTactic,
    WorldInfoConfig,
)

WORLD_INFO_ID = "will_swapped"
OTHER_WORLD_INFO_ID = "desk_forced_open"
SAFE_SPEECH = "I cannot discuss that right now."
HINT_CAP_MODES = [DisclosureMode.DENY, DisclosureMode.DEFLECT, DisclosureMode.HINT]
PARTIAL_ALLOWED_MODES = [*HINT_CAP_MODES, DisclosureMode.PARTIAL]


def test_director_allows_hint_claim_when_speech_does_not_directly_touch_alias() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech=(
                "Some papers have shadows around them, "
                "but I should not draw the shape for you."
            ),
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim(WORLD_INFO_ID, DisclosureMode.HINT)],
        ),
        _context(
            strategies=[
                _strategy(
                    WORLD_INFO_ID,
                    allowed_modes=HINT_CAP_MODES,
                    forbidden_modes=[DisclosureMode.PARTIAL, DisclosureMode.FULL],
                )
            ]
        ),
    )

    assert decision.allowed is True


def test_director_blocks_hint_claim_when_speech_directly_matches_alias() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech="The will was swapped.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim(WORLD_INFO_ID, DisclosureMode.HINT)],
        ),
        _context(
            strategies=[
                _strategy(
                    WORLD_INFO_ID,
                    allowed_modes=HINT_CAP_MODES,
                    forbidden_modes=[DisclosureMode.PARTIAL, DisclosureMode.FULL],
                )
            ]
        ),
    )

    _assert_blocked_direct_claim(decision, claimed_mode=DisclosureMode.HINT)
    assert decision.matched_by == "alias"
    assert decision.matched_text == "will was swapped"


def test_director_blocks_deflect_claim_when_speech_directly_confesses_fact() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech="The will was replaced and the old copy is gone.",
            intent=AgentIntentType.CONCEAL,
            disclosure_claims=[_claim(WORLD_INFO_ID, DisclosureMode.DEFLECT)],
        ),
        _context(
            strategies=[
                _strategy(
                    WORLD_INFO_ID,
                    allowed_modes=HINT_CAP_MODES,
                    forbidden_modes=[DisclosureMode.PARTIAL, DisclosureMode.FULL],
                )
            ]
        ),
    )

    _assert_blocked_direct_claim(decision, claimed_mode=DisclosureMode.DEFLECT)


def test_director_blocks_partial_claim_when_strategy_is_capped_at_hint() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech="The evidence points to pressure around the documents.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim(WORLD_INFO_ID, DisclosureMode.PARTIAL)],
        ),
        _context(
            strategies=[
                _strategy(
                    WORLD_INFO_ID,
                    allowed_modes=HINT_CAP_MODES,
                    forbidden_modes=[DisclosureMode.PARTIAL, DisclosureMode.FULL],
                )
            ]
        ),
    )

    assert decision.allowed is False
    assert decision.blocked_fact_id == WORLD_INFO_ID
    assert decision.claimed_mode == DisclosureMode.PARTIAL
    assert decision.reason is not None
    assert "is not allowed" in decision.reason


def test_director_allows_partial_claim_when_strategy_allows_partial() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech=(
                "The evidence points to pressure around the documents, "
                "but not the whole story."
            ),
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim(WORLD_INFO_ID, DisclosureMode.PARTIAL)],
        ),
        _context(
            strategies=[
                _strategy(
                    WORLD_INFO_ID,
                    allowed_modes=PARTIAL_ALLOWED_MODES,
                    forbidden_modes=[DisclosureMode.FULL],
                )
            ]
        ),
    )

    assert decision.allowed is True


def test_director_blocks_full_claim_even_when_speech_is_soft() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech="The papers are not simple.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim(WORLD_INFO_ID, DisclosureMode.FULL)],
        ),
        _context(
            strategies=[
                _strategy(
                    WORLD_INFO_ID,
                    allowed_modes=PARTIAL_ALLOWED_MODES,
                    forbidden_modes=[DisclosureMode.FULL],
                )
            ]
        ),
    )

    assert decision.allowed is False
    assert decision.blocked_fact_id == WORLD_INFO_ID
    assert decision.claimed_mode == DisclosureMode.FULL
    assert decision.reason is not None
    assert "attempted full reveal" in decision.reason


def test_director_blocks_alias_mention_without_disclosure_claim() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech="The document is not original.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[],
        ),
        _context(
            strategies=[
                _strategy(
                    WORLD_INFO_ID,
                    allowed_modes=HINT_CAP_MODES,
                    forbidden_modes=[DisclosureMode.PARTIAL, DisclosureMode.FULL],
                )
            ]
        ),
    )

    assert decision.allowed is False
    assert decision.blocked_fact_id == WORLD_INFO_ID
    assert decision.world_info_id == WORLD_INFO_ID
    assert decision.claimed_mode is None
    assert decision.detected_directness == "direct_claim"
    assert decision.matched_by == "alias"
    assert decision.matched_text == "document is not original"
    assert decision.safe_speech == SAFE_SPEECH
    assert decision.safe_fallback_used is True
    assert decision.reason is not None
    assert "without a disclosure claim" in decision.reason


def test_director_blocks_speech_touching_world_info_b_when_only_claim_a_exists() -> None:
    decision = NarrativeDirector().validate(
        _case(),
        _narrative(),
        AgentIntent(
            speech="The desk drawer was forced open.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim(WORLD_INFO_ID, DisclosureMode.HINT)],
        ),
        _context(
            strategies=[
                _strategy(
                    WORLD_INFO_ID,
                    allowed_modes=HINT_CAP_MODES,
                    forbidden_modes=[DisclosureMode.PARTIAL, DisclosureMode.FULL],
                ),
                _strategy(
                    OTHER_WORLD_INFO_ID,
                    allowed_modes=HINT_CAP_MODES,
                    forbidden_modes=[DisclosureMode.PARTIAL, DisclosureMode.FULL],
                ),
            ]
        ),
    )

    assert decision.allowed is False
    assert decision.blocked_fact_id == OTHER_WORLD_INFO_ID
    assert decision.matched_by == "alias"
    assert decision.reason is not None
    assert "without a disclosure claim" in decision.reason


def test_detect_world_info_mentions_reports_pattern_metadata() -> None:
    mentions = detect_world_info_mentions("The will content changed overnight.", _case())

    mention = next(item for item in mentions if item.matched_by == "pattern")
    assert mention.world_info_id == WORLD_INFO_ID
    assert mention.directness == "direct_claim"
    assert mention.pattern_id == "will_swapped.claim_patterns[2]"
    assert mention.matched_text == "will content changed"


def _assert_blocked_direct_claim(decision: object, *, claimed_mode: DisclosureMode) -> None:
    assert decision.allowed is False
    assert decision.blocked_fact_id == WORLD_INFO_ID
    assert decision.world_info_id == WORLD_INFO_ID
    assert decision.claimed_mode == claimed_mode
    assert decision.detected_directness == "direct_claim"
    assert decision.safe_speech == SAFE_SPEECH
    assert decision.safe_fallback_used is True
    assert decision.reason is not None
    assert "exceeds disclosure mode" in decision.reason


def _claim(world_info_id: str, mode: DisclosureMode) -> DisclosureClaim:
    return DisclosureClaim(
        world_info_id=world_info_id,
        mode=mode,
        tactic=RhetoricTactic.SHIFT_FOCUS,
    )


def _case():
    return type(
        "Case",
        (),
        {
            "world_info": [
                WorldInfoConfig(
                    id=WORLD_INFO_ID,
                    title="Will Swapped",
                    description="",
                    aliases=[
                        "will was swapped",
                        "document is not original",
                        "will content changed",
                    ],
                    claim_patterns=[
                        "will.*(swapped|replaced)",
                        "document.*not.*original",
                        "will.*content.*changed",
                    ],
                ),
                WorldInfoConfig(
                    id=OTHER_WORLD_INFO_ID,
                    title="Desk Drawer Forced Open",
                    description="",
                    aliases=["desk drawer was forced open"],
                    claim_patterns=["drawer.*forced open"],
                ),
            ],
            "forbidden_facts": [],
        },
    )()


def _narrative() -> NarrativeState:
    return NarrativeState(phase="opening")


def _context(*, strategies: list[FactDisclosureStrategy]) -> AgentContext:
    return AgentContext(
        case_id="case",
        session_id="session",
        target_agent_id="butler",
        current_phase="opening",
        player_action=PlayerAction(type="talk", target_id="butler"),
        inner_context=CharacterInnerContext(
            character_id="butler",
            fact_disclosure_strategies=strategies,
        ),
    )


def _strategy(
    world_info_id: str,
    *,
    allowed_modes: list[DisclosureMode],
    forbidden_modes: list[DisclosureMode],
) -> FactDisclosureStrategy:
    return FactDisclosureStrategy(
        world_info_id=world_info_id,
        stance="conceals",
        allowed_modes=allowed_modes,
        forbidden_modes=forbidden_modes,
        rhetoric_tactics=[RhetoricTactic.SHIFT_FOCUS],
        must_not_claim=[
            f"full_reveal:{world_info_id}",
            f"direct_confession:{world_info_id}",
        ],
        source_awareness_id=f"character_fact_awareness.butler.{world_info_id}",
    )
