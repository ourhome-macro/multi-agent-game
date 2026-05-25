from __future__ import annotations

from app.domain.models import (
    AgentIntent,
    AgentIntentType,
    CasePackage,
    PlayerAction,
    ProposedActionType,
    RelationshipChangeAction,
)


class MockAgent:
    def generate(self, case: CasePackage, action: PlayerAction) -> AgentIntent:
        dialogue = next(
            (
                item
                for item in case.mock_dialogues
                if item.character_id == action.target_id
            ),
            None,
        )
        character = next(
            (item for item in case.characters if item.id == action.target_id),
            None,
        )

        if dialogue is None or character is None:
            return AgentIntent(
                speech="这里没有人回应你。",
                intent=AgentIntentType.REFUSE,
                proposed_actions=[],
            )

        speech = (
            dialogue.forbidden_test_speech
            if action.force_forbidden and dialogue.forbidden_test_speech
            else dialogue.default_speech
        )

        proposed_actions = []
        if dialogue.relationship_delta_on_talk:
            proposed_actions.append(
                RelationshipChangeAction(
                    type=ProposedActionType.RELATIONSHIP_CHANGE,
                    source=action.target_id,
                    target="player",
                    deltas=dialogue.relationship_delta_on_talk,
                )
            )

        return AgentIntent(
            speech=speech,
            intent=dialogue.default_intent,
            emotional_shift={},
            proposed_actions=proposed_actions,
            memory_refs=[],
        )
