from __future__ import annotations

from app.domain.models import (
    CasePackage,
    CharacterFactAwarenessSourceType,
    CharacterFactStance,
    CharacterImpression,
    EventType,
    MemoryCandidateState,
    PlayerKnowledgeAcquisition,
    PlayerKnowledgeSourceType,
    PlayerKnowledgeState,
    SessionState,
    WorldEvent,
)
from app.runtime.character_fact_awareness import upsert_character_fact_awareness
from app.runtime.events import EventRecorder
from app.runtime.memory_derivations import (
    MEDICINE_BELIEF_MEMORY_ID,
    MEDICINE_RELATIONSHIP_MEMORY_ID,
    MEDICINE_STRATEGY_ID,
    MEDICINE_STRATEGY_MEMORY_ID,
    MEDICINE_TOPIC_RULE_IDS,
    memory_derivation_rule_ids_for_event,
    resolve_memory_derivation_effects,
)

CLUE_DISCOVERED_MEMORY_RULE_ID = "memory_rule.core.clue_discovered.episodic.v1"
RELATIONSHIP_THRESHOLD_MEMORY_RULE_ID = (
    "memory_rule.core.relationship_threshold.episodic.v1"
)
DIRECTOR_BLOCK_MEMORY_RULE_ID = "memory_rule.core.director_block.episodic.v1"
ASKED_ABOUT_MEMORY_RULE_ID = "memory_rule.core.asked_about.episodic.v1"
PRESENTED_CLUE_MEMORY_RULE_ID = "memory_rule.core.presented_clue.episodic.v1"
SCENE_SHARED_PRESENTED_CLUE_MEMORY_RULE_ID = (
    "memory_rule.core.scene_shared_presented_clue.episodic.v1"
)
PLAYER_ACCUSED_MEMORY_RULE_ID = "memory_rule.core.player_accused.episodic.v1"
ACCUSATION_EVALUATED_MEMORY_RULE_ID = (
    "memory_rule.core.accusation_evaluated.episodic.v1"
)


