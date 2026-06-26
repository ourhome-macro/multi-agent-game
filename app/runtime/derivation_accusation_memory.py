from __future__ import annotations

from app.domain.models import CasePackage, SessionState, WorldEvent
from app.runtime.derivation_memory_constants import (
    ACCUSATION_EVALUATED_MEMORY_RULE_ID,
    PLAYER_ACCUSED_MEMORY_RULE_ID,
)


class AccusationMemoryDerivationMixin:
    def _player_accused_memory_id(self, source_event: WorldEvent) -> str:
        return (
            "memory.player.accused."
            f"{source_event.payload['target_id']}."
            f"{source_event.payload['claim_id']}"
        )

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

