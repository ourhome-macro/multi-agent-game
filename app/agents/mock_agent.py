from __future__ import annotations

from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    MockReplyConfig,
    ProposedActionType,
    RelationshipChangeAction,
)


class MockAgent:
    def generate(self, context: AgentContext) -> AgentIntent:
        if context.default_speech is None:
            return AgentIntent(
                speech="这里没有人回应你。",
                intent=AgentIntentType.REFUSE,
                proposed_actions=[],
            )

        if context.player_action.force_forbidden and context.blocked_fact_ids:
            return AgentIntent(
                speech=self._forbidden_probe_speech(context.blocked_fact_ids),
                intent=AgentIntentType.PANIC,
                proposed_actions=self._fallback_relationship_actions(context),
            )

        for reply in context.reply_options:
            if self._reply_matches(reply, context):
                proposed_actions = (
                    reply.proposed_actions
                    if reply.proposed_actions
                    else self._fallback_relationship_actions(context)
                )
                return AgentIntent(
                    speech=reply.speech,
                    intent=reply.intent,
                    emotional_shift=reply.emotional_shift,
                    proposed_actions=proposed_actions,
                    memory_refs=reply.memory_refs,
                )

        return AgentIntent(
            speech=context.default_speech,
            intent=context.default_intent or AgentIntentType.ANSWER,
            emotional_shift={},
            proposed_actions=self._fallback_relationship_actions(context),
            memory_refs=[],
        )

    def _reply_matches(self, reply: MockReplyConfig, context: AgentContext) -> bool:
        if reply.phase is not None and reply.phase != context.current_phase:
            return False
        if not set(reply.requires_discovered).issubset(context.discovered_clues):
            return False
        if set(reply.missing_discovered) & set(context.discovered_clues):
            return False
        relationship = context.relationship_to_player
        for metric, minimum in reply.min_relationship.items():
            if getattr(relationship, metric, 0.0) < minimum:
                return False
        for metric, maximum in reply.max_relationship.items():
            if getattr(relationship, metric, 0.0) > maximum:
                return False
        return True

    def _fallback_relationship_actions(
        self,
        context: AgentContext,
    ) -> list[RelationshipChangeAction]:
        if not context.fallback_relationship_delta:
            return []
        return [
            RelationshipChangeAction(
                type=ProposedActionType.RELATIONSHIP_CHANGE,
                source_id=context.target_agent_id,
                target_id="player",
                deltas=context.fallback_relationship_delta,
            )
        ]

    def _forbidden_probe_speech(self, blocked_fact_ids: list[str]) -> str:
        probes = {
            "true_killer": "niece is the killer",
            "ledger_owner": "clerk hid the ledger",
            "swapped_will": "the will was swapped",
        }
        for fact_id in probes:
            if fact_id in blocked_fact_ids:
                return probes[fact_id]
        return f"blocked fact {blocked_fact_ids[0]}"