class DerivedEventSystem:
    def __init__(self, recorder: EventRecorder) -> None:
        self._recorder = recorder

    def derive(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_events: list[WorldEvent],
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        for source_event in source_events:
            impression_event = self._derive_character_impression(case, session, source_event)
            if impression_event is not None:
                events.append(impression_event)
            if source_event.type == EventType.CLUE_DISCOVERED:
                knowledge_event = self._derive_player_knowledge(case, session, source_event)
                if knowledge_event is not None:
                    events.append(knowledge_event)
                memory_event = self._derive_clue_memory_candidate(case, session, source_event)
                if memory_event is not None:
                    events.append(memory_event)
            elif source_event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
                memory_event = self._derive_relationship_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
            elif source_event.type == EventType.DIRECTOR_BLOCKED:
                memory_event = self._derive_director_block_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
            elif source_event.type == EventType.PLAYER_ASKED_ABOUT:
                awareness_event = self._derive_character_awareness_from_asked_about(
                    case,
                    session,
                    source_event,
                )
                if awareness_event is not None:
                    events.append(awareness_event)
                memory_event = self._derive_asked_about_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
                events.extend(
                    self._derive_medicine_topic_typed_memory_candidates(
                        session=session,
                        source_event=source_event,
                    )
                )
            elif source_event.type == EventType.PLAYER_PRESENTED_CLUE:
                awareness_event = self._derive_character_awareness_from_presented_clue(
                    case,
                    session,
                    source_event,
                )
                if awareness_event is not None:
                    events.append(awareness_event)
                memory_event = self._derive_presented_clue_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
                memory_event = self._derive_scene_shared_presented_clue_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
                events.extend(
                    self._derive_medicine_topic_typed_memory_candidates(
                        session=session,
                        source_event=source_event,
                    )
                )
            elif source_event.type == EventType.PLAYER_ACCUSED:
                awareness_events = self._derive_character_awareness_from_accusation(
                    case,
                    session,
                    source_event,
                )
                events.extend(awareness_events)
                memory_event = self._derive_player_accused_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
            elif source_event.type == EventType.ACCUSATION_EVALUATED:
                memory_event = self._derive_accusation_evaluated_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
        return events

    def _derive_player_knowledge(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        clue_id = str(source_event.payload["clue_id"])
        clue = next((item for item in case.clues if item.id == clue_id), None)
        if clue is None:
            return None

        world_info_by_id = {item.id: item for item in case.world_info}
        world_info_id = next(
            (
                item_id
                for item_id in clue.reveals_world_info
                if item_id in world_info_by_id
            ),
            None,
        )
        knowledge_id = (
            f"player_knowledge.{world_info_id}"
            if world_info_id is not None
            else f"player_knowledge.{clue_id}"
        )
        if knowledge_id in session.player_knowledge:
            return None

        world_info = world_info_by_id.get(world_info_id) if world_info_id is not None else None
        title = world_info.title if world_info is not None else clue.title
        summary = world_info.description if world_info is not None else clue.description

        session.player_knowledge[knowledge_id] = PlayerKnowledgeState(
            knowledge_id=knowledge_id,
            clue_id=clue_id,
            world_info_id=world_info_id,
            confidence=1.0,
            acquisition=PlayerKnowledgeAcquisition.DISCOVERED,
            source_type=PlayerKnowledgeSourceType.CLUE,
            title=title,
            summary=summary,
            source_event_id=source_event.id,
        )
        return self._recorder.append(
            session,
            actor_id="derived_event_system",
            event_type=EventType.PLAYER_KNOWLEDGE_UPDATED,
            payload={
                "clue_id": clue_id,
                "world_info_id": world_info_id,
                "knowledge_id": knowledge_id,
                "confidence": 1.0,
                "acquisition": PlayerKnowledgeAcquisition.DISCOVERED.value,
                "source_type": PlayerKnowledgeSourceType.CLUE.value,
                "source_event_id": source_event.id,
                "title": title,
                "summary": summary,
            },
            caused_by_event_id=source_event.id,
        )

    def _derive_character_awareness_from_asked_about(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        subject_type = str(source_event.payload["subject_type"])
        if subject_type != "clue":
            return None
        clue_id = str(source_event.payload["subject_id"])
        world_info_ids = self._world_info_ids_for_clue(case, clue_id)
        if not world_info_ids:
            return None
        return upsert_character_fact_awareness(
            session=session,
            recorder=self._recorder,
            character_id=str(source_event.payload["target_id"]),
            world_info_id=world_info_ids[0],
            stance=CharacterFactStance.SUSPECTS,
            confidence=0.55,
            source_type=CharacterFactAwarenessSourceType.PLAYER_ASKED_ABOUT,
            source_refs=[f"clue:{clue_id}"],
            evidence_clue_ids=[clue_id],
            source_event=source_event,
        )

    def _derive_character_awareness_from_presented_clue(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        clue_id = str(source_event.payload["clue_id"])
        world_info_ids = self._world_info_ids_for_clue(case, clue_id)
        if not world_info_ids:
            return None
        return upsert_character_fact_awareness(
            session=session,
            recorder=self._recorder,
            character_id=str(source_event.payload["target_id"]),
            world_info_id=world_info_ids[0],
            stance=CharacterFactStance.KNOWS,
            confidence=0.85,
            source_type=CharacterFactAwarenessSourceType.PLAYER_PRESENTED_CLUE,
            source_refs=[f"clue:{clue_id}"],
            evidence_clue_ids=[clue_id],
            source_event=source_event,
        )

    def _derive_character_awareness_from_accusation(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        evidence_clue_ids = [
            str(item) for item in source_event.payload.get("evidence_clue_ids", [])
        ]
        for world_info_id in self._world_info_ids_for_clues(case, evidence_clue_ids):
            event = upsert_character_fact_awareness(
                session=session,
                recorder=self._recorder,
                character_id=str(source_event.payload["target_id"]),
                world_info_id=world_info_id,
                stance=CharacterFactStance.KNOWS,
                confidence=0.95,
                source_type=CharacterFactAwarenessSourceType.PLAYER_ACCUSED,
                source_refs=[f"claim:{source_event.payload['claim_id']}"],
                evidence_clue_ids=evidence_clue_ids,
                source_event=source_event,
            )
            if event is not None:
                events.append(event)
        return events

    def _world_info_ids_for_clue(self, case: CasePackage, clue_id: str) -> list[str]:
        clue = next((item for item in case.clues if item.id == clue_id), None)
        if clue is None:
            return []
        world_info_ids = {item.id for item in case.world_info}
        return [
            world_info_id
            for world_info_id in clue.reveals_world_info
            if world_info_id in world_info_ids
        ]

    def _world_info_ids_for_clues(
        self,
        case: CasePackage,
        clue_ids: list[str],
    ) -> list[str]:
        world_info_ids: list[str] = []
        for clue_id in clue_ids:
            for world_info_id in self._world_info_ids_for_clue(case, clue_id):
                _append_unique(world_info_ids, world_info_id)
        return world_info_ids

    def _derive_clue_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        clue_id = str(source_event.payload["clue_id"])
        clue = next((item for item in case.clues if item.id == clue_id), None)
        if clue is None:
            return None
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=f"memory.player.clue_discovered.{clue_id}",
            rule_id=CLUE_DISCOVERED_MEMORY_RULE_ID,
            content=f"Player discovered clue '{clue.title}'.",
            salience=0.8,
            owner_character_id=None,
            visible_to_character_ids=self._all_character_ids(case),
            memory_scope="case",
            memory_layer="core",
        )

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
        )

    def _derive_scene_shared_presented_clue_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
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
        )

    def _derive_medicine_topic_typed_memory_candidates(
        self,
        *,
        session: SessionState,
        source_event: WorldEvent,
    ) -> list[WorldEvent]:
        target_id = str(source_event.payload["target_id"])
        events: list[WorldEvent] = []
        for resolved_effect in resolve_memory_derivation_effects(source_event):
            effect = resolved_effect.effect
            event = self._store_memory_candidate(
                session=session,
                source_event=source_event,
                memory_id=effect.memory_id,
                rule_id=resolved_effect.rule_id,
                memory_type=effect.memory_type,
                content=effect.content,
                salience=effect.salience,
                owner_character_id=target_id,
                visible_to_character_ids=[target_id],
                source_memory_ids=[resolved_effect.source_memory_id],
                confidence=effect.confidence,
                metadata=effect.metadata,
            )
            if event is not None:
                events.append(event)
        return events

    def _derive_player_accused_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        target_id = str(source_event.payload["target_id"])
        claim_id = str(source_event.payload["claim_id"])
        target_name = self._character_name(case, target_id)
        evidence_ids = [
            str(item) for item in source_event.payload.get("evidence_clue_ids", [])
        ]
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=f"memory.player.accused.{target_id}.{claim_id}",
            rule_id=PLAYER_ACCUSED_MEMORY_RULE_ID,
            content=(
                f"Player formally accused {target_name} with claim '{claim_id}' "
                f"using evidence {evidence_ids}."
            ),
            salience=1.0,
            owner_character_id=target_id,
            visible_to_character_ids=[target_id],
        )

    def _derive_accusation_evaluated_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        target_id = str(source_event.payload["target_id"])
        claim_id = str(source_event.payload["claim_id"])
        result = str(source_event.payload["result"])
        target_name = self._character_name(case, target_id)
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=f"memory.player.accusation_evaluated.{target_id}.{claim_id}.{result}",
            rule_id=ACCUSATION_EVALUATED_MEMORY_RULE_ID,
            content=(
                f"Rule Engine evaluated the accusation against {target_name} "
                f"for claim '{claim_id}' as {result}."
            ),
            salience=1.0,
            owner_character_id=target_id,
            visible_to_character_ids=[target_id],
        )

    def _character_name(self, case: CasePackage, character_id: str) -> str:
        return next(
            (item.display_name for item in case.characters if item.id == character_id),
            character_id,
        )

    def _all_character_ids(self, case: CasePackage) -> list[str]:
        return [character.id for character in case.characters]

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
        if source_event.id not in impression.source_event_ids:
            impression.source_event_ids.append(source_event.id)
        impression.confidence = _clamp01(impression.confidence + 0.1)

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
            _append_unique(impression.suspicious_points, "director_blocked")
            _append_unique(impression.tags, "unsafe_boundary_probe")
            _append_unique(impression.tags, "dangerous_topic_triggered")
            impression.threat_level = _clamp01(impression.threat_level + 0.2)
            impression.manipulation_risk = _clamp01(impression.manipulation_risk + 0.1)
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
        _append_unique(impression.suspicious_points, f"asked_about.{subject_type}.{subject_id}")
        _append_unique(impression.tags, "targeted_questioning")
        if self._append_optional_knowledge_ref(impression, source_event):
            _append_unique(impression.tags, "has_relevant_evidence")
        impression.threat_level = _clamp01(impression.threat_level + 0.1 + pressure * 0.2)
        impression.usefulness = _clamp01(impression.usefulness + 0.1)
        if pressure >= 0.6:
            _append_unique(impression.tags, "applies_pressure")
            impression.manipulation_risk = _clamp01(impression.manipulation_risk + 0.05)
        impression.trust_boundary = "Answer only within disclosed player knowledge."
        if self._is_medicine_topic_rule_match(source_event):
            impression.suspicion = _clamp_relationship(impression.suspicion + 0.2)
            impression.trust = _clamp_relationship(impression.trust - 0.1)
            impression.current_strategy = MEDICINE_STRATEGY_ID
            impression.traits["medicine_topic_pressure"] = _clamp01(
                impression.traits.get("medicine_topic_pressure", 0.0) + 0.2
            )
            _append_unique(impression.source_memory_ids, MEDICINE_BELIEF_MEMORY_ID)
            _append_unique(impression.source_memory_ids, MEDICINE_RELATIONSHIP_MEMORY_ID)
            _append_unique(impression.source_memory_ids, MEDICINE_STRATEGY_MEMORY_ID)

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
        _append_unique(impression.suspicious_points, f"presented_clue.{clue_id}")
        _append_unique(impression.tags, "evidence_pressure")
        if self._append_optional_knowledge_ref(impression, source_event):
            _append_unique(impression.tags, "has_relevant_evidence")
        impression.threat_level = _clamp01(impression.threat_level + 0.2 + pressure * 0.2)
        impression.manipulation_risk = _clamp01(impression.manipulation_risk + 0.15)
        impression.usefulness = _clamp01(impression.usefulness + 0.15)
        impression.trust_boundary = "Avoid direct admissions unless evidence rules allow it."
        if self._is_medicine_topic_rule_match(source_event):
            impression.suspicion = _clamp_relationship(impression.suspicion + 0.2)
            impression.trust = _clamp_relationship(impression.trust - 0.1)
            impression.current_strategy = MEDICINE_STRATEGY_ID
            impression.traits["medicine_topic_pressure"] = _clamp01(
                impression.traits.get("medicine_topic_pressure", 0.0) + 0.3
            )
            _append_unique(impression.source_memory_ids, MEDICINE_BELIEF_MEMORY_ID)
            _append_unique(impression.source_memory_ids, MEDICINE_RELATIONSHIP_MEMORY_ID)
            _append_unique(impression.source_memory_ids, MEDICINE_STRATEGY_MEMORY_ID)

    def _apply_player_accused_impression(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        claim_id = str(source_event.payload["claim_id"])
        impression.personality_impression = "The player is willing to make formal accusations."
        impression.perceived_motive = "Trying to force a formal case judgment."
        _append_unique(impression.suspicious_points, f"accused.{claim_id}")
        _append_unique(impression.tags, "formal_accusation")
        _append_unique(impression.tags, "has_relevant_evidence")
        for clue_id in source_event.payload.get("evidence_clue_ids", []):
            _append_unique(impression.suspected_knowledge_refs, str(clue_id))
        impression.threat_level = _clamp01(impression.threat_level + 0.35)
        impression.manipulation_risk = _clamp01(impression.manipulation_risk + 0.1)
        impression.usefulness = _clamp01(impression.usefulness + 0.2)
        impression.trust_boundary = "Do not volunteer extra facts under accusation pressure."

    def _apply_accusation_evaluated_impression(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        result = str(source_event.payload["result"])
        claim_id = str(source_event.payload["claim_id"])
        _append_unique(impression.suspicious_points, f"accusation_evaluated.{claim_id}.{result}")
        _append_unique(impression.tags, f"accusation_{result}")
        impression.perceived_motive = "Seeking case resolution through formal claims."
        if result == "correct":
            impression.personality_impression = "The player can assemble decisive evidence."
            impression.threat_level = _clamp01(impression.threat_level + 0.45)
            impression.usefulness = _clamp01(impression.usefulness + 0.25)
            impression.trust_boundary = "Assume the player can connect evidence accurately."
        else:
            impression.personality_impression = "The player may overreach with partial evidence."
            impression.manipulation_risk = _clamp01(impression.manipulation_risk + 0.2)

    def _apply_relationship_threshold_impression(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> None:
        metric = str(source_event.payload["metric"])
        state = str(source_event.payload["state"])
        _append_unique(impression.suspicious_points, f"relationship_threshold.{metric}.{state}")
        _append_unique(impression.tags, "relationship_threshold")
        _append_unique(impression.tags, f"{metric}_{state}")
        if metric == "trust":
            impression.alliance_potential = _clamp01(impression.alliance_potential + 0.3)
            impression.usefulness = _clamp01(impression.usefulness + 0.2)
            impression.trust_boundary = "Limited cooperation is possible."
            return
        if metric == "suspicion":
            impression.threat_level = _clamp01(impression.threat_level + 0.2)
            impression.manipulation_risk = _clamp01(impression.manipulation_risk + 0.1)
            impression.trust_boundary = "Keep answers guarded around sensitive topics."
            return
        if metric == "fear":
            impression.threat_level = _clamp01(impression.threat_level + 0.25)
            impression.trust_boundary = "Avoid escalation and disclose only safe fragments."

    def _append_optional_knowledge_ref(
        self,
        impression: CharacterImpression,
        source_event: WorldEvent,
    ) -> bool:
        appended = False
        knowledge_id = source_event.payload.get("knowledge_id")
        if isinstance(knowledge_id, str):
            _append_unique(impression.suspected_knowledge_refs, knowledge_id)
            appended = True
        clue_id = source_event.payload.get("clue_id")
        if isinstance(clue_id, str):
            _append_unique(impression.suspected_knowledge_refs, clue_id)
            _append_unique(impression.suspected_knowledge_refs, f"player_knowledge.{clue_id}")
            appended = True
        world_info_id = source_event.payload.get("world_info_id")
        if isinstance(world_info_id, str):
            _append_unique(impression.suspected_knowledge_refs, world_info_id)
            appended = True
        return appended

    def _is_medicine_topic_rule_match(self, source_event: WorldEvent) -> bool:
        return bool(memory_derivation_rule_ids_for_event(source_event) & MEDICINE_TOPIC_RULE_IDS)

    def _store_memory_candidate(
        self,
        *,
        session: SessionState,
        source_event: WorldEvent,
        memory_id: str,
        rule_id: str | None = None,
        memory_type: str = "episodic",
        content: str,
        salience: float,
        owner_character_id: str | None,
        visible_to_character_ids: list[str],
        memory_scope: str = "npc_private",
        memory_layer: str = "working",
        source_memory_ids: list[str] | None = None,
        confidence: float = 1.0,
        metadata: dict[str, object] | None = None,
    ) -> WorldEvent | None:
        current = session.memory_candidates.get(memory_id)
        if current is not None and source_event.id in current.source_event_ids:
            return None
        current_snapshot = session.memory_snapshots.get(memory_id)
        if current_snapshot is not None and source_event.id in current_snapshot.source_event_ids:
            return None
        session.memory_candidates[memory_id] = MemoryCandidateState(
            memory_id=memory_id,
            rule_id=rule_id,
            memory_type=memory_type,
            memory_scope=memory_scope,
            memory_layer=memory_layer,
            subject_id="player",
            owner_character_id=owner_character_id,
            visible_to_character_ids=visible_to_character_ids,
            content=content,
            source_event_id=source_event.id,
            source_event_ids=[source_event.id],
            source_memory_ids=source_memory_ids or [],
            visibility=["player"],
            salience=salience,
            confidence=confidence,
            metadata=metadata or {},
        )
        return self._recorder.append(
            session,
            actor_id="derived_event_system",
            event_type=EventType.MEMORY_CANDIDATE_CREATED,
            payload={
                "memory_id": memory_id,
                "rule_id": rule_id,
                "memory_type": memory_type,
                "memory_scope": memory_scope,
                "memory_layer": memory_layer,
                "subject_id": "player",
                "owner_character_id": owner_character_id,
                "visible_to_character_ids": visible_to_character_ids,
                "content": content,
                "source_event_id": source_event.id,
                "source_event_ids": [source_event.id],
                "source_memory_ids": source_memory_ids or [],
                "visibility": ["player"],
                "salience": salience,
                "confidence": confidence,
                "metadata": metadata or {},
            },
            caused_by_event_id=source_event.id,
        )


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _clamp01(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 4)


def _clamp_relationship(value: float) -> float:
    return round(min(max(value, -1.0), 1.0), 4)
