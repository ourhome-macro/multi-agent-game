from __future__ import annotations

from app.domain.models import (
    AccuseAffordance,
    ActionType,
    AskAboutAffordance,
    CasePackage,
    CharacterConfig,
    ClueConfig,
    InspectAffordance,
    PlayerAction,
    PresentationMode,
    PresentClueAffordance,
    SessionAffordances,
    SessionState,
    SubjectType,
    TalkAffordance,
)
from app.rules.engine import RuleEngine
from app.runtime.npc_locations import npc_scene_id


def build_session_affordances(
    *,
    case: CasePackage,
    session: SessionState,
    rule_engine: RuleEngine,
) -> SessionAffordances:
    clue_by_id = {clue.id: clue for clue in case.clues}
    character_by_id = {character.id: character for character in case.characters}
    scene_by_character = _scene_ids_by_character(case, session)
    present_clue = _build_present_clue_affordances(
        case=case,
        session=session,
        rule_engine=rule_engine,
        clue_by_id=clue_by_id,
        scene_by_character=scene_by_character,
    )
    evidence_asset_ids = list(dict.fromkeys(item.clue_id for item in present_clue))

    accuse = _build_accuse_affordances(
        case=case,
        session=session,
        rule_engine=rule_engine,
        evidence_clue_ids=evidence_asset_ids,
    )

    valid_presentation_modes = _valid_presentation_modes(present_clue)
    return SessionAffordances(
        session_id=session.id,
        case_id=session.case_id,
        narrative_phase=session.narrative.phase,
        event_count=len(session.events),
        available_hotspot_ids=[
            hotspot.id for scene in case.scenes for hotspot in scene.hotspots
        ],
        available_character_ids=[character.id for character in case.characters],
        discovered_clue_ids=sorted(session.discovered_clues),
        evidence_asset_ids=evidence_asset_ids,
        valid_presentation_modes=valid_presentation_modes,
        can_accuse=bool(accuse),
        inspect=[
            InspectAffordance(
                target_id=hotspot.id,
                scene_id=scene.id,
                label=hotspot.name,
                description=hotspot.description,
            )
            for scene in case.scenes
            for hotspot in scene.hotspots
        ],
        talk=[
            TalkAffordance(
                target_id=character.id,
                scene_ids=scene_by_character.get(character.id, []),
                label=character.display_name,
                public_role=character.public_role,
            )
            for character in case.characters
            if _action_allowed(
                rule_engine,
                case,
                session,
                PlayerAction(type=ActionType.TALK, target_id=character.id),
            )
        ],
        ask_about=_build_ask_about_affordances(
            case=case,
            session=session,
            rule_engine=rule_engine,
            clue_by_id=clue_by_id,
            character_by_id=character_by_id,
        ),
        present_clue=present_clue,
        accuse=accuse,
    )


def _build_ask_about_affordances(
    *,
    case: CasePackage,
    session: SessionState,
    rule_engine: RuleEngine,
    clue_by_id: dict[str, ClueConfig],
    character_by_id: dict[str, CharacterConfig],
) -> list[AskAboutAffordance]:
    affordances: list[AskAboutAffordance] = []
    for target in case.characters:
        for clue_id, clue in clue_by_id.items():
            action = PlayerAction(
                type=ActionType.ASK_ABOUT,
                target_id=target.id,
                subject_type=SubjectType.CLUE,
                subject_id=clue_id,
            )
            if not _action_allowed(rule_engine, case, session, action):
                continue
            clue = clue_by_id[clue_id]
            affordances.append(
                AskAboutAffordance(
                    target_id=target.id,
                    subject_type=SubjectType.CLUE,
                    subject_id=clue_id,
                    subject_label=clue.title,
                )
            )
        for character in case.characters:
            action = PlayerAction(
                type=ActionType.ASK_ABOUT,
                target_id=target.id,
                subject_type=SubjectType.CHARACTER,
                subject_id=character.id,
            )
            if not _action_allowed(rule_engine, case, session, action):
                continue
            affordances.append(
                AskAboutAffordance(
                    target_id=target.id,
                    subject_type=SubjectType.CHARACTER,
                    subject_id=character.id,
                    subject_label=character_by_id[character.id].display_name,
                )
            )
        for scene in case.scenes:
            action = PlayerAction(
                type=ActionType.ASK_ABOUT,
                target_id=target.id,
                subject_type=SubjectType.SCENE,
                subject_id=scene.id,
            )
            if not _action_allowed(rule_engine, case, session, action):
                continue
            affordances.append(
                AskAboutAffordance(
                    target_id=target.id,
                    subject_type=SubjectType.SCENE,
                    subject_id=scene.id,
                    subject_label=scene.name,
                )
            )
    return affordances


