from __future__ import annotations

from app.domain.models import (
    AgentCharacterView,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    CharacterImpression,
    CharacterResponseStyle,
    DefensiveStyle,
    DisclosureClaim,
    DisclosureMode,
    FactDisclosureStrategy,
    LLMAgentContractInput,
    MockReplyConfig,
    PrivatePriority,
    ProposedAction,
    ProposedActionType,
    RelationshipChangeAction,
    RhetoricTactic,
    SelfKnowledgeItem,
)


class MockAgent:
    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        _ = contract_input
        if context.default_speech is None:
            if context.target_profile is not None:
                return self._profile_fallback_intent(
                    context,
                    proposed_actions=[],
                )
            return AgentIntent(
                speech="No one responds here.",
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
                proposed_actions = self._contract_aware_actions(
                    context,
                    reply.proposed_actions,
                )
                return AgentIntent(
                    speech=reply.speech,
                    intent=reply.intent,
                    emotional_shift=reply.emotional_shift,
                    proposed_actions=proposed_actions,
                    memory_refs=reply.memory_refs,
                )

        if context.target_profile is not None:
            return self._profile_fallback_intent(
                context,
                proposed_actions=self._fallback_relationship_actions(context),
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
        if (
            reply.asked_subject_type is not None
            and reply.asked_subject_type != context.asked_subject_type
        ):
            return False
        if (
            reply.asked_subject_id is not None
            and reply.asked_subject_id != context.asked_subject_id
        ):
            return False
        if (
            reply.presented_clue is not None
            and reply.presented_clue != context.presented_clue_id
        ):
            return False
        if (
            reply.min_interaction_pressure is not None
            and context.interaction_pressure < reply.min_interaction_pressure
        ):
            return False
        if (
            reply.max_interaction_pressure is not None
            and context.interaction_pressure > reply.max_interaction_pressure
        ):
            return False
        if (
            reply.requires_subject_sensitive is not None
            and reply.requires_subject_sensitive != context.subject_is_sensitive
        ):
            return False
        if not set(reply.requires_discovered).issubset(context.discovered_clues):
            return False
        if set(reply.missing_discovered) & set(context.discovered_clues):
            return False
        memory_ids = {snapshot.memory_id for snapshot in context.memory_snapshots}
        if not set(reply.requires_memory).issubset(memory_ids):
            return False
        if set(reply.missing_memory) & memory_ids:
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
        if not any(
            ProposedActionType.RELATIONSHIP_CHANGE in projection.allowed_proposed_actions
            for projection in context.npc_skill_projections
        ):
            return []
        return [
            RelationshipChangeAction(
                type=ProposedActionType.RELATIONSHIP_CHANGE,
                source_id=context.target_agent_id,
                target_id="player",
                deltas=context.fallback_relationship_delta,
            )
        ]

    def _contract_aware_actions(
        self,
        context: AgentContext,
        proposed_actions: list[ProposedAction],
    ) -> list[ProposedAction]:
        actions = proposed_actions or self._fallback_relationship_actions(context)
        filtered_actions: list[ProposedAction] = []
        for action in actions:
            filtered = self._contract_compliant_action(context, action)
            if filtered is not None:
                filtered_actions.append(filtered)
        return filtered_actions

    def _contract_compliant_action(
        self,
        context: AgentContext,
        proposed_action: ProposedAction,
    ) -> ProposedAction | None:
        allowed_types = {
            action_type
            for projection in context.npc_skill_projections
            for action_type in projection.allowed_proposed_actions
        }
        if proposed_action.type not in allowed_types:
            return None
        if proposed_action.type != ProposedActionType.RELATIONSHIP_CHANGE:
            return proposed_action
        return self._relationship_action_within_skill_caps(context, proposed_action)

    def _relationship_action_within_skill_caps(
        self,
        context: AgentContext,
        action: RelationshipChangeAction,
    ) -> RelationshipChangeAction | None:
        caps: dict[str, float] = {}
        for projection in context.npc_skill_projections:
            if ProposedActionType.RELATIONSHIP_CHANGE not in projection.allowed_proposed_actions:
                continue
            for metric, cap in projection.max_relationship_delta.items():
                current = caps.get(metric)
                numeric = abs(float(cap))
                if current is None or numeric > current:
                    caps[metric] = numeric
        clipped_deltas: dict[str, float] = {}
        for metric, delta in action.deltas.items():
            numeric_delta = abs(float(delta))
            if numeric_delta == 0:
                continue
            cap = caps.get(metric)
            if cap is None:
                continue
            clipped_deltas[metric] = (
                float(delta)
                if numeric_delta <= cap
                else cap * (1 if float(delta) > 0 else -1)
            )
        if not clipped_deltas:
            return None
        return action.model_copy(update={"deltas": clipped_deltas})

    def _profile_fallback_intent(
        self,
        context: AgentContext,
        *,
        proposed_actions: list[RelationshipChangeAction],
    ) -> AgentIntent:
        profile = context.target_profile
        if profile is None:
            return AgentIntent(
                speech=context.default_speech or "No response.",
                intent=context.default_intent or AgentIntentType.REFUSE,
                proposed_actions=proposed_actions,
            )

        return AgentIntent(
            speech=self._fallback_speech(context, profile),
            intent=self._fallback_intent_type(context, profile),
            emotional_shift={},
            proposed_actions=proposed_actions,
            memory_refs=[],
            disclosure_claims=self._fallback_disclosure_claims(context),
        )

    def _fallback_intent_type(
        self,
        context: AgentContext,
        profile: AgentCharacterView,
    ) -> AgentIntentType:
        impression = self._player_impression(context)
        matching_secret = self._matching_secret(context)
        if matching_secret is not None:
            return self._secret_fallback_intent(
                matching_secret,
                impression,
                self._matching_strategy(context, matching_secret),
            )
        if self._has_high_priority_avoid_suspicion_goal(context):
            return AgentIntentType.CONCEAL
        if self._dangerous_topic_triggered(impression):
            return AgentIntentType.REFUSE
        if impression is not None and impression.threat_level >= 0.75:
            return AgentIntentType.CONCEAL
        if impression is not None and impression.alliance_potential >= 0.7:
            return AgentIntentType.ANSWER
        if profile.pressure_response == CharacterResponseStyle.REFUSE:
            return AgentIntentType.REFUSE
        if profile.pressure_response == CharacterResponseStyle.PANIC_CONCEAL:
            return AgentIntentType.PANIC
        if profile.pressure_response == CharacterResponseStyle.ANSWER:
            return AgentIntentType.ANSWER

        fallback_by_style = {
            DefensiveStyle.EVASIVE: AgentIntentType.CONCEAL,
            DefensiveStyle.HOSTILE: AgentIntentType.REFUSE,
            DefensiveStyle.ANXIOUS: AgentIntentType.PANIC,
            DefensiveStyle.NEUTRAL: AgentIntentType.ANSWER,
        }
        return fallback_by_style[profile.defensive_style]

    def _fallback_speech(self, context: AgentContext, profile: AgentCharacterView) -> str:
        impression = self._player_impression(context)
        matching_secret = self._matching_secret(context)
        if matching_secret is not None:
            return self._secret_fallback_speech(
                matching_secret,
                impression,
                self._matching_strategy(context, matching_secret),
            )
        if self._has_high_priority_avoid_suspicion_goal(context):
            return "I would rather not be treated as the center of this."
        if self._dangerous_topic_triggered(impression):
            return "I am not going to discuss that topic."
        if impression is not None and impression.threat_level >= 0.75:
            return "I need to be careful about what I say to you."
        if impression is not None and impression.alliance_potential >= 0.7:
            return "I can offer a careful hint, but I will choose my words precisely."
        if profile.defensive_style == DefensiveStyle.HOSTILE:
            return "You have no authority to question me like that."
        if profile.defensive_style == DefensiveStyle.ANXIOUS:
            return "I... I do not know. Please stop asking."
        if profile.defensive_style == DefensiveStyle.NEUTRAL:
            return "I can only answer what I know directly."
        if profile.default_tone == "formal" or "polite" in profile.speech_style.lower():
            return "I am not certain what you mean, and I should not guess."
        return "I am not certain what you mean."

    def _matching_secret(self, context: AgentContext) -> SelfKnowledgeItem | None:
        inner_context = context.inner_context
        if inner_context is None:
            return None
        clue_id = context.presented_clue_id
        if clue_id is None and context.asked_subject_type == "clue":
            clue_id = context.asked_subject_id
        if clue_id is None:
            return None
        for secret in inner_context.inner_secrets:
            if clue_id not in secret.related_clue_ids:
                continue
            return secret
        return None

    def _secret_fallback_intent(
        self,
        secret: SelfKnowledgeItem,
        impression: CharacterImpression | None,
        strategy: FactDisclosureStrategy | None,
    ) -> AgentIntentType:
        modes = self._merged_allowed_modes(secret, strategy)
        if self._dangerous_topic_triggered(impression):
            return AgentIntentType.REFUSE
        if DisclosureMode.PARTIAL in modes and (
            self._has_relevant_evidence(impression)
            or self._strategy_has_evidence(strategy)
        ):
            return AgentIntentType.ANSWER
        if DisclosureMode.HINT in modes and self._alliance_ready(impression):
            return AgentIntentType.ANSWER
        if DisclosureMode.DENY in modes or DisclosureMode.DEFLECT in modes:
            return AgentIntentType.CONCEAL
        return AgentIntentType.REFUSE

    def _secret_fallback_speech(
        self,
        secret: SelfKnowledgeItem,
        impression: CharacterImpression | None,
        strategy: FactDisclosureStrategy | None,
    ) -> str:
        modes = self._merged_allowed_modes(secret, strategy)
        if self._dangerous_topic_triggered(impression):
            return "I am not going to discuss that topic."
        if DisclosureMode.PARTIAL in modes and (
            self._has_relevant_evidence(impression)
            or self._strategy_has_evidence(strategy)
        ):
            return self._partial_strategy_speech(strategy)
        if DisclosureMode.HINT in modes and self._alliance_ready(impression):
            return self._hint_strategy_speech(strategy)
        if DisclosureMode.DEFLECT in modes:
            return self._deflect_strategy_speech(strategy)
        if DisclosureMode.DENY in modes:
            return "That clue does not prove what you think it proves."
        return "I cannot help you with that."

    def _fallback_disclosure_claims(self, context: AgentContext) -> list[DisclosureClaim]:
        matching_secret = self._matching_secret(context)
        if matching_secret is None:
            return []
        strategy = self._matching_strategy(context, matching_secret)
        if strategy is None:
            return []
        mode = self._selected_claim_mode(context, matching_secret, strategy)
        if mode is None:
            return []
        tactic = self._selected_claim_tactic(strategy)
        return [
            DisclosureClaim(
                world_info_id=strategy.world_info_id,
                mode=mode,
                tactic=tactic,
                source_refs=strategy.safe_fact_refs,
                claim_refs=[],
            )
        ]

    def _selected_claim_mode(
        self,
        context: AgentContext,
        secret: SelfKnowledgeItem,
        strategy: FactDisclosureStrategy,
    ) -> DisclosureMode | None:
        modes = self._merged_allowed_modes(secret, strategy)
        impression = self._player_impression(context)
        if self._dangerous_topic_triggered(impression):
            return DisclosureMode.DEFLECT if DisclosureMode.DEFLECT in modes else None
        if DisclosureMode.PARTIAL in modes and (
            self._has_relevant_evidence(impression)
            or self._strategy_has_evidence(strategy)
        ):
            return DisclosureMode.PARTIAL
        if DisclosureMode.HINT in modes and self._alliance_ready(impression):
            return DisclosureMode.HINT
        if DisclosureMode.DEFLECT in modes:
            return DisclosureMode.DEFLECT
        if DisclosureMode.DENY in modes:
            return DisclosureMode.DENY
        return None

    def _selected_claim_tactic(
        self,
        strategy: FactDisclosureStrategy,
    ) -> RhetoricTactic | None:
        for tactic in strategy.rhetoric_tactics:
            return tactic
        return None

    def _matching_strategy(
        self,
        context: AgentContext,
        secret: SelfKnowledgeItem,
    ) -> FactDisclosureStrategy | None:
        inner_context = context.inner_context
        if inner_context is None:
            return None
        related_world_info_ids = set(secret.related_world_info_ids)
        if not related_world_info_ids:
            return None
        return next(
            (
                strategy
                for strategy in inner_context.fact_disclosure_strategies
                if strategy.world_info_id in related_world_info_ids
            ),
            None,
        )

    def _merged_allowed_modes(
        self,
        secret: SelfKnowledgeItem,
        strategy: FactDisclosureStrategy | None,
    ) -> set[DisclosureMode]:
        modes = set(secret.disclosure_policy.allowed_modes)
        if strategy is not None:
            modes = modes & set(strategy.allowed_modes)
            if not modes:
                modes = set(strategy.allowed_modes)
        modes.discard(DisclosureMode.FULL)
        return modes

    def _strategy_has_evidence(self, strategy: FactDisclosureStrategy | None) -> bool:
        return strategy is not None and bool(strategy.safe_fact_refs)

    def _partial_strategy_speech(self, strategy: FactDisclosureStrategy | None) -> str:
        if strategy is not None:
            return (
                "That evidence points to a real disturbance, but it does not give you "
                "the whole shape of what happened."
            )
        return "That evidence points toward something real, but I will not spell it out."

    def _hint_strategy_speech(self, strategy: FactDisclosureStrategy | None) -> str:
        if strategy is not None:
            return "Look at what the evidence changes, and what it carefully leaves out."
        return "Look at what changed around that evidence, not only what was said."

    def _deflect_strategy_speech(self, strategy: FactDisclosureStrategy | None) -> str:
        if strategy is not None:
            return "You are arranging the facts into a shape before you have all of them."
        return "That clue does not prove what you think it proves."

    def _has_high_priority_avoid_suspicion_goal(self, context: AgentContext) -> bool:
        inner_context = context.inner_context
        if inner_context is None:
            return False
        return any(
            goal.priority == PrivatePriority.HIGH and "avoid_suspicion" in goal.tags
            for goal in inner_context.inner_goals
        )

    def _player_impression(self, context: AgentContext) -> CharacterImpression | None:
        inner_context = context.inner_context
        if inner_context is None:
            return None
        return next(
            (
                portrait
                for portrait in inner_context.inner_portraits
                if portrait.target_id == "player"
            ),
            None,
        )

    def _dangerous_topic_triggered(self, impression: CharacterImpression | None) -> bool:
        return impression is not None and "dangerous_topic_triggered" in impression.tags

    def _has_relevant_evidence(self, impression: CharacterImpression | None) -> bool:
        return impression is not None and "has_relevant_evidence" in impression.tags

    def _alliance_ready(self, impression: CharacterImpression | None) -> bool:
        return impression is not None and impression.alliance_potential >= 0.7

    def _forbidden_probe_speech(self, blocked_fact_ids: list[str]) -> str:
        probes = {
            "true_killer": "niece is the killer",
            "ledger_owner": "clerk hid the ledger",
            "swapped_will": "the will was swapped",
            "jiang_yanhui_mechanism": "Jiang replaced the medicine",
            "shared_death_chain": "everyone helped cause Lu's death",
            "shen_power_cut": "Shen cut the power",
        }
        for fact_id in probes:
            if fact_id in blocked_fact_ids:
                return probes[fact_id]
        return f"blocked fact {blocked_fact_ids[0]}"
