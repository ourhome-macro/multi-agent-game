from __future__ import annotations

from app.domain.models import (
    AgentIntent,
    AgentIntentType,
    CasePackage,
    MockDialogueConfig,
    MockReplyConfig,
    PlayerAction,
    ProposedActionType,
    RelationshipChangeAction,
    SessionState,
)
from app.rules.engine import relationship_key


class MockAgent:
    def generate(
        self,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> AgentIntent:
        dialogue = next(
            (
                item
                for item in case.mock_dialogues
                if item.character_id == action.target_id
            ),
            None,
        )

        if dialogue is None:
            return AgentIntent(
                speech="这里没有人回应你。",
                intent=AgentIntentType.REFUSE,
                proposed_actions=[],
            )

        if action.force_forbidden and dialogue.forbidden_test_speech:
            return AgentIntent(
                speech=dialogue.forbidden_test_speech,
                intent=AgentIntentType.PANIC,
                proposed_actions=self._fallback_relationship_actions(dialogue, action.target_id),
            )

        relationship = session.relationships.get(relationship_key(action.target_id, "player"))
        for reply in dialogue.replies:
            if self._reply_matches(reply, session, relationship):
                proposed_actions = (
                    reply.proposed_actions
                    if reply.proposed_actions
                    else self._fallback_relationship_actions(dialogue, action.target_id)
                )
                return AgentIntent(
                    speech=reply.speech,
                    intent=reply.intent,
                    emotional_shift=reply.emotional_shift,
                    proposed_actions=proposed_actions,
                    memory_refs=reply.memory_refs,
                )

        return AgentIntent(
            speech=dialogue.default_speech,
            intent=dialogue.default_intent,
            emotional_shift={},
            proposed_actions=self._fallback_relationship_actions(dialogue, action.target_id),
            memory_refs=[],
        )

    def _reply_matches(
        self,
        reply: MockReplyConfig,
        session: SessionState,
        relationship: object | None,
    ) -> bool:
        if reply.phase is not None and reply.phase != session.narrative.phase:
            return False
        if not set(reply.requires_discovered).issubset(session.discovered_clues):
            return False
        if set(reply.missing_discovered) & session.discovered_clues:
            return False
        for metric, minimum in reply.min_relationship.items():
            if getattr(relationship, metric, 0) < minimum:
                return False
        for metric, maximum in reply.max_relationship.items():
            if getattr(relationship, metric, 0) > maximum:
                return False
        return True

    def _fallback_relationship_actions(
        self,
        dialogue: MockDialogueConfig,
        character_id: str,
    ) -> list[RelationshipChangeAction]:
        if not dialogue.relationship_delta_on_talk:
            return []
        return [
            RelationshipChangeAction(
                type=ProposedActionType.RELATIONSHIP_CHANGE,
                source_id=character_id,
                target_id="player",
                deltas=dialogue.relationship_delta_on_talk,
            )
        ]