def _build_present_clue_affordances(
    *,
    case: CasePackage,
    session: SessionState,
    rule_engine: RuleEngine,
    clue_by_id: dict[str, ClueConfig],
    scene_by_character: dict[str, list[str]],
) -> list[PresentClueAffordance]:
    affordances: list[PresentClueAffordance] = []
    for character in case.characters:
        for clue in case.clues:
            modes: list[PresentationMode] = []
            private_action = PlayerAction(
                type=ActionType.PRESENT_CLUE,
                target_id=character.id,
                clue_id=clue.id,
                presentation_mode=PresentationMode.PRIVATE,
            )
            if _action_allowed(rule_engine, case, session, private_action):
                modes.append(PresentationMode.PRIVATE)
            scene_ids: list[str] = []
            for scene_id in scene_by_character.get(character.id, []):
                shared_action = PlayerAction(
                    type=ActionType.PRESENT_CLUE,
                    target_id=character.id,
                    clue_id=clue.id,
                    presentation_mode=PresentationMode.SCENE_SHARED,
                    scene_id=scene_id,
                )
                if _action_allowed(rule_engine, case, session, shared_action):
                    scene_ids.append(scene_id)
            if scene_ids:
                modes.append(PresentationMode.SCENE_SHARED)
            if not modes:
                continue
            affordances.append(
                PresentClueAffordance(
                    target_id=character.id,
                    clue_id=clue.id,
                    clue_title=clue_by_id[clue.id].title,
                    presentation_modes=modes,
                    scene_ids=scene_ids,
                )
            )
    return affordances


def _build_accuse_affordances(
    *,
    case: CasePackage,
    session: SessionState,
    rule_engine: RuleEngine,
    evidence_clue_ids: list[str],
) -> list[AccuseAffordance]:
    affordances: list[AccuseAffordance] = []
    seen_targets: set[str] = set()
    for claim in case.solution_claims.claims:
        action = PlayerAction(
            type=ActionType.ACCUSE,
            target_id=claim.target_id,
            claim_id=claim.id,
            evidence_clue_ids=evidence_clue_ids,
        )
        if (
            not _action_allowed(rule_engine, case, session, action)
            or claim.target_id in seen_targets
        ):
            continue
        seen_targets.add(claim.target_id)
        affordances.append(
            AccuseAffordance(
                target_id=claim.target_id,
                evidence_clue_ids=list(evidence_clue_ids),
            )
        )
    return affordances


def _scene_ids_by_character(
    case: CasePackage,
    session: SessionState,
) -> dict[str, list[str]]:
    scene_ids: dict[str, list[str]] = {}
    for character in case.characters:
        scene_id = npc_scene_id(
            case=case,
            session=session,
            character_id=character.id,
        )
        if scene_id is not None:
            scene_ids[character.id] = [scene_id]
    return scene_ids


def _valid_presentation_modes(
    affordances: list[PresentClueAffordance],
) -> list[PresentationMode]:
    modes: list[PresentationMode] = []
    for affordance in affordances:
        for mode in affordance.presentation_modes:
            if mode not in modes:
                modes.append(mode)
    return modes


def _action_allowed(
    rule_engine: RuleEngine,
    case: CasePackage,
    session: SessionState,
    action: PlayerAction,
) -> bool:
    dry_run_session = session.model_copy(deep=True)
    return (
        rule_engine.precheck_player_action(
            case=case,
            session=dry_run_session,
            action=action,
        )
        is None
    )
