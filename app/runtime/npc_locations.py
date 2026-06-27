from __future__ import annotations

from app.domain.models import CasePackage, NpcLocationState, SessionState


def initial_npc_locations(case: CasePackage) -> dict[str, NpcLocationState]:
    locations: dict[str, NpcLocationState] = {}
    known_character_ids = {character.id for character in case.characters}
    for scene in case.scenes:
        for character_id in scene.characters:
            if character_id not in known_character_ids or character_id in locations:
                continue
            locations[character_id] = NpcLocationState(
                npc_id=character_id,
                scene_id=scene.id,
                updated_at_tick=0,
            )
    return locations


def npc_scene_id(
    *,
    case: CasePackage,
    session: SessionState,
    character_id: str,
) -> str | None:
    location = session.npc_locations.get(character_id)
    if location is not None:
        return location.scene_id
    initial = initial_npc_locations(case).get(character_id)
    return initial.scene_id if initial is not None else None
