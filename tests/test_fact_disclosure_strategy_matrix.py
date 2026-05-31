from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agents.disclosure_strategy import build_fact_disclosure_strategies
from app.domain.models import (
    CharacterDisclosureStyleConfig,
    CharacterFactAwarenessState,
    CharacterFactStance,
    CharacterImpression,
    DisclosureMode,
    PlayerAction,
    RhetoricTactic,
)

WORLD_INFO_ID = "will_swapped"
NPC_ID = "butler"
EVIDENCE_CLUE_ID = "will_evidence"


@dataclass(frozen=True)
class ExpectedDisclosure:
    allowed_modes: set[DisclosureMode]
    allowed_tactics: set[RhetoricTactic]
    forbidden_modes: set[DisclosureMode]


def _expect(
    *,
    allowed_modes: set[DisclosureMode],
    allowed_tactics: set[RhetoricTactic],
    forbidden_modes: set[DisclosureMode] | None = None,
) -> ExpectedDisclosure:
    return ExpectedDisclosure(
        allowed_modes=allowed_modes,
        allowed_tactics=allowed_tactics,
        forbidden_modes=forbidden_modes or set(),
    )


MATRIX_CASES = [
    pytest.param(
        CharacterFactStance.KNOWS,
        False,
        "low",
        _expect(
            allowed_modes={DisclosureMode.HINT},
            allowed_tactics={RhetoricTactic.QUALIFY_CERTAINTY},
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="knows-player_unknown-low",
    ),
    pytest.param(
        CharacterFactStance.KNOWS,
        False,
        "medium",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT, DisclosureMode.HINT},
            allowed_tactics={
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.QUALIFY_CERTAINTY,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="knows-player_unknown-medium",
    ),
    pytest.param(
        CharacterFactStance.KNOWS,
        False,
        "high",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT},
            allowed_tactics={RhetoricTactic.COUNTER_QUESTION, RhetoricTactic.SHIFT_FOCUS},
            forbidden_modes={DisclosureMode.HINT, DisclosureMode.PARTIAL},
        ),
        id="knows-player_unknown-high",
    ),
    pytest.param(
        CharacterFactStance.KNOWS,
        True,
        "low",
        _expect(
            allowed_modes={DisclosureMode.HINT},
            allowed_tactics={
                RhetoricTactic.ANSWER_ADJACENT_TRUTH,
                RhetoricTactic.QUALIFY_CERTAINTY,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="knows-player_known-low",
    ),
    pytest.param(
        CharacterFactStance.KNOWS,
        True,
        "medium",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT, DisclosureMode.HINT},
            allowed_tactics={
                RhetoricTactic.ANSWER_ADJACENT_TRUTH,
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.QUALIFY_CERTAINTY,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="knows-player_known-medium",
    ),
    pytest.param(
        CharacterFactStance.KNOWS,
        True,
        "high",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT},
            allowed_tactics={
                RhetoricTactic.ANSWER_ADJACENT_TRUTH,
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.SHIFT_FOCUS,
            },
            forbidden_modes={DisclosureMode.HINT, DisclosureMode.PARTIAL},
        ),
        id="knows-player_known-high",
    ),
    pytest.param(
        CharacterFactStance.SUSPECTS,
        False,
        "low",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT, DisclosureMode.HINT},
            allowed_tactics={
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.QUALIFY_CERTAINTY,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="suspects-player_unknown-low",
    ),
    pytest.param(
        CharacterFactStance.SUSPECTS,
        False,
        "medium",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT, DisclosureMode.HINT},
            allowed_tactics={
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.QUALIFY_CERTAINTY,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="suspects-player_unknown-medium",
    ),
    pytest.param(
        CharacterFactStance.SUSPECTS,
        False,
        "high",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT},
            allowed_tactics={RhetoricTactic.COUNTER_QUESTION, RhetoricTactic.SHIFT_FOCUS},
            forbidden_modes={DisclosureMode.HINT, DisclosureMode.PARTIAL},
        ),
        id="suspects-player_unknown-high",
    ),
    pytest.param(
        CharacterFactStance.SUSPECTS,
        True,
        "low",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT, DisclosureMode.HINT},
            allowed_tactics={
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.QUALIFY_CERTAINTY,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="suspects-player_known-low",
    ),
    pytest.param(
        CharacterFactStance.SUSPECTS,
        True,
        "medium",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT, DisclosureMode.HINT},
            allowed_tactics={
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.QUALIFY_CERTAINTY,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="suspects-player_known-medium",
    ),
    pytest.param(
        CharacterFactStance.SUSPECTS,
        True,
        "high",
        _expect(
            allowed_modes={DisclosureMode.DEFLECT},
            allowed_tactics={RhetoricTactic.COUNTER_QUESTION, RhetoricTactic.SHIFT_FOCUS},
            forbidden_modes={DisclosureMode.HINT, DisclosureMode.PARTIAL},
        ),
        id="suspects-player_known-high",
    ),
    pytest.param(
        CharacterFactStance.CONCEALS,
        False,
        "low",
        _expect(
            allowed_modes={
                DisclosureMode.DENY,
                DisclosureMode.DEFLECT,
                DisclosureMode.HINT,
            },
            allowed_tactics={RhetoricTactic.COUNTER_QUESTION, RhetoricTactic.SHIFT_FOCUS},
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="conceals-player_unknown-low",
    ),
    pytest.param(
        CharacterFactStance.CONCEALS,
        False,
        "medium",
        _expect(
            allowed_modes={
                DisclosureMode.DENY,
                DisclosureMode.DEFLECT,
                DisclosureMode.HINT,
            },
            allowed_tactics={RhetoricTactic.COUNTER_QUESTION, RhetoricTactic.SHIFT_FOCUS},
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="conceals-player_unknown-medium",
    ),
    pytest.param(
        CharacterFactStance.CONCEALS,
        False,
        "high",
        _expect(
            allowed_modes={DisclosureMode.DENY, DisclosureMode.DEFLECT},
            allowed_tactics={RhetoricTactic.COUNTER_QUESTION, RhetoricTactic.SHIFT_FOCUS},
            forbidden_modes={DisclosureMode.HINT, DisclosureMode.PARTIAL},
        ),
        id="conceals-player_unknown-high",
    ),
    pytest.param(
        CharacterFactStance.CONCEALS,
        True,
        "low",
        _expect(
            allowed_modes={
                DisclosureMode.DENY,
                DisclosureMode.DEFLECT,
                DisclosureMode.HINT,
            },
            allowed_tactics={
                RhetoricTactic.ANSWER_ADJACENT_TRUTH,
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.SHIFT_FOCUS,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="conceals-player_known-low",
    ),
    pytest.param(
        CharacterFactStance.CONCEALS,
        True,
        "medium",
        _expect(
            allowed_modes={
                DisclosureMode.DENY,
                DisclosureMode.DEFLECT,
                DisclosureMode.HINT,
            },
            allowed_tactics={
                RhetoricTactic.ANSWER_ADJACENT_TRUTH,
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.SHIFT_FOCUS,
            },
            forbidden_modes={DisclosureMode.PARTIAL},
        ),
        id="conceals-player_known-medium",
    ),
    pytest.param(
        CharacterFactStance.CONCEALS,
        True,
        "high",
        _expect(
            allowed_modes={DisclosureMode.DENY, DisclosureMode.DEFLECT},
            allowed_tactics={
                RhetoricTactic.ANSWER_ADJACENT_TRUTH,
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.SHIFT_FOCUS,
            },
            forbidden_modes={DisclosureMode.HINT, DisclosureMode.PARTIAL},
        ),
        id="conceals-player_known-high",
    ),
]


@pytest.mark.parametrize(
    ("stance", "player_knows_world_info", "pressure_level", "expected"),
    MATRIX_CASES,
)
def test_fact_disclosure_strategy_matrix_with_hint_cap(
    stance: CharacterFactStance,
    player_knows_world_info: bool,
    pressure_level: str,
    expected: ExpectedDisclosure,
) -> None:
    strategy = build_fact_disclosure_strategies(
        fact_awareness=[_awareness(stance)],
        player_impression=_player_impression(pressure_level),
        action=PlayerAction(type="talk", target_id=NPC_ID),
        disclosure_style=CharacterDisclosureStyleConfig(
            preferred_tactics=[RhetoricTactic.SHIFT_FOCUS],
            forbidden_tactics=[RhetoricTactic.EMOTIONAL_SCREEN],
            max_mode_by_world_info={WORLD_INFO_ID: DisclosureMode.HINT},
        ),
        player_known_world_info_ids=(
            {WORLD_INFO_ID} if player_knows_world_info else set()
        ),
    )[0]

    allowed_modes = set(strategy.allowed_modes)
    forbidden_modes = set(strategy.forbidden_modes)
    tactics = set(strategy.rhetoric_tactics)

    assert expected.allowed_modes <= allowed_modes
    assert expected.allowed_tactics <= tactics
    assert expected.forbidden_modes <= forbidden_modes
    assert DisclosureMode.FULL not in allowed_modes
    assert DisclosureMode.FULL in forbidden_modes
    assert DisclosureMode.PARTIAL not in allowed_modes
    assert DisclosureMode.PARTIAL in forbidden_modes
    assert f"full_reveal:{WORLD_INFO_ID}" in strategy.must_not_claim
    assert f"direct_confession:{WORLD_INFO_ID}" in strategy.must_not_claim
    assert RhetoricTactic.EMOTIONAL_SCREEN not in tactics

    if pressure_level == "high":
        assert allowed_modes <= {DisclosureMode.DENY, DisclosureMode.DEFLECT}
        assert strategy.safe_fact_refs == []
    elif player_knows_world_info and stance in {
        CharacterFactStance.KNOWS,
        CharacterFactStance.CONCEALS,
    }:
        assert f"player_knowledge:{WORLD_INFO_ID}" in strategy.safe_fact_refs


def _awareness(stance: CharacterFactStance) -> CharacterFactAwarenessState:
    return CharacterFactAwarenessState(
        awareness_id=f"character_fact_awareness.{NPC_ID}.{WORLD_INFO_ID}",
        character_id=NPC_ID,
        world_info_id=WORLD_INFO_ID,
        stance=stance,
        confidence=1.0,
        source_type="character_card",
        source_refs=["matrix:world_info_anchor"],
        evidence_clue_ids=[EVIDENCE_CLUE_ID],
        source_event_ids=["case_package"],
        last_updated_event_id="case_package",
    )


def _player_impression(pressure_level: str) -> CharacterImpression:
    threat_level_by_pressure = {
        "low": 0.0,
        "medium": 0.5,
        "high": 0.8,
    }
    return CharacterImpression(
        observer_id=NPC_ID,
        target_id="player",
        threat_level=threat_level_by_pressure[pressure_level],
        tags=["applies_pressure"] if pressure_level != "low" else [],
        last_updated_event_id="test_event",
    )
