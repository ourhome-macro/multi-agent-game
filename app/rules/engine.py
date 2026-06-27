from __future__ import annotations

from app.domain.models import (
    ActionType,
    AgentIntent,
    BacktrackClueUnlockConfig,
    CasePackage,
    DiscoverClueAction,
    EventType,
    MeetingSessionState,
    MeetingVoteChoice,
    MeetingVoteState,
    NpcLocationState,
    PlayerAction,
    PresentationMode,
    ProposedActionType,
    RelationshipChangeAction,
    RelationshipState,
    SceneConfig,
    SceneHotspotConfig,
    SessionState,
    SubjectType,
    WorldEvent,
    clamp_relationship_metric,
)
from app.rules.deduction import DeductionEvaluator, DeductionResult
from app.rules.deduction import player_knowledge_id_for_clue as _player_knowledge_id_for_clue
from app.runtime.events import EventRecorder
from app.runtime.npc_autonomy import (
    ALLOWED_NPC_AUTONOMY_TYPES,
    NPC_AUTONOMY_MOVE,
    NPC_AUTONOMY_OBSERVE,
    NPC_AUTONOMY_TALK_TO,
    NPC_AUTONOMY_WAIT,
    NPC_LOCATION_CHANGED_EVENT_TYPE,
    autonomy_action_type,
    autonomy_actor_id,
    autonomy_from_scene_id,
    autonomy_intent_type,
    autonomy_payload,
    autonomy_rationale,
    autonomy_scene_id,
    autonomy_target_id,
    autonomy_to_scene_id,
    current_npc_scene_id,
    forbidden_autonomy_side_effects,
)
from app.runtime.pressure import calculate_interaction_pressure

RELATIONSHIP_METRICS = {"trust", "suspicion", "fear", "intimacy", "hostility"}
RELATIONSHIP_THRESHOLDS = {
    "suspicion": (0.7, "guarded"),
    "fear": (0.7, "afraid"),
    "trust": (0.7, "cooperative"),
}
MEETING_ACTION_TYPES = {
    ActionType.MEETING_START,
    ActionType.MEETING_SPEAK,
    ActionType.MEETING_PRESENT_EVIDENCE,
    ActionType.MEETING_ASK,
    ActionType.MEETING_OPEN_VOTE,
    ActionType.MEETING_CAST_VOTE,
    ActionType.MEETING_PROPOSE_VERDICT,
}


