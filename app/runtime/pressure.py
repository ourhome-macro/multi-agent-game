from __future__ import annotations

from app.domain.models import ActionType, CasePackage, PlayerAction, SubjectType


def calculate_interaction_pressure(case: CasePackage, action: PlayerAction) -> float:
    base_pressure = {
        ActionType.TALK: 0.1,
        ActionType.ASK_ABOUT: 0.3,
        ActionType.PRESENT_CLUE: 0.6,
    }.get(action.type, 0.0)
    pressure = base_pressure
    if subject_is_associated_with_target(case, action):
        pressure += 0.2
    if subject_is_key_clue(case, action):
        pressure += 0.1
    return round(min(max(pressure, 0.0), 1.0), 4)


def subject_is_sensitive(case: CasePackage, action: PlayerAction) -> bool:
    return subject_is_associated_with_target(case, action) or subject_is_key_clue(case, action)


def subject_is_associated_with_target(case: CasePackage, action: PlayerAction) -> bool:
    clue_id = _clue_subject_id(action)
    if clue_id is not None:
        clue = next((item for item in case.clues if item.id == clue_id), None)
        return clue is not None and action.target_id in clue.related_characters

    if action.type == ActionType.ASK_ABOUT and action.subject_type == SubjectType.CHARACTER:
        return action.subject_id == action.target_id

    if action.type == ActionType.ASK_ABOUT and action.subject_type == SubjectType.SCENE:
        scene = next((item for item in case.scenes if item.id == action.subject_id), None)
        return scene is not None and action.target_id in scene.characters

    return False


def subject_is_key_clue(case: CasePackage, action: PlayerAction) -> bool:
    clue_id = _clue_subject_id(action)
    if clue_id is None:
        return False
    clue = next((item for item in case.clues if item.id == clue_id), None)
    return clue is not None and clue.key


def _clue_subject_id(action: PlayerAction) -> str | None:
    if action.type == ActionType.PRESENT_CLUE:
        return action.clue_id
    if action.type == ActionType.ASK_ABOUT and action.subject_type == SubjectType.CLUE:
        return action.subject_id
    return None
