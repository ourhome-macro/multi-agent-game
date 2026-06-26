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
    AUTHORITY_SOURCE_RULE_DERIVED as _AUTHORITY_SOURCE_RULE_DERIVED,
)
from app.runtime.derivation_utils import (
    case_thread_metadata_for_claim as _case_thread_metadata_for_claim,
)
from app.runtime.derivation_utils import (
    case_thread_topic_tags as _case_thread_topic_tags,
)
from app.runtime.derivation_utils import (
    claim_supports_reconstruction_thread as _claim_supports_reconstruction_thread,
)
from app.runtime.derivation_utils import (
    clue_discovered_memory_id as _clue_discovered_memory_id,
)
from app.runtime.derivation_utils import (
    clue_memory_metadata as _clue_memory_metadata,
)
from app.runtime.derivation_utils import (
    reconstruction_memory_id as _reconstruction_memory_id,
)
from app.runtime.derivation_utils import (
    role_reconstruction_metadata as _role_reconstruction_metadata,
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
            memory_id=_clue_discovered_memory_id(clue_id),
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
        source_memory_id = _clue_discovered_memory_id(clue_id)
        common_metadata = {
            **thread_metadata,
            "clue_id": clue_id,
            "phase_ids": ["reconstruction", "resolved"],
            "topic_tags": _case_thread_topic_tags(
                case_thread_id=case_thread_id,
                clue_ids=[
                    clue_id,
                    *[
                        str(item)
                        for item in thread_metadata.get("adjacent_clue_ids", [])
                        if item is not None
                    ],
                ],
            ),
            "authority_source": _AUTHORITY_SOURCE_RULE_DERIVED,
        }
        events: list[WorldEvent] = []
        for event in (
            self._store_memory_candidate(
                session=session,
                source_event=source_event,
                memory_id=_reconstruction_memory_id("belief", case_thread_id),
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
                memory_id=_reconstruction_memory_id("strategy", case_thread_id),
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
            metadata = _role_reconstruction_metadata(
                thread_metadata=thread_metadata,
                case_thread_id=case_thread_id,
                character_id=character.id,
                adjacent_clue_ids=adjacent_clue_ids,
            )
            for event in (
                self._store_memory_candidate(
                    session=session,
                    source_event=source_event,
                    memory_id=_reconstruction_memory_id(
                        "belief",
                        case_thread_id,
                        character_id=character.id,
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
                    memory_id=_reconstruction_memory_id(
                        "strategy",
                        case_thread_id,
                        character_id=character.id,
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
            return _clue_memory_metadata(clue_id=clue_id)
        return _clue_memory_metadata(
            clue_id=clue_id,
            related_event_ids=clue.related_events,
            related_character_ids=clue.related_characters,
            world_info_ids=clue.reveals_world_info,
            case_thread_metadata=self._case_thread_metadata_for_clue(case, clue_id),
        )

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
        return _case_thread_metadata_for_claim(
            claim_id=claim.id,
            clue_id=clue_id,
            required_evidence=claim.required_evidence,
        )

    def _thread_evidence_ready(
        self,
        session: SessionState,
        required_evidence: list[str],
    ) -> bool:
        return set(required_evidence).issubset(session.discovered_clues)

    def _all_character_ids(self, case: CasePackage) -> list[str]:
        return [character.id for character in case.characters]

