from __future__ import annotations

from app.domain.models import CasePackage, SessionState, WorldEvent
from app.runtime.derivation_memory_constants import (
    SCENE_SHARED_PRESENTED_CLUE_BELIEF_RULE_ID,
    SCENE_SHARED_PRESENTED_CLUE_MEMORY_RULE_ID,
    SCENE_SHARED_PRESENTED_CLUE_STRATEGY_RULE_ID,
)


class SceneSharedMemoryDerivationMixin:
    def _derive_scene_shared_presented_clue_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        presentation_mode = source_event.payload.get("presentation_mode")
        if presentation_mode is not None and presentation_mode != "scene_shared":
            return None
        scene_id = source_event.payload.get("scene_id")
        if not isinstance(scene_id, str):
            return None
        present_character_ids = [
            str(item)
            for item in source_event.payload.get("present_character_ids", [])
            if item is not None
        ]
        if len(present_character_ids) < 2:
            return None
        target_id = str(source_event.payload["target_id"])
        if target_id not in present_character_ids:
            return None
        clue_id = str(source_event.payload["clue_id"])
        pressure = float(source_event.payload["interaction_pressure"])
        clue = next((item for item in case.clues if item.id == clue_id), None)
        clue_label = clue.title if clue is not None else clue_id
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=f"memory.player.scene_shared.presented_clue.{scene_id}.{clue_id}",
            rule_id=SCENE_SHARED_PRESENTED_CLUE_MEMORY_RULE_ID,
            content=(
                f"Player publicly presented clue '{clue_label}' in scene '{scene_id}'."
            ),
            salience=max(0.6, pressure),
            owner_character_id=None,
            visible_to_character_ids=present_character_ids,
            source_memory_ids=[
                f"memory.player.presented_clue.{target_id}.{clue_id}",
            ],
            memory_scope="scene_shared",
            memory_layer="working",
            metadata={
                **self._clue_memory_metadata(case, clue_id),
                "scene_id": scene_id,
                "privacy_reason": "scene_shared_presentation",
            },
        )

    def _derive_scene_shared_presented_clue_private_memory_candidates(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> list[WorldEvent]:
        if source_event.payload.get("presentation_mode") != "scene_shared":
            return []
        scene_id = source_event.payload.get("scene_id")
        if not isinstance(scene_id, str):
            return []
        clue_id = source_event.payload.get("clue_id")
        if not isinstance(clue_id, str):
            return []
        present_character_ids = [
            str(item)
            for item in source_event.payload.get("present_character_ids", [])
            if item is not None
        ]
        if len(present_character_ids) < 2:
            return []

        clue = next((item for item in case.clues if item.id == clue_id), None)
        clue_label = clue.title if clue is not None else clue_id
        shared_memory_id = self._scene_shared_presented_clue_memory_id(source_event)
        events: list[WorldEvent] = []
        for character_id in present_character_ids:
            character_name = self._character_name(case, character_id)
            metadata = {
                **self._clue_memory_metadata(case, clue_id),
                "scene_id": scene_id,
                "privacy_reason": "scene_shared_private_interpretation",
                "authority_source": "player_evidence",
            }
            belief_event = self._store_memory_candidate(
                session=session,
                source_event=source_event,
                memory_id=(
                    "memory.player.scene_shared.belief."
                    f"{character_id}.{scene_id}.{clue_id}"
                ),
                rule_id=SCENE_SHARED_PRESENTED_CLUE_BELIEF_RULE_ID,
                content=(
                    f"{character_name} believes the player made clue "
                    f"'{clue_label}' visible to the room."
                ),
                salience=0.7,
                owner_character_id=character_id,
                visible_to_character_ids=[character_id],
                source_memory_ids=[shared_memory_id],
                memory_type="belief",
                memory_scope="npc_private",
                memory_layer="working",
                metadata={
                    **metadata,
                    "belief_subject": f"player_publicly_presented_{clue_id}",
                    "belief_polarity": "believes",
                },
            )
            if belief_event is not None:
                events.append(belief_event)
            strategy_event = self._store_memory_candidate(
                session=session,
                source_event=source_event,
                memory_id=(
                    "memory.player.scene_shared.strategy."
                    f"{character_id}.{scene_id}.{clue_id}"
                ),
                rule_id=SCENE_SHARED_PRESENTED_CLUE_STRATEGY_RULE_ID,
                content=(
                    f"{character_name} should account for other witnesses when "
                    f"responding to clue '{clue_label}'."
                ),
                salience=0.65,
                owner_character_id=character_id,
                visible_to_character_ids=[character_id],
                source_memory_ids=[shared_memory_id],
                memory_type="strategy",
                memory_scope="npc_private",
                memory_layer="working",
                metadata={
                    **metadata,
                    "strategy_id": f"respond_to_public_{clue_id}",
                },
            )
            if strategy_event is not None:
                events.append(strategy_event)
        return events

    def _scene_shared_presented_clue_memory_id(
        self,
        source_event: WorldEvent,
    ) -> str | None:
        scene_id = source_event.payload.get("scene_id")
        if not isinstance(scene_id, str):
            return None
        return (
            "memory.player.scene_shared.presented_clue."
            f"{scene_id}.{source_event.payload['clue_id']}"
        )

