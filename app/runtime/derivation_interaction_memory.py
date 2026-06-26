from __future__ import annotations

from app.domain.models import CasePackage, EventType, SessionState, WorldEvent
from app.runtime.derivation_memory_constants import (
    ASKED_ABOUT_MEMORY_RULE_ID,
    DIRECTOR_BLOCK_MEMORY_RULE_ID,
    PRESENTED_CLUE_MEMORY_RULE_ID,
    RELATIONSHIP_THRESHOLD_MEMORY_RULE_ID,
)
from app.runtime.memory_derivations import resolve_memory_derivation_effects


class InteractionMemoryDerivationMixin:
    def _derive_relationship_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        source_id = str(source_event.payload["source_id"])
        metric = str(source_event.payload["metric"])
        state_name = str(source_event.payload["state"])
        character_name = next(
            (item.display_name for item in case.characters if item.id == source_id),
            source_id,
        )
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=(
                "memory.player.relationship_threshold."
                f"{source_id}.player.{metric}.{state_name}"
            ),
            rule_id=RELATIONSHIP_THRESHOLD_MEMORY_RULE_ID,
            content=f"{character_name} became {state_name} toward the player ({metric}).",
            salience=0.7,
            owner_character_id=source_id,
            visible_to_character_ids=[source_id],
        )

    def _derive_director_block_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        target_id = str(source_event.payload["target_id"])
        character_name = next(
            (item.display_name for item in case.characters if item.id == target_id),
            target_id,
        )
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=(
                "memory.player.director_blocked."
                f"{target_id}.{source_event.payload.get('blocked_fact_id', 'unknown')}"
            ),
            rule_id=DIRECTOR_BLOCK_MEMORY_RULE_ID,
            content=f"Conversation with {character_name} was blocked by narrative rules.",
            salience=0.9,
            owner_character_id=None,
            visible_to_character_ids=[],
            memory_scope="director_audit",
            memory_layer="working",
        )

    def _derive_asked_about_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        target_id = str(source_event.payload["target_id"])
        target_name = self._character_name(case, target_id)
        subject_type = str(source_event.payload["subject_type"])
        subject_id = str(source_event.payload["subject_id"])
        pressure = float(source_event.payload["interaction_pressure"])
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=f"memory.player.asked_about.{target_id}.{subject_type}.{subject_id}",
            rule_id=ASKED_ABOUT_MEMORY_RULE_ID,
            content=(
                f"Player asked {target_name} about {subject_type} '{subject_id}' "
                f"with pressure {pressure}."
            ),
            salience=max(0.4, pressure),
            owner_character_id=target_id,
            visible_to_character_ids=[target_id],
            metadata=self._default_memory_metadata(case, source_event),
        )

    def _derive_presented_clue_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        target_id = str(source_event.payload["target_id"])
        target_name = self._character_name(case, target_id)
        clue_id = str(source_event.payload["clue_id"])
        pressure = float(source_event.payload["interaction_pressure"])
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=f"memory.player.presented_clue.{target_id}.{clue_id}",
            rule_id=PRESENTED_CLUE_MEMORY_RULE_ID,
            content=(
                f"Player pressured {target_name} with clue '{clue_id}' "
                f"at pressure {pressure}."
            ),
            salience=max(0.6, pressure),
            owner_character_id=target_id,
            visible_to_character_ids=[target_id],
            metadata={
                **self._clue_memory_metadata(case, clue_id),
                "privacy_reason": "private_presentation",
            },
        )

    def _configured_event_created_memory(
        self,
        events: list[WorldEvent],
        memory_id: str | None,
    ) -> bool:
        if memory_id is None:
            return False
        return any(
            event.type == EventType.MEMORY_CANDIDATE_CREATED
            and event.payload.get("memory_id") == memory_id
            for event in events
        )

    def _asked_about_memory_id(self, source_event: WorldEvent) -> str:
        return (
            "memory.player.asked_about."
            f"{source_event.payload['target_id']}."
            f"{source_event.payload['subject_type']}."
            f"{source_event.payload['subject_id']}"
        )

    def _presented_clue_memory_id(self, source_event: WorldEvent) -> str:
        return (
            "memory.player.presented_clue."
            f"{source_event.payload['target_id']}."
            f"{source_event.payload['clue_id']}"
        )

    def _derive_configured_memory_candidates(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        for resolved_effect in resolve_memory_derivation_effects(case, source_event):
            effect = resolved_effect.effect
            event = self._store_memory_candidate(
                session=session,
                source_event=source_event,
                memory_id=effect.memory_id,
                rule_id=resolved_effect.rule_id,
                memory_type=effect.memory_type,
                memory_scope=effect.memory_scope,
                memory_layer=effect.memory_layer,
                operation=effect.operation,
                subject_id=effect.subject_id,
                content=effect.content,
                salience=effect.salience,
                owner_character_id=effect.owner_character_id,
                visible_to_character_ids=effect.visible_to_character_ids,
                source_event_ids=effect.source_event_ids,
                source_memory_ids=effect.source_memory_ids,
                confidence=effect.confidence,
                metadata={
                    **self._default_memory_metadata(case, source_event),
                    **effect.metadata,
                },
            )
            if event is not None:
                events.append(event)
        return events

    def _default_memory_metadata(
        self,
        case: CasePackage,
        source_event: WorldEvent,
    ) -> dict[str, object]:
        clue_id = source_event.payload.get("clue_id")
        if source_event.type == EventType.PLAYER_ASKED_ABOUT:
            subject_type = source_event.payload.get("subject_type")
            subject_id = source_event.payload.get("subject_id")
            clue_id = subject_id if subject_type == "clue" else None
        if not isinstance(clue_id, str):
            return {}

        metadata = self._clue_memory_metadata(case, clue_id)
        if source_event.type == EventType.PLAYER_PRESENTED_CLUE:
            metadata.setdefault("privacy_reason", "private_presentation")
            scene_id = source_event.payload.get("scene_id")
            if isinstance(scene_id, str):
                metadata["scene_id"] = scene_id
                metadata["privacy_reason"] = "scene_shared_presentation"
        return metadata

