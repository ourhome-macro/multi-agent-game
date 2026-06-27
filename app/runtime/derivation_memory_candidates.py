from __future__ import annotations

from app.runtime.derivation_accusation_memory import AccusationMemoryDerivationMixin
from app.runtime.derivation_clue_memory import ClueMemoryDerivationMixin
from app.runtime.derivation_interaction_memory import InteractionMemoryDerivationMixin
from app.runtime.derivation_memory_store import MemoryCandidateStoreMixin
from app.runtime.derivation_npc_observation_memory import (
    NpcObservationMemoryDerivationMixin,
)
from app.runtime.derivation_scene_shared_memory import SceneSharedMemoryDerivationMixin


class MemoryCandidateDerivationMixin(
    AccusationMemoryDerivationMixin,
    ClueMemoryDerivationMixin,
    InteractionMemoryDerivationMixin,
    NpcObservationMemoryDerivationMixin,
    SceneSharedMemoryDerivationMixin,
    MemoryCandidateStoreMixin,
):
    pass
