from __future__ import annotations

from typing import Protocol

from app.domain.models import (
    CasePackage,
    CharacterImpression,
    EventType,
    SessionState,
    WorldEvent,
)
from app.runtime.derivation_utils import append_unique, clamp01, clamp_relationship
from app.runtime.events import EventRecorder
from app.runtime.memory_derivations import resolve_memory_impression_effects


class _HasRecorder(Protocol):
    _recorder: EventRecorder


class CharacterImpressionDerivationMixin(_HasRecorder):
    def _derive_character_impression(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        observer_id = self._impression_observer_id(case, source_event)
        if observer_id is None:
            return None

        target_id = "player"
        current = session.character_impressions.get(observer_id, {}).get(target_id)
        if current is not None and source_event.id in current.source_event_ids:
            return None

        impression = (
            current.model_copy(deep=True)
            if current is not None
            else CharacterImpression(
                observer_id=observer_id,
                target_id=target_id,
                personality_impression="The player is still being evaluated.",
                perceived_motive="Unknown.",
                trust_boundary="Keep disclosures bounded by evidence and narrative rules.",
                last_updated_event_id=source_event.id,
            )
        )
        self._apply_impression_signal(impression, source_event)
        self._apply_rule_impression_effects(impression, case, source_event)
        if source_event.id not in impression.source_event_ids:
            impression.source_event_ids.append(source_event.id)
        impression.confidence = clamp01(impression.confidence + 0.1)

        event = self._recorder.append(
            session,
            actor_id="character_impression_system",
            event_type=EventType.CHARACTER_IMPRESSION_UPDATED,
            payload=impression.model_dump(mode="json"),
            caused_by_event_id=source_event.id,
        )
        impression.last_updated_event_id = event.id
        event.payload = impression.model_dump(mode="json")
        session.character_impressions.setdefault(observer_id, {})[target_id] = impression
        return event

    def _impression_observer_id(
        self,
        case: CasePackage,
        source_event: WorldEvent,
    ) -> str | None:
        character_ids = {character.id for character in case.characters}
        if source_event.type in {
            EventType.PLAYER_ASKED_ABOUT,
            EventType.PLAYER_PRESENTED_CLUE,
            EventType.PLAYER_ACCUSED,
            EventType.ACCUSATION_EVALUATED,
            EventType.DIRECTOR_BLOCKED,
        }:
            observer_id = str(source_event.payload.get("target_id", ""))
            return observer_id if observer_id in character_ids else None
        if source_event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
            observer_id = str(source_event.payload.get("source_id", ""))
            target_id = str(source_event.payload.get("target_id", ""))
            if target_id == "player" and observer_id in character_ids:
                return observer_id
        return None

    def _apply_impression_signal(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        if source_event.type == EventType.PLAYER_ASKED_ABOUT:
            self._apply_asked_about_impression(impression, source_event)
            return
        if source_event.type == EventType.PLAYER_PRESENTED_CLUE:
            self._apply_presented_clue_impression(impression, source_event)
            return
        if source_event.type == EventType.PLAYER_ACCUSED:
            self._apply_player_accused_impression(impression, source_event)
            return
        if source_event.type == EventType.ACCUSATION_EVALUATED:
            self._apply_accusation_evaluated_impression(impression, source_event)
            return
        if source_event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
            self._apply_relationship_threshold_impression(impression, source_event)
            return
        if source_event.type == EventType.DIRECTOR_BLOCKED:
            impression.personality_impression = (
                "The player can push the conversation into unsafe territory."
            )
            impression.perceived_motive = "Testing boundaries around restricted facts."
            append_unique(impression.suspicious_points, "director_blocked")
            append_unique(impression.tags, "unsafe_boundary_probe")
            append_unique(impression.tags, "dangerous_topic_triggered")
            impression.threat_level = clamp01(impression.threat_level + 0.2)
            impression.manipulation_risk = clamp01(impression.manipulation_risk + 0.1)
            impression.trust_boundary = "Avoid unsafe disclosures and stay within public facts."

    def _apply_asked_about_impression(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        subject_type = str(source_event.payload["subject_type"])
        subject_id = str(source_event.payload["subject_id"])
        pressure = float(source_event.payload["interaction_pressure"])
        impression.personality_impression = "The player asks targeted investigative questions."
        impression.perceived_motive = "Testing what the NPC knows about case references."
        append_unique(impression.suspicious_points, f"asked_about.{subject_type}.{subject_id}")
        append_unique(impression.tags, "targeted_questioning")
        if self._append_optional_knowledge_ref(impression, source_event):
            append_unique(impression.tags, "has_relevant_evidence")
        impression.threat_level = clamp01(impression.threat_level + 0.1 + pressure * 0.2)
        impression.usefulness = clamp01(impression.usefulness + 0.1)
        if pressure >= 0.6:
            append_unique(impression.tags, "applies_pressure")
            impression.manipulation_risk = clamp01(impression.manipulation_risk + 0.05)
        impression.trust_boundary = "Answer only within disclosed player knowledge."

    def _apply_presented_clue_impression(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        clue_id = str(source_event.payload["clue_id"])
        pressure = float(source_event.payload["interaction_pressure"])
        impression.personality_impression = (
            "The player is evidence-driven and willing to pressure NPCs."
        )
        impression.perceived_motive = "Testing contradictions with discovered evidence."
        append_unique(impression.suspicious_points, f"presented_clue.{clue_id}")
        append_unique(impression.tags, "evidence_pressure")
        if self._append_optional_knowledge_ref(impression, source_event):
            append_unique(impression.tags, "has_relevant_evidence")
        impression.threat_level = clamp01(impression.threat_level + 0.2 + pressure * 0.2)
        impression.manipulation_risk = clamp01(impression.manipulation_risk + 0.15)
        impression.usefulness = clamp01(impression.usefulness + 0.15)
        impression.trust_boundary = "Avoid direct admissions unless evidence rules allow it."

    def _apply_player_accused_impression(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        claim_id = str(source_event.payload["claim_id"])
        impression.personality_impression = "The player is willing to make formal accusations."
        impression.perceived_motive = "Trying to force a formal case judgment."
        append_unique(impression.suspicious_points, f"accused.{claim_id}")
        append_unique(impression.tags, "formal_accusation")
        append_unique(impression.tags, "has_relevant_evidence")
        for clue_id in source_event.payload.get("evidence_clue_ids", []):
            append_unique(impression.suspected_knowledge_refs, str(clue_id))
        impression.threat_level = clamp01(impression.threat_level + 0.35)
        impression.manipulation_risk = clamp01(impression.manipulation_risk + 0.1)
        impression.usefulness = clamp01(impression.usefulness + 0.2)
        impression.trust_boundary = "Do not volunteer extra facts under accusation pressure."

    def _apply_accusation_evaluated_impression(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        result = str(source_event.payload["result"])
        claim_id = str(source_event.payload["claim_id"])
        append_unique(impression.suspicious_points, f"accusation_evaluated.{claim_id}.{result}")
        append_unique(impression.tags, f"accusation_{result}")
        impression.perceived_motive = "Seeking case resolution through formal claims."
        if result == "correct":
            impression.personality_impression = "The player can assemble decisive evidence."
            impression.threat_level = clamp01(impression.threat_level + 0.45)
            impression.usefulness = clamp01(impression.usefulness + 0.25)
            impression.trust_boundary = "Assume the player can connect evidence accurately."
        else:
            impression.personality_impression = "The player may overreach with partial evidence."
            impression.manipulation_risk = clamp01(impression.manipulation_risk + 0.2)

    def _apply_relationship_threshold_impression(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        metric = str(source_event.payload["metric"])
        state = str(source_event.payload["state"])
        append_unique(impression.suspicious_points, f"relationship_threshold.{metric}.{state}")
        append_unique(impression.tags, "relationship_threshold")
        append_unique(impression.tags, f"{metric}_{state}")
        if metric == "trust":
            impression.alliance_potential = clamp01(impression.alliance_potential + 0.3)
            impression.usefulness = clamp01(impression.usefulness + 0.2)
            impression.trust_boundary = "Limited cooperation is possible."
            return
        if metric == "suspicion":
            impression.threat_level = clamp01(impression.threat_level + 0.2)
            impression.manipulation_risk = clamp01(impression.manipulation_risk + 0.1)
            impression.trust_boundary = "Keep answers guarded around sensitive topics."
            return
        if metric == "fear":
            impression.threat_level = clamp01(impression.threat_level + 0.25)
            impression.trust_boundary = "Avoid escalation and disclose only safe fragments."

    def _append_optional_knowledge_ref(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> bool:
        appended = False
        knowledge_id = source_event.payload.get("knowledge_id")
        if isinstance(knowledge_id, str):
            append_unique(impression.suspected_knowledge_refs, knowledge_id)
            appended = True
        clue_id = source_event.payload.get("clue_id")
        if isinstance(clue_id, str):
            append_unique(impression.suspected_knowledge_refs, clue_id)
            append_unique(impression.suspected_knowledge_refs, f"player_knowledge.{clue_id}")
            appended = True
        world_info_id = source_event.payload.get("world_info_id")
        if isinstance(world_info_id, str):
            append_unique(impression.suspected_knowledge_refs, world_info_id)
            appended = True
        return appended

    def _apply_rule_impression_effects(
        self,
        impression: CharacterImpression,
        case: CasePackage,
        source_event: WorldEvent,
    ) -> None:
        for resolved in resolve_memory_impression_effects(case, source_event):
            effect = resolved.impression
            for metric, delta in effect.relationship_delta.items():
                if metric == "suspicion":
                    impression.suspicion = clamp_relationship(impression.suspicion + delta)
                elif metric == "trust":
                    impression.trust = clamp_relationship(impression.trust + delta)
                elif metric == "fear":
                    impression.fear = clamp_relationship(impression.fear + delta)
            if effect.strategy_id is not None:
                impression.current_strategy = effect.strategy_id
            for trait, delta in effect.traits.items():
                impression.traits[trait] = clamp01(
                    impression.traits.get(trait, 0.0) + delta
                )
            for memory_id in resolved.produced_memory_ids:
                append_unique(impression.source_memory_ids, memory_id)