class RuleEngine:
    def __init__(self, recorder: EventRecorder) -> None:
        self._recorder = recorder
        self._deduction_evaluator = DeductionEvaluator()

    def precheck_player_action(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> WorldEvent | None:
        if action.type == ActionType.INSPECT:
            if self._hotspot(case, action.target_id) is None:
                return self.reject_player_action(
                    session=session,
                    action=action,
                    reason="target_id is not a known hotspot",
                )
            return None

        if action.type == ActionType.TALK:
            if not self._is_known_character(case, action.target_id):
                return self.reject_player_action(
                    session=session,
                    action=action,
                    reason="target_id is not a known character",
            )
            return None

        if action.type == ActionType.ASK_ABOUT:
            return self._copy_precheck_rejection(
                self.apply_ask_about(
                    case=case,
                    session=session.model_copy(deep=True),
                    action=action,
                ),
                session=session,
            )

        if action.type == ActionType.PRESENT_CLUE:
            return self._copy_precheck_rejection(
                self.apply_present_clue(
                    case=case,
                    session=session.model_copy(deep=True),
                    action=action,
                ),
                session=session,
            )

        if action.type == ActionType.ACCUSE:
            return self._copy_precheck_rejection(
                self.apply_accuse(
                    case=case,
                    session=session.model_copy(deep=True),
                    action=action,
                ),
                session=session,
            )

        if action.type in MEETING_ACTION_TYPES:
            return self._copy_precheck_rejection(
                self.apply_meeting_action(
                    case=case,
                    session=session.model_copy(deep=True),
                    action=action,
                ),
                session=session,
            )

        return self.reject_player_action(
            session=session,
            action=action,
            reason=f"unsupported action type: {action.type}",
        )

    def reject_player_action(
        self,
        *,
        session: SessionState,
        action: PlayerAction,
        reason: str,
    ) -> WorldEvent:
        return self._reject(
            session=session,
            action_type=f"player.{action.type.value}",
            reason=reason,
            payload=_player_action_payload(action),
            caused_by_event_id=None,
        )

    def _copy_precheck_rejection(
        self,
        events: list[WorldEvent],
        *,
        session: SessionState,
    ) -> WorldEvent | None:
        dry_run_rejection = next(
            (event for event in events if event.type == EventType.RULE_REJECTED),
            None,
        )
        if dry_run_rejection is None:
            return None
        proposed_payload = dry_run_rejection.payload.get("proposed_payload", {})
        if not isinstance(proposed_payload, dict):
            proposed_payload = {}
        return self._reject(
            session=session,
            action_type=str(dry_run_rejection.payload.get("action_type", "player.unknown")),
            reason=str(dry_run_rejection.payload.get("reason", "rule precheck rejected")),
            payload=proposed_payload,
            caused_by_event_id=None,
        )

    def apply_inspect(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        hotspot = self._hotspot(case, action.target_id)

        if hotspot is None:
            return []

        events: list[WorldEvent] = []
        for clue_id in hotspot.discover_clues:
            event = self._discover_clue(
                session=session,
                clue_id=clue_id,
                payload={"clue_id": clue_id, "source_hotspot_id": hotspot.id},
                caused_by_event_id=caused_by_event_id,
            )
            if event is not None:
                events.append(event)
        for unlock in hotspot.backtrack_unlocks:
            if not self._backtrack_unlock_ready(
                session,
                action.target_id,
                unlock,
                caused_by_event_id,
            ):
                continue
            for clue_id in unlock.clue_ids:
                event = self._discover_clue(
                    session=session,
                    clue_id=clue_id,
                    payload={
                        "clue_id": clue_id,
                        "source_hotspot_id": hotspot.id,
                        "source_backtrack_unlock_id": unlock.id,
                    },
                    caused_by_event_id=caused_by_event_id,
                )
                if event is not None:
                    events.append(event)
        return events

    def apply_agent_intent(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        intent: AgentIntent,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        for proposed_action in intent.proposed_actions:
            if proposed_action.type == ProposedActionType.RELATIONSHIP_CHANGE:
                events.extend(
                    self._apply_relationship_change(
                        case=case,
                        session=session,
                        action=proposed_action,
                        caused_by_event_id=caused_by_event_id,
                    )
                )
            elif proposed_action.type == ProposedActionType.DISCOVER_CLUE:
                event = self._apply_discover_clue(
                    case=case,
                    session=session,
                    action=proposed_action,
                    caused_by_event_id=caused_by_event_id,
                )
                if event is not None:
                    events.append(event)
            elif proposed_action.type == ProposedActionType.NARRATIVE_PHASE_CHANGE:
                events.append(
                    self._reject(
                        session=session,
                        action_type=proposed_action.type,
                        reason="narrative phase changes must be driven by narrative rules",
                        payload={"phase": proposed_action.phase},
                        caused_by_event_id=caused_by_event_id,
                    )
                )
        return events

    def apply_npc_autonomy_intent(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        intent: object,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        forbidden_side_effects = forbidden_autonomy_side_effects(intent)
        if forbidden_side_effects:
            return [
                self._reject(
                    session=session,
                    action_type=autonomy_action_type(intent),
                    reason="npc autonomy intent cannot mutate clues or narrative phase",
                    payload={
                        **autonomy_payload(intent),
                        "forbidden_side_effects": forbidden_side_effects,
                    },
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        intent_type = autonomy_intent_type(intent)
        if intent_type not in ALLOWED_NPC_AUTONOMY_TYPES:
            return [
                self._reject(
                    session=session,
                    action_type=autonomy_action_type(intent),
                    reason="unsupported npc autonomy intent type",
                    payload=autonomy_payload(intent),
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        actor_id = autonomy_actor_id(intent)
        if actor_id is None or not self._is_known_character(case, actor_id):
            return [
                self._reject(
                    session=session,
                    action_type=autonomy_action_type(intent),
                    reason="actor_id is not a known character",
                    payload=autonomy_payload(intent),
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        if intent_type == NPC_AUTONOMY_MOVE:
            return self._apply_npc_autonomy_move(
                case=case,
                session=session,
                intent=intent,
                actor_id=actor_id,
                caused_by_event_id=caused_by_event_id,
            )
        if intent_type == NPC_AUTONOMY_OBSERVE:
            return self._apply_npc_autonomy_observe(
                case=case,
                session=session,
                intent=intent,
                actor_id=actor_id,
                caused_by_event_id=caused_by_event_id,
            )
        if intent_type == NPC_AUTONOMY_WAIT:
            return self._apply_npc_autonomy_wait(
                case=case,
                session=session,
                intent=intent,
                actor_id=actor_id,
                caused_by_event_id=caused_by_event_id,
            )
        if intent_type == NPC_AUTONOMY_TALK_TO:
            return self._apply_npc_autonomy_talk_to(
                case=case,
                session=session,
                intent=intent,
                actor_id=actor_id,
                caused_by_event_id=caused_by_event_id,
            )
        raise AssertionError(f"unhandled npc autonomy intent type: {intent_type}")

    def apply_present_clue(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        presentation_mode = action.effective_presentation_mode or PresentationMode.PRIVATE
        if not self._is_known_character(case, action.target_id):
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="target_id is not a known character",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": action.clue_id,
                        "presentation_mode": presentation_mode.value,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        clue_id = str(action.clue_id)
        clue_ids = {clue.id for clue in case.clues}
        if clue_id not in clue_ids:
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="clue_id is not defined by the case package",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": clue_id,
                        "presentation_mode": presentation_mode.value,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        if clue_id not in session.discovered_clues:
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="clue_id has not been discovered",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": clue_id,
                        "presentation_mode": presentation_mode.value,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        knowledge_id = player_knowledge_id_for_clue(case, clue_id)
        if knowledge_id not in session.player_knowledge:
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="clue_id is not available in player knowledge",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": clue_id,
                        "knowledge_id": knowledge_id,
                        "presentation_mode": presentation_mode.value,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        scene = None
        if presentation_mode == PresentationMode.SCENE_SHARED:
            scene = self._scene_for_presented_clue(
                case,
                session,
                action.target_id,
                action.scene_id,
            )
        if presentation_mode == PresentationMode.SCENE_SHARED and scene is None:
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="scene_id is not defined or target is not present in scene",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": clue_id,
                        "knowledge_id": knowledge_id,
                        "scene_id": action.scene_id,
                        "presentation_mode": presentation_mode.value,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        payload: dict[str, object] = {
            "target_id": action.target_id,
            "clue_id": clue_id,
            "knowledge_id": knowledge_id,
            "presentation_mode": presentation_mode.value,
            "text": action.text,
            "interaction_pressure": calculate_interaction_pressure(case, action),
        }
        if scene is not None:
            payload["scene_id"] = scene.id
            payload["present_character_ids"] = self._character_ids_in_scene(
                case,
                session,
                scene.id,
            )
        return [
            self._recorder.append(
                session,
                actor_id="player",
                event_type=EventType.PLAYER_PRESENTED_CLUE,
                payload=payload,
            )
        ]

    def apply_ask_about(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        if not self._is_known_character(case, action.target_id):
            return [
                self._reject(
                    session=session,
                    action_type="player.ask_about",
                    reason="target_id is not a known character",
                    payload={
                        "target_id": action.target_id,
                        "subject_type": action.subject_type,
                        "subject_id": action.subject_id,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]

        subject_id = str(action.subject_id)
        payload: dict[str, object] = {
            "target_id": action.target_id,
            "subject_type": str(action.subject_type.value if action.subject_type else ""),
            "subject_id": subject_id,
            "text": action.text,
            "interaction_pressure": calculate_interaction_pressure(case, action),
        }
        if action.subject_type == SubjectType.CLUE:
            clue_ids = {clue.id for clue in case.clues}
            if subject_id not in clue_ids:
                return [
                    self._reject(
                        session=session,
                        action_type="player.ask_about",
                        reason="subject clue is not defined by the case package",
                        payload=payload,
                        caused_by_event_id=None,
                    )
            ]
            knowledge_id = player_knowledge_id_for_clue(case, subject_id)
            if (
                subject_id not in session.discovered_clues
                and knowledge_id not in session.player_knowledge
            ):
                return [
                    self._reject(
                        session=session,
                        action_type="player.ask_about",
                        reason="subject clue has not been discovered",
                        payload=payload,
                        caused_by_event_id=None,
                    )
                ]
            if knowledge_id in session.player_knowledge:
                payload["knowledge_id"] = knowledge_id

        elif action.subject_type == SubjectType.CHARACTER:
            if not self._is_known_character(case, subject_id):
                return [
                    self._reject(
                        session=session,
                        action_type="player.ask_about",
                        reason="subject character is not defined by the case package",
                        payload=payload,
                        caused_by_event_id=None,
                    )
                ]
        elif action.subject_type == SubjectType.SCENE:
            if not any(scene.id == subject_id for scene in case.scenes):
                return [
                    self._reject(
                        session=session,
                        action_type="player.ask_about",
                        reason="subject scene is not defined by the case package",
                        payload=payload,
                        caused_by_event_id=None,
                    )
                ]

        return [
            self._recorder.append(
                session,
                actor_id="player",
                event_type=EventType.PLAYER_ASKED_ABOUT,
                payload=payload,
            )
        ]

    def apply_accuse(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        payload: dict[str, object] = {
            "target_id": action.target_id,
            "claim_id": action.claim_id,
            "evidence_clue_ids": list(action.evidence_clue_ids),
            "text": action.text,
        }
        result = self._deduction_evaluator.evaluate(
            case=case,
            session=session,
            action=action,
        )
        if not result.accepted:
            return [
                self._accuse_rejection(
                    session=session,
                    payload=payload,
                    result=result,
                )
            ]

        accused_event = self._recorder.append(
            session,
            actor_id="player",
            event_type=EventType.PLAYER_ACCUSED,
            payload={
                "target_id": action.target_id,
                "claim_id": str(action.claim_id),
                "evidence_clue_ids": result.evidence_clue_ids or [],
                "text": action.text,
            },
        )
        evaluated_event = self._recorder.append(
            session,
            actor_id="rule_engine",
            event_type=EventType.ACCUSATION_EVALUATED,
            payload={
                "target_id": action.target_id,
                "claim_id": str(action.claim_id),
                "result": result.result,
                "matched_required_evidence": result.matched_required_evidence,
                "missing_required_evidence": result.missing_evidence,
            },
            caused_by_event_id=accused_event.id,
        )
        return [accused_event, evaluated_event]

    def _accuse_rejection(
        self,
        *,
        session: SessionState,
        payload: dict[str, object],
        result: DeductionResult,
    ) -> WorldEvent:
        match result.reject_code:
            case "unknown_target":
                reason = "target_id is not a known character"
                reject_payload = payload
            case "unknown_claim":
                reason = "claim_id is not defined by the case package"
                reject_payload = payload
            case "target_mismatch":
                reason = "claim target_id does not match action target_id"
                reject_payload = payload
            case "phase_not_allowed":
                reason = "claim is not allowed in current narrative phase"
                reject_payload = {**payload, "current_phase": session.narrative.phase}
            case "empty_evidence":
                reason = "evidence_clue_ids cannot be empty"
                reject_payload = payload
            case "unknown_evidence":
                reason = "evidence_clue_ids contain unknown clues"
                reject_payload = {**payload, "unknown_evidence": result.unknown_evidence or []}
            case "undiscovered_evidence":
                reason = "evidence clues have not all been discovered"
                reject_payload = {
                    **payload,
                    "undiscovered_evidence": result.undiscovered_evidence or [],
                }
            case "missing_player_knowledge":
                reason = "evidence clues are not all available in player knowledge"
                reject_payload = {
                    **payload,
                    "missing_player_knowledge": result.missing_player_knowledge or [],
                }
            case "missing_required_evidence":
                reason = "evidence does not cover required claim evidence"
                reject_payload = {**payload, "missing_required_evidence": result.missing_evidence}
            case "missing_required_world_info":
                reason = "player knowledge does not cover required world info"
                reject_payload = {
                    **payload,
                    "missing_required_world_info": result.missing_world_info,
                }
            case _:
                raise ValueError("deduction rejection is missing a reject_code")
        return self._reject(
            session=session,
            action_type="player.accuse",
            reason=reason,
            payload=reject_payload,
            caused_by_event_id=None,
        )

    def apply_meeting_action(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        if action.type == ActionType.MEETING_START:
            return self._apply_meeting_start(case=case, session=session, action=action)
        if action.type == ActionType.MEETING_SPEAK:
            return self._apply_meeting_speak(session=session, action=action)
        if action.type == ActionType.MEETING_PRESENT_EVIDENCE:
            return self._apply_meeting_present_evidence(
                case=case,
                session=session,
                action=action,
            )
        if action.type == ActionType.MEETING_ASK:
            return self._apply_meeting_ask(case=case, session=session, action=action)
        if action.type == ActionType.MEETING_OPEN_VOTE:
            return self._apply_meeting_open_vote(case=case, session=session, action=action)
        if action.type == ActionType.MEETING_CAST_VOTE:
            return self._apply_meeting_cast_vote(session=session, action=action)
        if action.type == ActionType.MEETING_PROPOSE_VERDICT:
            return self._apply_meeting_propose_verdict(
                case=case,
                session=session,
                action=action,
            )
        return [
            self._reject(
                session=session,
                action_type=f"player.{action.type.value}",
                reason="unsupported meeting action type",
                payload=_player_action_payload(action),
                caused_by_event_id=None,
            )
        ]

    def record_meeting_message(
        self,
        *,
        session: SessionState,
        speaker_id: str,
        text: str,
        message_kind: str,
        caused_by_event_id: str,
        target_id: str | None = None,
        clue_id: str | None = None,
    ) -> WorldEvent:
        payload: dict[str, object] = {
            "meeting_id": session.meeting.meeting_id,
            "speaker_id": speaker_id,
            "message_kind": message_kind,
            "text": text,
        }
        if target_id is not None:
            payload["target_id"] = target_id
        if clue_id is not None:
            payload["clue_id"] = clue_id
        return self._append_meeting_event(
            session=session,
            actor_id=speaker_id,
            event_type=EventType.MEETING_MESSAGE_POSTED,
            payload=payload,
            caused_by_event_id=caused_by_event_id,
        )

    def record_meeting_vote(
        self,
        *,
        session: SessionState,
        voter_id: str,
        target_id: str,
        choice: MeetingVoteChoice,
        reason: str,
        caused_by_event_id: str,
    ) -> WorldEvent:
        return self._append_meeting_event(
            session=session,
            actor_id=voter_id,
            event_type=EventType.MEETING_VOTE_CAST,
            payload={
                "meeting_id": session.meeting.meeting_id,
                "voter_id": voter_id,
                "target_id": target_id,
                "choice": choice.value,
                "reason": reason,
            },
            caused_by_event_id=caused_by_event_id,
        )

    def _apply_meeting_start(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        if session.meeting.active:
            return [
                self._reject(
                    session=session,
                    action_type="meeting.session.started",
                    reason="meeting is already active",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        participant_ids = [character.id for character in case.characters]
        meeting_id = f"meeting.{session.id}.{len(session.events) + 1}"
        start_event = self._append_meeting_event(
            session=session,
            actor_id="player",
            event_type=EventType.MEETING_SESSION_STARTED,
            payload={
                "meeting_id": meeting_id,
                "topic": action.text or "案件公开讨论",
                "participant_ids": participant_ids,
            },
            caused_by_event_id=None,
        )
        turn_event = self._append_meeting_event(
            session=session,
            actor_id="director",
            event_type=EventType.MEETING_TURN_OPENED,
            payload={"meeting_id": meeting_id, "turn": 1},
            caused_by_event_id=start_event.id,
        )
        opening = self.record_meeting_message(
            session=session,
            speaker_id="director",
            text="会议开始。所有公开发言都会进入事件记录，投票不能替代证据链。",
            message_kind="system",
            caused_by_event_id=turn_event.id,
        )
        return [start_event, turn_event, opening]

    def _apply_meeting_speak(
        self,
        *,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        rejection = self._require_active_meeting(session=session, action=action)
        if rejection is not None:
            return [rejection]
        text = (action.text or "").strip()
        proposed = self._append_meeting_event(
            session=session,
            actor_id="player",
            event_type=EventType.MEETING_MESSAGE_PROPOSED,
            payload={
                "meeting_id": session.meeting.meeting_id,
                "speaker_id": "player",
                "message_kind": "speech",
                "text": text,
            },
            caused_by_event_id=None,
        )
        if not text:
            rejected = self._append_meeting_event(
                session=session,
                actor_id="rule_engine",
                event_type=EventType.MEETING_MESSAGE_REJECTED,
                payload={
                    "meeting_id": session.meeting.meeting_id,
                    "speaker_id": "player",
                    "reason": "meeting speech text is required",
                },
                caused_by_event_id=proposed.id,
            )
            return [proposed, rejected]
        posted = self.record_meeting_message(
            session=session,
            speaker_id="player",
            text=text,
            message_kind="speech",
            caused_by_event_id=proposed.id,
        )
        return [proposed, posted]

    def _apply_meeting_present_evidence(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        rejection = self._require_active_meeting(session=session, action=action)
        if rejection is not None:
            return [rejection]
        clue_id = str(action.clue_id)
        clue = next((item for item in case.clues if item.id == clue_id), None)
        if clue is None:
            return [
                self._reject(
                    session=session,
                    action_type="meeting.present_evidence",
                    reason="clue_id is not defined by the case package",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        if clue_id not in session.discovered_clues:
            return [
                self._reject(
                    session=session,
                    action_type="meeting.present_evidence",
                    reason="clue_id has not been discovered",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        knowledge_id = _player_knowledge_id_for_clue(case, clue_id)
        if knowledge_id not in session.player_knowledge:
            return [
                self._reject(
                    session=session,
                    action_type="meeting.present_evidence",
                    reason="clue_id is not available in player knowledge",
                    payload={**_player_action_payload(action), "knowledge_id": knowledge_id},
                    caused_by_event_id=None,
                )
            ]
        posted = self.record_meeting_message(
            session=session,
            speaker_id="player",
            text=action.text or f"展示证据：{clue.title}",
            message_kind="evidence",
            clue_id=clue_id,
            caused_by_event_id=None,
        )
        return [posted]

    def _apply_meeting_ask(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        rejection = self._require_active_meeting(session=session, action=action)
        if rejection is not None:
            return [rejection]
        if not self._is_known_character(case, action.target_id):
            return [
                self._reject(
                    session=session,
                    action_type="meeting.ask",
                    reason="target_id is not a known character",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        posted = self.record_meeting_message(
            session=session,
            speaker_id="player",
            text=action.text or f"请 {action.target_id} 回应这个议题。",
            message_kind="question",
            target_id=action.target_id,
            caused_by_event_id=None,
        )
        return [posted]

    def _apply_meeting_open_vote(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        rejection = self._require_active_meeting(session=session, action=action)
        if rejection is not None:
            return [rejection]
        if not self._is_known_character(case, action.target_id):
            return [
                self._reject(
                    session=session,
                    action_type="meeting.vote.opened",
                    reason="target_id is not a known character",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        event = self._append_meeting_event(
            session=session,
            actor_id="player",
            event_type=EventType.MEETING_VOTE_OPENED,
            payload={
                "meeting_id": session.meeting.meeting_id,
                "target_id": action.target_id,
                "text": action.text,
            },
            caused_by_event_id=None,
        )
        return [event]

    def _apply_meeting_cast_vote(
        self,
        *,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        rejection = self._require_active_meeting(session=session, action=action)
        if rejection is not None:
            return [rejection]
        if not session.meeting.vote_open or session.meeting.vote_target_id is None:
            return [
                self._reject(
                    session=session,
                    action_type="meeting.vote.cast",
                    reason="meeting vote is not open",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        if action.target_id != session.meeting.vote_target_id:
            return [
                self._reject(
                    session=session,
                    action_type="meeting.vote.cast",
                    reason="vote target does not match open vote",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        vote_event = self.record_meeting_vote(
            session=session,
            voter_id="player",
            target_id=action.target_id,
            choice=action.vote or MeetingVoteChoice.ABSTAIN,
            reason=action.text or "player vote",
            caused_by_event_id=None,
        )
        return [vote_event]

    def _apply_meeting_propose_verdict(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        rejection = self._require_active_meeting(session=session, action=action)
        if rejection is not None:
            return [rejection]
        if not self._is_known_character(case, action.target_id):
            return [
                self._reject(
                    session=session,
                    action_type="meeting.verdict.proposed",
                    reason="target_id is not a known character",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        claim_id = action.claim_id or self._default_claim_id(case, action.target_id)
        if claim_id is None:
            return [
                self._reject(
                    session=session,
                    action_type="meeting.verdict.proposed",
                    reason="no solution claim exists for target_id",
                    payload=_player_action_payload(action),
                    caused_by_event_id=None,
                )
            ]
        proposed = self._append_meeting_event(
            session=session,
            actor_id="player",
            event_type=EventType.MEETING_VERDICT_PROPOSED,
            payload={
                "meeting_id": session.meeting.meeting_id,
                "target_id": action.target_id,
                "claim_id": claim_id,
                "evidence_clue_ids": list(action.evidence_clue_ids),
                "text": action.text,
            },
            caused_by_event_id=None,
        )
        accusation_action = PlayerAction(
            type=ActionType.ACCUSE,
            target_id=action.target_id,
            claim_id=claim_id,
            evidence_clue_ids=list(action.evidence_clue_ids),
            text=action.text,
        )
        result = self._deduction_evaluator.evaluate(
            case=case,
            session=session,
            action=accusation_action,
        )
        if not result.accepted:
            reason, reject_payload = self._deduction_rejection_details(
                session=session,
                payload={
                    "target_id": action.target_id,
                    "claim_id": claim_id,
                    "evidence_clue_ids": list(action.evidence_clue_ids),
                    "text": action.text,
                },
                result=result,
            )
            rejected = self._append_meeting_event(
                session=session,
                actor_id="rule_engine",
                event_type=EventType.MEETING_VERDICT_REJECTED,
                payload={
                    "meeting_id": session.meeting.meeting_id,
                    "target_id": action.target_id,
                    "claim_id": claim_id,
                    "reason": reason,
                    "missing_required_evidence": result.missing_evidence,
                    "missing_required_world_info": result.missing_world_info,
                },
                caused_by_event_id=proposed.id,
            )
            rule_rejected = self._reject(
                session=session,
                action_type="meeting.verdict.proposed",
                reason=reason,
                payload=reject_payload,
                caused_by_event_id=rejected.id,
            )
            return [proposed, rejected, rule_rejected]

        accepted = self._append_meeting_event(
            session=session,
            actor_id="rule_engine",
            event_type=EventType.MEETING_VERDICT_ACCEPTED,
            payload={
                "meeting_id": session.meeting.meeting_id,
                "target_id": action.target_id,
                "claim_id": claim_id,
                "result": result.result,
                "matched_required_evidence": result.matched_required_evidence,
            },
            caused_by_event_id=proposed.id,
        )
        accused_event = self._recorder.append(
            session,
            actor_id="player",
            event_type=EventType.PLAYER_ACCUSED,
            payload={
                "target_id": action.target_id,
                "claim_id": claim_id,
                "evidence_clue_ids": result.evidence_clue_ids or [],
                "text": action.text,
                "source": "meeting_verdict",
            },
            caused_by_event_id=accepted.id,
        )
        evaluated_event = self._recorder.append(
            session,
            actor_id="rule_engine",
            event_type=EventType.ACCUSATION_EVALUATED,
            payload={
                "target_id": action.target_id,
                "claim_id": claim_id,
                "result": result.result,
                "matched_required_evidence": result.matched_required_evidence,
                "missing_required_evidence": result.missing_evidence,
                "source": "meeting_verdict",
            },
            caused_by_event_id=accused_event.id,
        )
        return [proposed, accepted, accused_event, evaluated_event]

    def _require_active_meeting(
        self,
        *,
        session: SessionState,
        action: PlayerAction,
    ) -> WorldEvent | None:
        if session.meeting.active:
            return None
        return self._reject(
            session=session,
            action_type=f"player.{action.type.value}",
            reason="meeting is not active",
            payload=_player_action_payload(action),
            caused_by_event_id=None,
        )

    def _default_claim_id(self, case: CasePackage, target_id: str) -> str | None:
        claim = next(
            (item for item in case.solution_claims.claims if item.target_id == target_id),
            None,
        )
        return claim.id if claim is not None else None

    def _deduction_rejection_details(
        self,
        *,
        session: SessionState,
        payload: dict[str, object],
        result: DeductionResult,
    ) -> tuple[str, dict[str, object]]:
        match result.reject_code:
            case "unknown_target":
                return "target_id is not a known character", payload
            case "unknown_claim":
                return "claim_id is not defined by the case package", payload
            case "target_mismatch":
                return "claim target_id does not match action target_id", payload
            case "phase_not_allowed":
                return (
                    "claim is not allowed in current narrative phase",
                    {**payload, "current_phase": session.narrative.phase},
                )
            case "empty_evidence":
                return "evidence_clue_ids cannot be empty", payload
            case "unknown_evidence":
                return (
                    "evidence_clue_ids contain unknown clues",
                    {**payload, "unknown_evidence": result.unknown_evidence or []},
                )
            case "undiscovered_evidence":
                return (
                    "evidence clues have not all been discovered",
                    {
                        **payload,
                        "undiscovered_evidence": result.undiscovered_evidence or [],
                    },
                )
            case "missing_player_knowledge":
                return (
                    "evidence clues are not all available in player knowledge",
                    {
                        **payload,
                        "missing_player_knowledge": result.missing_player_knowledge or [],
                    },
                )
            case "missing_required_evidence":
                return (
                    "evidence does not cover required claim evidence",
                    {**payload, "missing_required_evidence": result.missing_evidence},
                )
            case "missing_required_world_info":
                return (
                    "player knowledge does not cover required world info",
                    {
                        **payload,
                        "missing_required_world_info": result.missing_world_info,
                    },
                )
            case _:
                raise ValueError("deduction rejection is missing a reject_code")

    def _append_meeting_event(
        self,
        *,
        session: SessionState,
        actor_id: str,
        event_type: EventType,
        payload: dict[str, object],
        caused_by_event_id: str | None,
    ) -> WorldEvent:
        event = self._recorder.append(
            session,
            actor_id=actor_id,
            event_type=event_type,
            payload=payload,
            caused_by_event_id=caused_by_event_id,
        )
        self._project_meeting_event(session=session, event=event)
        return event

    def _project_meeting_event(self, *, session: SessionState, event: WorldEvent) -> None:
        payload = event.payload
        if event.type == EventType.MEETING_SESSION_STARTED:
            session.meeting = MeetingSessionState(
                active=True,
                meeting_id=str(payload["meeting_id"]),
                topic=_optional_payload_text(payload.get("topic")),
                participant_ids=[str(item) for item in payload.get("participant_ids", [])],
                started_at_event_id=event.id,
            )
            return
        if event.type == EventType.MEETING_SESSION_ENDED:
            session.meeting.active = False
            session.meeting.ended_at_event_id = event.id
            return
        if event.type == EventType.MEETING_TURN_OPENED:
            session.meeting.turn = int(payload.get("turn", session.meeting.turn + 1))
            return
        if event.type == EventType.MEETING_VOTE_OPENED:
            session.meeting.vote_open = True
            session.meeting.vote_target_id = _optional_payload_text(payload.get("target_id"))
            session.meeting.votes = {}
            return
        if event.type == EventType.MEETING_VOTE_CAST:
            voter_id = str(payload["voter_id"])
            session.meeting.votes[voter_id] = MeetingVoteState(
                voter_id=voter_id,
                target_id=str(payload["target_id"]),
                choice=MeetingVoteChoice(str(payload["choice"])),
                reason=_optional_payload_text(payload.get("reason")),
                event_id=event.id,
            )
            return
        if event.type == EventType.MEETING_VERDICT_PROPOSED:
            session.meeting.verdict_target_id = _optional_payload_text(
                payload.get("target_id")
            )
            session.meeting.verdict_status = "proposed"
            session.meeting.verdict_result = None
            session.meeting.verdict_reason = None
            session.meeting.missing_required_evidence = []
            session.meeting.missing_required_world_info = []
            session.meeting.verdict_event_id = event.id
            return
        if event.type == EventType.MEETING_VERDICT_ACCEPTED:
            session.meeting.vote_open = False
            session.meeting.verdict_target_id = _optional_payload_text(
                payload.get("target_id")
            )
            session.meeting.verdict_status = "accepted"
            session.meeting.verdict_result = _optional_payload_text(payload.get("result"))
            session.meeting.verdict_reason = None
            session.meeting.missing_required_evidence = []
            session.meeting.missing_required_world_info = []
            session.meeting.verdict_event_id = event.id
            return
        if event.type == EventType.MEETING_VERDICT_REJECTED:
            session.meeting.verdict_target_id = _optional_payload_text(
                payload.get("target_id")
            )
            session.meeting.verdict_status = "rejected"
            session.meeting.verdict_result = None
            session.meeting.verdict_reason = _optional_payload_text(payload.get("reason"))
            session.meeting.missing_required_evidence = [
                str(item) for item in payload.get("missing_required_evidence", [])
            ]
            session.meeting.missing_required_world_info = [
                str(item) for item in payload.get("missing_required_world_info", [])
            ]
            session.meeting.verdict_event_id = event.id
            return

    def _apply_relationship_change(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: RelationshipChangeAction,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        character_ids = {character.id for character in case.characters}
        valid_actor_ids = character_ids | {"player"}
        if action.source_id not in valid_actor_ids or action.target_id not in valid_actor_ids:
            return [
                self._reject(
                    session=session,
                    action_type=action.type,
                    reason="relationship endpoint is not a known character or player",
                    payload={
                        "source_id": action.source_id,
                        "target_id": action.target_id,
                        "deltas": action.deltas,
                    },
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        unknown_metrics = set(action.deltas) - RELATIONSHIP_METRICS
        if unknown_metrics:
            return [
                self._reject(
                    session=session,
                    action_type=action.type,
                    reason=f"unknown relationship metrics: {sorted(unknown_metrics)}",
                    payload={
                        "source_id": action.source_id,
                        "target_id": action.target_id,
                        "deltas": action.deltas,
                    },
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        key = relationship_key(action.source_id, action.target_id)
        relationship = session.relationships.get(key)
        if relationship is None:
            relationship = RelationshipState(source_id=action.source_id, target_id=action.target_id)
            session.relationships[key] = relationship

        previous_values = {field: getattr(relationship, field) for field in RELATIONSHIP_METRICS}
        for field, delta in action.deltas.items():
            current_value = getattr(relationship, field)
            setattr(relationship, field, clamp_relationship_metric(current_value + delta))

        events = [
            self._recorder.append(
                session,
                actor_id="system",
                event_type=EventType.RELATIONSHIP_CHANGED,
                payload={
                    "source_id": action.source_id,
                    "target_id": action.target_id,
                    "deltas": action.deltas,
                    "current": relationship.model_dump(mode="json"),
                },
                caused_by_event_id=caused_by_event_id,
            )
        ]
        events.extend(
            self._apply_relationship_thresholds(
                session=session,
                relationship=relationship,
                previous_values=previous_values,
                caused_by_event_id=events[-1].id,
            )
        )
        return events

    def _apply_discover_clue(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: DiscoverClueAction,
        caused_by_event_id: str,
    ) -> WorldEvent | None:
        clue_ids = {clue.id for clue in case.clues}
        if action.clue_id not in clue_ids:
            return self._reject(
                session=session,
                action_type=action.type,
                reason="clue_id is not defined by the case package",
                payload={"clue_id": action.clue_id},
                caused_by_event_id=caused_by_event_id,
            )
        if action.clue_id in session.discovered_clues:
            return None
        return self._discover_clue(
            session=session,
            clue_id=action.clue_id,
            payload={"clue_id": action.clue_id, "source": "agent_intent"},
            caused_by_event_id=caused_by_event_id,
        )

    def _apply_npc_autonomy_move(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        intent: object,
        actor_id: str,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        from_scene_id = autonomy_from_scene_id(intent)
        to_scene_id = autonomy_to_scene_id(intent)
        if to_scene_id is None:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="to_scene_id is required for move",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if not self._is_known_scene(case, to_scene_id):
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="to_scene_id is not a known scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if from_scene_id is not None and not self._is_known_scene(case, from_scene_id):
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="from_scene_id is not a known scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        current_scene_id = current_npc_scene_id(case, session, actor_id)
        if current_scene_id is None:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="actor_id has no known current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if from_scene_id is not None and from_scene_id != current_scene_id:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="from_scene_id does not match actor current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        payload = {
            "current": {
                "npc_id": actor_id,
                "scene_id": to_scene_id,
                "from_scene_id": current_scene_id,
                "updated_at_tick": session.town_clock.tick,
            }
        }
        rationale = autonomy_rationale(intent)
        if rationale is not None:
            payload["movement_reason"] = rationale
        event = self._append_npc_autonomy_event(
            session=session,
            actor_id=actor_id,
            event_type=NPC_LOCATION_CHANGED_EVENT_TYPE,
            payload=payload,
            caused_by_event_id=caused_by_event_id,
        )
        session.npc_locations[actor_id] = NpcLocationState(
            npc_id=actor_id,
            scene_id=to_scene_id,
            updated_at_tick=session.town_clock.tick,
            updated_at_event_id=event.id,
        )
        return [event]

    def _apply_npc_autonomy_observe(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        intent: object,
        actor_id: str,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        scene_id = autonomy_scene_id(intent)
        current_scene_id = current_npc_scene_id(case, session, actor_id)
        if current_scene_id is None:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="actor_id has no known current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if scene_id is not None and not self._is_known_scene(case, scene_id):
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="scene_id is not a known scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        effective_scene_id = scene_id or current_scene_id
        if effective_scene_id != current_scene_id:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="scene_id does not match actor current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        target_id = autonomy_target_id(intent)
        if target_id is not None and not self._is_observable_in_scene(
            case,
            session,
            target_id,
            effective_scene_id,
        ):
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="target_id is not observable in actor current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        payload: dict[str, object] = {
            "npc_id": actor_id,
            "type": NPC_AUTONOMY_OBSERVE,
            "scene_id": effective_scene_id,
            "status": "accepted",
        }
        if target_id is not None:
            payload["target_id"] = target_id
        rationale = autonomy_rationale(intent)
        if rationale is not None:
            payload["rationale"] = rationale
        return [
            self._append_npc_autonomy_event(
                session=session,
                actor_id=actor_id,
                event_type=EventType.NPC_AUTONOMY_INTENT_PROPOSED,
                payload=payload,
                caused_by_event_id=caused_by_event_id,
            )
        ]

    def _apply_npc_autonomy_wait(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        intent: object,
        actor_id: str,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        scene_id = autonomy_scene_id(intent)
        current_scene_id = current_npc_scene_id(case, session, actor_id)
        if current_scene_id is None:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="actor_id has no known current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if scene_id is not None and not self._is_known_scene(case, scene_id):
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="scene_id is not a known scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        effective_scene_id = scene_id or current_scene_id
        if effective_scene_id != current_scene_id:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="scene_id does not match actor current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        payload: dict[str, object] = {
            "npc_id": actor_id,
            "type": NPC_AUTONOMY_WAIT,
            "scene_id": effective_scene_id,
            "status": "accepted",
        }
        rationale = autonomy_rationale(intent)
        if rationale is not None:
            payload["rationale"] = rationale
        return [
            self._append_npc_autonomy_event(
                session=session,
                actor_id=actor_id,
                event_type=EventType.NPC_AUTONOMY_INTENT_PROPOSED,
                payload=payload,
                caused_by_event_id=caused_by_event_id,
            )
        ]

    def _apply_npc_autonomy_talk_to(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        intent: object,
        actor_id: str,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        target_id = autonomy_target_id(intent)
        if target_id is None:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="target_id is required for talk_to",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if not self._is_known_character(case, target_id):
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="target_id is not a known character",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if target_id == actor_id:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="target_id must be another character",
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        actor_scene_id = current_npc_scene_id(case, session, actor_id)
        target_scene_id = current_npc_scene_id(case, session, target_id)
        if actor_scene_id is None or target_scene_id is None:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="actor or target has no known current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        requested_scene_id = autonomy_scene_id(intent)
        if requested_scene_id is not None and not self._is_known_scene(case, requested_scene_id):
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="scene_id is not a known scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if requested_scene_id is not None and requested_scene_id != actor_scene_id:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="scene_id does not match actor current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]
        if actor_scene_id != target_scene_id:
            return [
                self._reject_npc_autonomy(
                    session=session,
                    intent=intent,
                    reason="target_id is not in actor current scene",
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        payload: dict[str, object] = {
            "npc_id": actor_id,
            "type": NPC_AUTONOMY_TALK_TO,
            "target_character_id": target_id,
            "scene_id": actor_scene_id,
            "status": "accepted",
        }
        rationale = autonomy_rationale(intent)
        if rationale is not None:
            payload["rationale"] = rationale
        return [
            self._append_npc_autonomy_event(
                session=session,
                actor_id=actor_id,
                event_type=EventType.NPC_AUTONOMY_INTENT_PROPOSED,
                payload=payload,
                caused_by_event_id=caused_by_event_id,
            )
        ]

    def _backtrack_unlock_ready(
        self,
        session: SessionState,
        hotspot_id: str,
        unlock: BacktrackClueUnlockConfig,
        current_inspect_event_id: str,
    ) -> bool:
        conditions = unlock.conditions
        if conditions.phases and session.narrative.phase not in conditions.phases:
            return False
        if not set(conditions.completed_beats).issubset(session.narrative.completed_beats):
            return False
        if not set(conditions.discovered_clues).issubset(session.discovered_clues):
            return False
        if not set(conditions.player_knowledge_ids).issubset(session.player_knowledge):
            return False
        player_world_info_ids = {
            knowledge.world_info_id
            for knowledge in session.player_knowledge.values()
            if knowledge.world_info_id is not None
        }
        if not set(conditions.player_world_info_ids).issubset(player_world_info_ids):
            return False
        required_prior_hotspots = conditions.prior_inspected_hotspots or [hotspot_id]
        for prior_hotspot_id in required_prior_hotspots:
            if (
                self._prior_inspect_count(
                    session,
                    prior_hotspot_id,
                    exclude_event_id=current_inspect_event_id,
                )
                < conditions.min_prior_inspections
            ):
                return False
        return True

    def _prior_inspect_count(
        self,
        session: SessionState,
        hotspot_id: str,
        *,
        exclude_event_id: str,
    ) -> int:
        return sum(
            1
            for event in session.events
            if event.type == EventType.PLAYER_INSPECTED
            and event.id != exclude_event_id
            and event.payload.get("target_id") == hotspot_id
        )

    def _discover_clue(
        self,
        *,
        session: SessionState,
        clue_id: str,
        payload: dict[str, object],
        caused_by_event_id: str,
    ) -> WorldEvent | None:
        if clue_id in session.discovered_clues:
            return None
        session.discovered_clues.add(clue_id)
        session.narrative.discovered_clues.add(clue_id)
        return self._recorder.append(
            session,
            actor_id="system",
            event_type=EventType.CLUE_DISCOVERED,
            payload=payload,
            caused_by_event_id=caused_by_event_id,
        )

    def _reject(
        self,
        *,
        session: SessionState,
        action_type: ProposedActionType | str,
        reason: str,
        payload: dict[str, object],
        caused_by_event_id: str | None,
    ) -> WorldEvent:
        return self._recorder.append(
            session,
            actor_id="rule_engine",
            event_type=EventType.RULE_REJECTED,
            payload={
                "action_type": action_type,
                "reason": reason,
                "proposed_payload": payload,
            },
            caused_by_event_id=caused_by_event_id,
        )

    def _apply_relationship_thresholds(
        self,
        *,
        session: SessionState,
        relationship: RelationshipState,
        previous_values: dict[str, float],
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        for metric, (threshold, state_name) in RELATIONSHIP_THRESHOLDS.items():
            previous_value = previous_values.get(metric, 0.0)
            current_value = getattr(relationship, metric)
            threshold_key = relationship_threshold_key(
                relationship.source_id,
                relationship.target_id,
                metric,
                state_name,
            )
            if threshold_key in session.relationship_thresholds_crossed:
                continue
            if previous_value < threshold <= current_value:
                session.relationship_thresholds_crossed.add(threshold_key)
                events.append(
                    self._recorder.append(
                        session,
                        actor_id="system",
                        event_type=EventType.RELATIONSHIP_THRESHOLD_CROSSED,
                        payload={
                            "source_id": relationship.source_id,
                            "target_id": relationship.target_id,
                            "metric": metric,
                            "threshold": threshold,
                            "state": state_name,
                            "current_value": current_value,
                        },
                        caused_by_event_id=caused_by_event_id,
                    )
                )
        return events

    def _reject_npc_autonomy(
        self,
        *,
        session: SessionState,
        intent: object,
        reason: str,
        caused_by_event_id: str,
    ) -> WorldEvent:
        return self._reject(
            session=session,
            action_type=autonomy_action_type(intent),
            reason=reason,
            payload=autonomy_payload(intent),
            caused_by_event_id=caused_by_event_id,
        )

    def _append_npc_autonomy_event(
        self,
        *,
        session: SessionState,
        actor_id: str,
        event_type: EventType | str,
        payload: dict[str, object],
        caused_by_event_id: str,
    ) -> WorldEvent:
        typed_event_type = (
            event_type if isinstance(event_type, EventType) else EventType(event_type)
        )
        return self._recorder.append(
            session,
            actor_id=actor_id,
            event_type=typed_event_type,
            payload=payload,
            caused_by_event_id=caused_by_event_id,
        )

    def _is_known_character(self, case: CasePackage, character_id: str) -> bool:
        return any(character.id == character_id for character in case.characters)

    def _is_known_scene(self, case: CasePackage, scene_id: str) -> bool:
        return any(scene.id == scene_id for scene in case.scenes)

    def _is_observable_in_scene(
        self,
        case: CasePackage,
        session: SessionState,
        target_id: str,
        scene_id: str,
    ) -> bool:
        if self._is_known_character(case, target_id):
            return current_npc_scene_id(case, session, target_id) == scene_id
        return any(
            scene.id == scene_id and any(hotspot.id == target_id for hotspot in scene.hotspots)
            for scene in case.scenes
        )

    def _hotspot(self, case: CasePackage, hotspot_id: str) -> SceneHotspotConfig | None:
        for scene in case.scenes:
            hotspot = next((item for item in scene.hotspots if item.id == hotspot_id), None)
            if hotspot is not None:
                return hotspot
        return None

    def _scene_for_presented_clue(
        self,
        case: CasePackage,
        session: SessionState,
        target_id: str,
        scene_id: str | None,
    ) -> SceneConfig | None:
        if scene_id is None:
            return None
        scene = next((item for item in case.scenes if item.id == scene_id), None)
        if scene is None or current_npc_scene_id(case, session, target_id) != scene.id:
            return None
        return scene

    def _character_ids_in_scene(
        self,
        case: CasePackage,
        session: SessionState,
        scene_id: str,
    ) -> list[str]:
        return [
            character.id
            for character in case.characters
            if current_npc_scene_id(case, session, character.id) == scene_id
        ]


def relationship_key(source_id: str, target_id: str) -> str:
    return f"{source_id}->{target_id}"


def relationship_threshold_key(
    source_id: str,
    target_id: str,
    metric: str,
    state_name: str,
) -> str:
    return f"{source_id}->{target_id}:{metric}:{state_name}"


def player_knowledge_id_for_clue(case: CasePackage, clue_id: str) -> str:
    return _player_knowledge_id_for_clue(case, clue_id)


def _player_action_payload(action: PlayerAction) -> dict[str, object]:
    return action.model_dump(mode="json", exclude_none=True)


def _optional_payload_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
