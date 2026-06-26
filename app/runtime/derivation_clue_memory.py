from __future__ import annotations

from app.domain.models import CasePackage, SessionState, SolutionClaimConfig, WorldEvent
from app.runtime.derivation_memory_constants import (
    CLUE_DISCOVERED_CHAIN_BELIEF_RULE_ID,
    CLUE_DISCOVERED_CHAIN_STRATEGY_RULE_ID,
    CLUE_DISCOVERED_MEMORY_RULE_ID,
    CLUE_DISCOVERED_ROLE_CHAIN_BELIEF_RULE_ID,
    CLUE_DISCOVERED_ROLE_CHAIN_STRATEGY_RULE_ID,
)
from app.runtime.derivation_utils import (
    claim_supports_reconstruction_thread as _claim_supports_reconstruction_thread,
)
from app.runtime.derivation_utils import (
    identifier_topic_tags as _identifier_topic_tags,
)
from app.runtime.derivation_utils import (
    ordered_unique as _ordered_unique,
)
from app.runtime.derivation_utils import (
    role_reconstruction_topic_tags as _role_reconstruction_topic_tags,
)


class ClueMemoryDerivationMixin:
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
            metadata=self._clue_memory_metadata(case, clue_id),
        )

    def _derive_clue_chain_typed_memory_candidates(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> list[WorldEvent]:
        clue_id = str(source_event.payload["clue_id"])
        claim = self._reconstruction_thread_claim_for_clue(case, clue_id)
        if claim is None:
            return []
        thread_metadata = self._case_thread_metadata_for_claim(claim, clue_id)
        case_thread_id = thread_metadata.get("case_thread_id")
        if not isinstance(case_thread_id, str):
            return []
        source_memory_id = f"memory.player.clue_discovered.{clue_id}"
        common_metadata = {
            **thread_metadata,
            "clue_id": clue_id,
            "phase_ids": ["reconstruction", "resolved"],
            "topic_tags": _ordered_unique(
                [
                    case_thread_id,
                    "reconstruction",
                    clue_id,
                    *[
                        str(item)
                        for item in thread_metadata.get("adjacent_clue_ids", [])
                        if item is not None
                    ],
                ]
            ),
            "authority_source": "rule_derived",
        }
        events: list[WorldEvent] = []
        for event in (
            self._store_memory_candidate(
                session=session,
                source_event=source_event,
                memory_id=f"memory.player.belief.reconstruction.{case_thread_id}",
                rule_id=CLUE_DISCOVERED_CHAIN_BELIEF_RULE_ID,
                content="Player has established evidence that belongs to a reconstruction thread.",
                salience=0.82,
                owner_character_id=None,
                visible_to_character_ids=[],
                source_memory_ids=[source_memory_id],
                memory_type="belief",
                memory_scope="case",
                memory_layer="core",
                metadata={
                    **common_metadata,
                    "belief_subject": f"player_reconstructing_{case_thread_id}",
                    "belief_polarity": "suspects",
                    "chain_node_id": "thread_belief",
                },
            ),
            self._store_memory_candidate(
                session=session,
                source_event=source_event,
                memory_id=f"memory.player.strategy.reconstruction.{case_thread_id}",
                rule_id=CLUE_DISCOVERED_CHAIN_STRATEGY_RULE_ID,
                content=(
                    "During reconstruction, respond by connecting discovered "
                    "evidence as linked clue nodes."
                ),
                salience=0.86,
                owner_character_id=None,
                visible_to_character_ids=[],
                source_memory_ids=[source_memory_id],
                memory_type="strategy",
                memory_scope="case",
                memory_layer="core",
                metadata={
                    **common_metadata,
                    "strategy_id": f"connect_{case_thread_id}_nodes",
                    "chain_node_id": "thread_strategy",
                },
            ),
        ):
            if event is not None:
                events.append(event)
        if self._thread_evidence_ready(session, claim.required_evidence):
            events.extend(
                self._derive_role_reconstruction_thread_memory_candidates(
                    case=case,
                    session=session,
                    source_event=source_event,
                    case_thread_id=case_thread_id,
                    source_memory_id=source_memory_id,
                    thread_metadata=thread_metadata,
                )
            )
        return events

    def _derive_role_reconstruction_thread_memory_candidates(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
        case_thread_id: str,
        source_memory_id: str,
        thread_metadata: dict[str, object],
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        adjacent_clue_ids = [
            str(item)
            for item in thread_metadata.get("adjacent_clue_ids", [])
            if item is not None
        ]
        for character in case.characters:
            role_tags = _role_reconstruction_topic_tags(character.id)
            metadata = {
                **thread_metadata,
                "phase_ids": ["reconstruction", "resolved"],
                "topic_tags": _ordered_unique(
                    [
                        case_thread_id,
                        "reconstruction",
                        character.id,
                        *role_tags,
                        *adjacent_clue_ids,
                    ]
                ),
                "authority_source": "rule_derived",
            }
            for event in (
                self._store_memory_candidate(
                    session=session,
                    source_event=source_event,
                    memory_id=(
                        "memory.player.belief.reconstruction."
                        f"{character.id}.{case_thread_id}"
                    ),
                    rule_id=CLUE_DISCOVERED_ROLE_CHAIN_BELIEF_RULE_ID,
                    content=(
                        f"{character.display_name} believes the player can now "
                        "compare established evidence across the reconstruction chain."
                    ),
                    salience=0.78,
                    owner_character_id=character.id,
                    visible_to_character_ids=[character.id],
                    source_memory_ids=[source_memory_id],
                    memory_type="belief",
                    memory_scope="npc_private",
                    memory_layer="working",
                    metadata={
                        **metadata,
                        "belief_subject": (
                            f"player_reconstructing_{case_thread_id}_{character.id}"
                        ),
                        "belief_polarity": "suspects",
                        "chain_node_id": f"{character.id}_thread_belief",
                    },
                ),
                self._store_memory_candidate(
                    session=session,
                    source_event=source_event,
                    memory_id=(
                        "memory.player.strategy.reconstruction."
                        f"{character.id}.{case_thread_id}"
                    ),
                    rule_id=CLUE_DISCOVERED_ROLE_CHAIN_STRATEGY_RULE_ID,
                    content=(
                        f"{character.display_name} should answer from their own "
                        "evidence boundary and avoid adding facts outside unlocked evidence."
                    ),
                    salience=0.84,
                    owner_character_id=character.id,
                    visible_to_character_ids=[character.id],
                    source_memory_ids=[source_memory_id],
                    memory_type="strategy",
                    memory_scope="npc_private",
                    memory_layer="working",
                    metadata={
                        **metadata,
                        "strategy_id": f"bounded_reconstruction_{character.id}",
                        "chain_node_id": f"{character.id}_thread_strategy",
                    },
                ),
            ):
                if event is not None:
                    events.append(event)
        return events

    def _clue_memory_metadata(
        self,
        case: CasePackage,
        clue_id: str,
    ) -> dict[str, object]:
        clue = next((item for item in case.clues if item.id == clue_id), None)
        if clue is None:
            return {"clue_id": clue_id, "topic_tags": _identifier_topic_tags(clue_id)}
        metadata: dict[str, object] = {
            "clue_id": clue_id,
            "topic_tags": _ordered_unique(
                [
                    *_identifier_topic_tags(clue_id),
                    *clue.related_events,
                    *clue.related_characters,
                ]
            ),
        }
        if clue.reveals_world_info:
            metadata["world_info_id"] = clue.reveals_world_info[0]
        metadata.update(self._case_thread_metadata_for_clue(case, clue_id))
        return metadata

    def _case_thread_metadata_for_clue(
        self,
        case: CasePackage,
        clue_id: str,
    ) -> dict[str, object]:
        claim = self._reconstruction_thread_claim_for_clue(case, clue_id)
        if claim is None:
            return {}
        return self._case_thread_metadata_for_claim(claim, clue_id)

    def _reconstruction_thread_claim_for_clue(
        self,
        case: CasePackage,
        clue_id: str,
    ) -> SolutionClaimConfig | None:
        return next(
            (
                item
                for item in case.solution_claims.claims
                if item.result == "correct"
                and clue_id in set(item.required_evidence)
                and _claim_supports_reconstruction_thread(item.allowed_phases)
            ),
            None,
        )

    def _case_thread_metadata_for_claim(
        self,
        claim: SolutionClaimConfig,
        clue_id: str,
    ) -> dict[str, object]:
        adjacent_clue_ids = [
            evidence_id
            for evidence_id in claim.required_evidence
            if evidence_id != clue_id
        ]
        return {
            "case_thread_id": claim.id,
            "chain_node_id": clue_id,
            "adjacent_clue_ids": adjacent_clue_ids,
            "key_clue": True,
            "is_plot_critical": True,
        }

    def _thread_evidence_ready(
        self,
        session: SessionState,
        required_evidence: list[str],
    ) -> bool:
        return set(required_evidence).issubset(session.discovered_clues)

    def _all_character_ids(self, case: CasePackage) -> list[str]:
        return [character.id for character in case.characters]

