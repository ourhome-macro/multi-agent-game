from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, replace
from enum import StrEnum

from app.domain.models import ActionType, CasePackage, PlayerAction, SubjectType


class ActionRouteStatus(StrEnum):
    RESOLVED = "resolved"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNKNOWN = "unknown"


class ClassifiedAction(StrEnum):
    INSPECT = "inspect"
    TALK = "talk"
    ASK_ABOUT = "ask_about"
    PRESENT_CLUE = "present_clue"
    ACCUSE = "accuse"


class EntityKind(StrEnum):
    CHARACTER = "character"
    CLUE = "clue"
    HOTSPOT = "hotspot"
    SCENE = "scene"
    CLAIM = "claim"


class EntityResolveStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassificationResult:
    status: ActionRouteStatus
    action: ClassifiedAction | None
    confidence: float
    reason: str | None = None


@dataclass(frozen=True)
class EntityRef:
    id: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class EntityMatch:
    id: str
    alias: str
    score: float
    strategy: str = "alias_exact"


@dataclass(frozen=True)
class EntityResolveResult:
    status: EntityResolveStatus
    best_id: str | None
    matches: list[EntityMatch] = field(default_factory=list)
    reason: str | None = None

    @property
    def candidate_ids(self) -> list[str]:
        return list(dict.fromkeys(match.id for match in self.matches))


@dataclass(frozen=True)
class RouterTrace:
    raw_text_hash: str
    raw_text_length: int
    recognized_action: str | None
    target_candidates: list[str] = field(default_factory=list)
    subject_candidates: list[str] = field(default_factory=list)
    confidence: float = 0.0
    resolver_strategy: str | None = None
    director_precheck_result: str | None = None
    reason: str | None = None

    @classmethod
    def from_text(
        cls,
        raw_text: str,
        *,
        recognized_action: str | None = None,
        target_candidates: list[str] | None = None,
        subject_candidates: list[str] | None = None,
        confidence: float = 0.0,
        resolver_strategy: str | None = None,
        reason: str | None = None,
    ) -> RouterTrace:
        return cls(
            raw_text_hash=_hash_text(raw_text),
            raw_text_length=len(raw_text),
            recognized_action=recognized_action,
            target_candidates=target_candidates or [],
            subject_candidates=subject_candidates or [],
            confidence=confidence,
            resolver_strategy=resolver_strategy,
            reason=reason,
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "raw_text_hash": self.raw_text_hash,
            "raw_text_length": self.raw_text_length,
            "recognized_action": self.recognized_action,
            "target_candidates": self.target_candidates,
            "subject_candidates": self.subject_candidates,
            "confidence": self.confidence,
            "resolver_strategy": self.resolver_strategy,
            "director_precheck_result": self.director_precheck_result,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RouteResult:
    action: PlayerAction | None
    confidence: float
    status: ActionRouteStatus
    trace: RouterTrace
    needs_clarification: bool = False
    missing_slots: list[str] = field(default_factory=list)
    reason: str | None = None

    def with_director_precheck(self, result: str) -> RouteResult:
        return replace(
            self,
            trace=replace(self.trace, director_precheck_result=result),
        )


class ActionClassifier:
    def classify(self, raw_text: str) -> ClassificationResult:
        text = raw_text.strip()
        if not text:
            return ClassificationResult(
                status=ActionRouteStatus.NEEDS_CLARIFICATION,
                action=None,
                confidence=0.0,
                reason="empty_player_input",
            )
        if _has_multiple_actions(text):
            return ClassificationResult(
                status=ActionRouteStatus.NEEDS_CLARIFICATION,
                action=None,
                confidence=0.0,
                reason="multiple_actions_detected",
            )
        if _has_negated_accusation(text):
            if _has_any(text, TALK_MARKERS) or _has_any(text, ASK_MARKERS):
                return ClassificationResult(
                    status=ActionRouteStatus.RESOLVED,
                    action=ClassifiedAction.TALK,
                    confidence=0.58,
                )
            return ClassificationResult(
                status=ActionRouteStatus.UNKNOWN,
                action=None,
                confidence=0.0,
                reason="negated_accusation",
            )
        if _has_present_pattern(text):
            return ClassificationResult(
                status=ActionRouteStatus.RESOLVED,
                action=ClassifiedAction.PRESENT_CLUE,
                confidence=0.88,
            )
        if _has_any(text, ACCUSE_MARKERS):
            return ClassificationResult(
                status=ActionRouteStatus.RESOLVED,
                action=ClassifiedAction.ACCUSE,
                confidence=0.84,
            )
        if _looks_like_inspecting_object(text) and not _has_ask_marker(text):
            return ClassificationResult(
                status=ActionRouteStatus.RESOLVED,
                action=ClassifiedAction.INSPECT,
                confidence=0.82,
            )
        if _has_ask_marker(text):
            if _looks_like_ask_about(text):
                return ClassificationResult(
                    status=ActionRouteStatus.RESOLVED,
                    action=ClassifiedAction.ASK_ABOUT,
                    confidence=0.82,
                )
            return ClassificationResult(
                status=ActionRouteStatus.RESOLVED,
                action=ClassifiedAction.TALK,
                confidence=0.62,
                )
        if _looks_like_observing_character_response(text):
            return ClassificationResult(
                status=ActionRouteStatus.RESOLVED,
                action=ClassifiedAction.TALK,
                confidence=0.66,
            )
        if _has_any(text, TALK_MARKERS):
            return ClassificationResult(
                status=ActionRouteStatus.RESOLVED,
                action=ClassifiedAction.TALK,
                confidence=0.78,
            )
        if _has_any(text, INSPECT_MARKERS):
            return ClassificationResult(
                status=ActionRouteStatus.RESOLVED,
                action=ClassifiedAction.INSPECT,
                confidence=0.82,
            )
        return ClassificationResult(
            status=ActionRouteStatus.UNKNOWN,
            action=None,
            confidence=0.0,
            reason="unknown_action",
        )


class EntityResolver:
    def __init__(self, case: CasePackage) -> None:
        self._refs = {
            EntityKind.CHARACTER: _character_refs(case),
            EntityKind.CLUE: _clue_refs(case),
            EntityKind.HOTSPOT: _hotspot_refs(case),
            EntityKind.SCENE: _scene_refs(case),
            EntityKind.CLAIM: _claim_refs(case),
        }

    def resolve(
        self,
        raw_text: str,
        kind: EntityKind,
        *,
        exclude_ids: set[str] | None = None,
    ) -> EntityResolveResult:
        refs = [
            ref for ref in self._refs[kind] if exclude_ids is None or ref.id not in exclude_ids
        ]
        matches = _matches(raw_text, refs)
        if not matches and kind == EntityKind.CHARACTER and _has_generic_doctor(raw_text):
            matches = _doctor_matches(refs)
        if not matches:
            return EntityResolveResult(
                status=EntityResolveStatus.UNKNOWN,
                best_id=None,
                reason=f"unknown_{kind.value}",
            )
        candidate_ids = list(dict.fromkeys(match.id for match in matches))
        if len(candidate_ids) > 1 and _is_ambiguous_top_match(matches):
            return EntityResolveResult(
                status=EntityResolveStatus.AMBIGUOUS,
                best_id=None,
                matches=matches,
                reason=f"ambiguous_{kind.value}",
            )
        return EntityResolveResult(
            status=EntityResolveStatus.RESOLVED,
            best_id=matches[0].id,
            matches=matches,
        )

    def matches(
        self,
        raw_text: str,
        kind: EntityKind,
        *,
        exclude_ids: set[str] | None = None,
    ) -> list[EntityMatch]:
        refs = [
            ref for ref in self._refs[kind] if exclude_ids is None or ref.id not in exclude_ids
        ]
        return _matches(raw_text, refs)


class ActionRouter:
    def __init__(self, case: CasePackage) -> None:
        self._case = case
        self._classifier = ActionClassifier()
        self._resolver = EntityResolver(case)

    def route(self, raw_text: str) -> RouteResult:
        text = raw_text.strip()
        classification = self._classifier.classify(text)
        if classification.status == ActionRouteStatus.NEEDS_CLARIFICATION:
            return _clarify(
                text,
                ["action"],
                classification.reason or "ambiguous_route",
                target_candidates=[],
                subject_candidates=[],
            )
        if classification.status == ActionRouteStatus.UNKNOWN:
            fallback = self._route_fallback(text, classification)
            if fallback is not None:
                return fallback
            return _unknown(text, classification.reason or "unknown_action")

        if classification.action == ClassifiedAction.INSPECT:
            return self._route_inspect(text, classification)
        if classification.action == ClassifiedAction.TALK:
            return self._route_talk(text, classification)
        if classification.action == ClassifiedAction.ASK_ABOUT:
            return self._route_ask_about(text, classification)
        if classification.action == ClassifiedAction.PRESENT_CLUE:
            return self._route_present_clue(text, classification)
        if classification.action == ClassifiedAction.ACCUSE:
            return self._route_accuse(text, classification)
        return _unknown(text, "unknown_action")

    def _route_inspect(
        self,
        text: str,
        classification: ClassificationResult,
    ) -> RouteResult:
        hotspot = self._resolver.resolve(text, EntityKind.HOTSPOT)
        if hotspot.status == EntityResolveStatus.RESOLVED and hotspot.best_id is not None:
            return _action_result(
                text,
                PlayerAction(type=ActionType.INSPECT, target_id=hotspot.best_id),
                classification.confidence,
                target_candidates=hotspot.candidate_ids,
                subject_candidates=[],
                resolver_strategy=_strategy(hotspot.matches),
            )
        if _has_generic_inspect_target(text):
            return _clarify(
                text,
                ["target"],
                "ambiguous_route",
                target_candidates=hotspot.candidate_ids,
                subject_candidates=[],
            )
        return _unknown(text, "unknown_hotspot")

    def _route_talk(
        self,
        text: str,
        classification: ClassificationResult,
    ) -> RouteResult:
        target = self._resolver.resolve(text, EntityKind.CHARACTER)
        if target.status == EntityResolveStatus.RESOLVED and target.best_id is not None:
            return _action_result(
                text,
                PlayerAction(type=ActionType.TALK, target_id=target.best_id, text=text),
                classification.confidence,
                target_candidates=target.candidate_ids,
                subject_candidates=[],
                resolver_strategy=_strategy(target.matches),
            )
        if target.status == EntityResolveStatus.AMBIGUOUS:
            return _clarify(
                text,
                ["target"],
                "ambiguous_route",
                target_candidates=target.candidate_ids,
                subject_candidates=[],
            )
        if _has_generic_character_target(text):
            return _clarify(
                text,
                ["target"],
                "ambiguous_route",
                target_candidates=target.candidate_ids,
                subject_candidates=[],
            )
        return _unknown(text, "unknown_target")

    def _route_ask_about(
        self,
        text: str,
        classification: ClassificationResult,
    ) -> RouteResult:
        target = self._resolver.resolve(text, EntityKind.CHARACTER)
        subject_type, subject_id, subject_candidates, subject_status = self._resolve_subject(
            text,
            target_id=target.best_id,
        )
        missing: list[str] = []
        if target.status == EntityResolveStatus.AMBIGUOUS:
            missing.append("target")
        elif target.status == EntityResolveStatus.UNKNOWN:
            if _has_unknown_named_character(text):
                return _unknown(
                    text,
                    "unknown_target",
                    target_candidates=target.candidate_ids,
                    subject_candidates=subject_candidates,
                )
            missing.append("target")
        if subject_status == EntityResolveStatus.AMBIGUOUS:
            missing.append("subject")
        elif subject_id is None:
            if _has_generic_subject_reference(text):
                missing.append("subject")
            elif _has_unknown_subject_reference(text):
                return _unknown(
                    text,
                    "unknown_subject",
                    target_candidates=target.candidate_ids,
                    subject_candidates=subject_candidates,
                )
            missing.append("subject")
        if missing:
            return _clarify(
                text,
                list(dict.fromkeys(missing)),
                "ambiguous_route",
                target_candidates=target.candidate_ids,
                subject_candidates=subject_candidates,
            )
        assert target.best_id is not None
        assert subject_type is not None
        assert subject_id is not None
        return _action_result(
            text,
            PlayerAction(
                type=ActionType.ASK_ABOUT,
                target_id=target.best_id,
                subject_type=subject_type,
                subject_id=subject_id,
                text=text,
            ),
            classification.confidence,
            target_candidates=target.candidate_ids,
            subject_candidates=subject_candidates,
            resolver_strategy=_combined_strategy(target.matches, subject_candidates),
        )

    def _route_present_clue(
        self,
        text: str,
        classification: ClassificationResult,
    ) -> RouteResult:
        target = self._resolver.resolve(text, EntityKind.CHARACTER)
        clue = self._resolver.resolve(text, EntityKind.CLUE)
        if target.status == EntityResolveStatus.UNKNOWN and _has_unknown_named_character(text):
            return _unknown(
                text,
                "unknown_target",
                target_candidates=target.candidate_ids,
                subject_candidates=clue.candidate_ids,
            )
        if clue.status == EntityResolveStatus.UNKNOWN and _has_unknown_subject_reference(text):
            return _unknown(
                text,
                "unknown_clue",
                target_candidates=target.candidate_ids,
                subject_candidates=clue.candidate_ids,
            )
        missing: list[str] = []
        if target.status != EntityResolveStatus.RESOLVED:
            missing.append("target")
        if clue.status != EntityResolveStatus.RESOLVED:
            if _has_unknown_subject_reference(text) and not _has_generic_subject_reference(text):
                return _unknown(
                    text,
                    "unknown_clue",
                    target_candidates=target.candidate_ids,
                    subject_candidates=clue.candidate_ids,
                )
            missing.append("clue")
        if missing:
            return _clarify(
                text,
                missing,
                "ambiguous_route",
                target_candidates=target.candidate_ids,
                subject_candidates=clue.candidate_ids,
            )
        assert target.best_id is not None
        assert clue.best_id is not None
        return _action_result(
            text,
            PlayerAction(
                type=ActionType.PRESENT_CLUE,
                target_id=target.best_id,
                clue_id=clue.best_id,
                text=text,
            ),
            classification.confidence,
            target_candidates=target.candidate_ids,
            subject_candidates=clue.candidate_ids,
            resolver_strategy=_strategy(target.matches + clue.matches),
        )

    def _route_accuse(
        self,
        text: str,
        classification: ClassificationResult,
    ) -> RouteResult:
        target = self._resolve_accuse_target(text)
        claim = self._resolver.resolve(text, EntityKind.CLAIM)
        if target.status == EntityResolveStatus.UNKNOWN and _has_unknown_named_character(text):
            return _unknown(
                text,
                "unknown_target",
                target_candidates=target.candidate_ids,
                subject_candidates=claim.candidate_ids,
            )
        if claim.status == EntityResolveStatus.UNKNOWN and target.best_id is not None:
            target_claims = [
                item
                for item in self._case.solution_claims.claims
                if item.target_id == target.best_id
            ]
            if len(target_claims) == 1:
                claim = EntityResolveResult(
                    status=EntityResolveStatus.RESOLVED,
                    best_id=target_claims[0].id,
                    matches=[
                        EntityMatch(
                            id=target_claims[0].id,
                            alias="target_default_claim",
                            score=0.6,
                            strategy="target_default_claim",
                        )
                    ],
                )
        missing: list[str] = []
        if target.status != EntityResolveStatus.RESOLVED:
            missing.append("target")
        if claim.status != EntityResolveStatus.RESOLVED:
            missing.append("claim")
        if missing:
            return _clarify(
                text,
                missing,
                "ambiguous_route",
                target_candidates=target.candidate_ids,
                subject_candidates=claim.candidate_ids,
            )
        assert target.best_id is not None
        assert claim.best_id is not None
        evidence = _matched_ids(self._resolver.matches(text, EntityKind.CLUE))
        return _action_result(
            text,
            PlayerAction(
                type=ActionType.ACCUSE,
                target_id=target.best_id,
                claim_id=claim.best_id,
                evidence_clue_ids=evidence,
                text=text,
            ),
            classification.confidence,
            target_candidates=target.candidate_ids,
            subject_candidates=claim.candidate_ids,
            resolver_strategy=_strategy(target.matches + claim.matches),
        )

    def _route_fallback(
        self,
        text: str,
        classification: ClassificationResult,
    ) -> RouteResult | None:
        if classification.reason == "negated_accusation":
            target = self._resolver.resolve(text, EntityKind.CHARACTER)
            if target.status == EntityResolveStatus.RESOLVED and target.best_id is not None:
                return _action_result(
                    text,
                    PlayerAction(type=ActionType.TALK, target_id=target.best_id, text=text),
                    0.42,
                    target_candidates=target.candidate_ids,
                    subject_candidates=[],
                    resolver_strategy=_strategy(target.matches),
                )
            return _unknown(text, "negated_accusation")

        target = self._resolver.resolve(text, EntityKind.CHARACTER)
        if target.status == EntityResolveStatus.RESOLVED and target.best_id is not None:
            return _action_result(
                text,
                PlayerAction(type=ActionType.TALK, target_id=target.best_id, text=text),
                0.45,
                target_candidates=target.candidate_ids,
                subject_candidates=[],
                resolver_strategy=_strategy(target.matches),
            )
        return None

    def _resolve_subject(
        self,
        text: str,
        *,
        target_id: str | None,
    ) -> tuple[SubjectType | None, str | None, list[str], EntityResolveStatus]:
        clue = self._resolver.resolve(text, EntityKind.CLUE)
        if clue.status == EntityResolveStatus.RESOLVED and clue.best_id is not None:
            return SubjectType.CLUE, clue.best_id, clue.candidate_ids, clue.status
        if clue.status == EntityResolveStatus.AMBIGUOUS:
            return None, None, clue.candidate_ids, clue.status
        if _has_generic_subject_reference(text):
            return None, None, [], EntityResolveStatus.UNKNOWN

        character = self._resolver.resolve(
            text,
            EntityKind.CHARACTER,
            exclude_ids={target_id} if target_id else None,
        )
        if character.status == EntityResolveStatus.RESOLVED and character.best_id is not None:
            return (
                SubjectType.CHARACTER,
                character.best_id,
                character.candidate_ids,
                character.status,
            )
        if character.status == EntityResolveStatus.AMBIGUOUS:
            return None, None, character.candidate_ids, character.status

        scene = self._resolver.resolve(text, EntityKind.SCENE)
        if scene.status == EntityResolveStatus.RESOLVED and scene.best_id is not None:
            return SubjectType.SCENE, scene.best_id, scene.candidate_ids, scene.status
        if scene.status == EntityResolveStatus.AMBIGUOUS:
            return None, None, scene.candidate_ids, scene.status
        return None, None, [], EntityResolveStatus.UNKNOWN

    def _resolve_accuse_target(self, text: str) -> EntityResolveResult:
        negation_target = _target_after_negation(text)
        if negation_target:
            positive_segment = text.split(negation_target, maxsplit=1)[-1]
            if positive_segment:
                target = self._resolver.resolve(positive_segment, EntityKind.CHARACTER)
                if target.status == EntityResolveStatus.RESOLVED:
                    return target
        return self._resolver.resolve(text, EntityKind.CHARACTER)


INSPECT_MARKERS = ("检查", "调查", "查看", "搜查", "观察", "看看", "检视")
TALK_MARKERS = ("说话", "聊天", "聊聊", "交谈", "谈谈", "对话")
ASK_MARKERS = ("问", "询问", "追问", "打听", "质问")
ACCUSE_MARKERS = (
    "指控",
    "控告",
    "认定",
    "正式指控",
    "凶手是",
    "是凶手",
    "造成",
    "导致",
    "怀疑",
    "认为",
)
PRESENT_MARKERS = ("给", "给看", "出示", "展示", "拿出", "拿给", "递给", "递", "让")
PRESENT_OBJECT_MARKERS = ("线索", "证据", "看", "空胶囊", "药盒", "药瓶", "门锁", "录音")
MULTI_ACTION_MARKERS = ("先", "再", "然后", "回来", "一边")
GENERIC_CHARACTER_TERMS = ("医生", "那个人", "他", "她", "那位")
GENERIC_SUBJECT_TERMS = ("那个东西", "线索", "证据", "药的事")
GENERIC_HOTSPOT_TERMS = ("那个地方", "现场", "地方")
UNKNOWN_CHARACTER_TERMS = ("张三", "猫")
UNKNOWN_SUBJECT_TERMS = ("不存在", "钥匙")

COMMON_CHARACTER_TITLES = (
    "医生",
    "先生",
    "女士",
    "律师",
    "顾问",
    "警官",
    "管家",
)

EXTRA_CHARACTER_ALIASES: dict[str, tuple[str, ...]] = {
    "jiang_yanhui": ("江医生", "江言晖", "江雁回", "江律师"),
    "shen_zhaoye": ("沈医生", "沈照夜", "照夜", "沈顾问"),
    "lin_qichi": ("林栖迟", "林女士", "林太太"),
    "qi_yan": ("祁宴", "祁编剧"),
    "butler": ("管家", "老管家", "韩管家"),
    "niece": ("侄女", "林侄女"),
}

COMMON_CLUE_ALIASES: dict[str, tuple[str, ...]] = {
    "bitter_wine": ("红酒", "苦味红酒", "红酒残液", "酒杯", "药酒"),
    "delayed_lock_marks": (
        "门锁",
        "书房门锁",
        "锁",
        "划痕",
        "锁痕",
        "门锁痕迹",
        "锁上的划痕",
        "延迟锁痕",
    ),
    "echo_tape": ("磁带", "录音带", "回声钟", "录音机"),
    "burned_confession": ("忏悔信", "烧毁的信", "纸灰", "壁炉纸灰", "附录"),
    "ruolan_voice_tape": ("江若岚录音", "若岚录音", "录音片段", "声音片段"),
    "empty_capsules": (
        "空胶囊",
        "胶囊",
        "胶囊壳",
        "空药壳",
        "药盒",
        "药瓶",
        "药瓶里的空胶囊",
        "心脏病胶囊",
    ),
    "cut_power_trace": ("电闸", "主电闸", "配电箱", "电箱", "断路器", "停电", "断电"),
    "scratched_drawer": ("抽屉", "抽屉划痕", "划痕", "书桌"),
    "torn_note": ("便签", "撕碎的便签", "纸条"),
    "dustless_frame": ("画框", "无尘画框", "肖像画"),
}

COMMON_HOTSPOT_ALIASES: dict[str, tuple[str, ...]] = {
    "wine_table": ("红酒", "酒杯", "红酒杯"),
    "study_lock": ("门锁", "书房门锁", "锁", "门锁痕迹", "锁上的划痕", "延迟锁痕"),
    "tape_recorder": ("录音机", "磁带", "录音带"),
    "burned_letter": ("壁炉", "壁炉纸灰", "纸灰", "烧毁的信"),
    "medicine_box": ("药盒", "胶囊", "药瓶", "空胶囊", "心脏病药盒", "药柜里的药盒"),
    "breaker_box": ("配电箱", "电箱", "电闸", "主电闸", "断路器"),
    "desk": ("书桌", "抽屉"),
    "carpet": ("地毯", "地面"),
    "portrait": ("肖像", "肖像画", "画框"),
}

COMMON_CLAIM_ALIASES: dict[str, tuple[str, ...]] = {
    "shared_death_chain": (
        "共同死亡链",
        "死亡链",
        "共同因果",
        "造成死亡",
        "造成共同死亡",
        "导致共同死亡链",
        "凶手",
    ),
    "lin_poisoned_lu": ("林栖迟下毒", "林下毒", "红酒下毒", "下毒", "毒杀"),
    "butler_moved_key": ("管家移动钥匙", "移动钥匙", "伪造书房"),
    "niece_staged_meeting": ("侄女伪造会面", "伪造会面"),
}


def _character_refs(case: CasePackage) -> list[EntityRef]:
    refs: list[EntityRef] = []
    for character in case.characters:
        aliases = {
            character.id,
            character.display_name,
            character.public_role,
            *EXTRA_CHARACTER_ALIASES.get(character.id, ()),
        }
        refs.append(EntityRef(id=character.id, aliases=_clean_aliases(aliases)))
    return refs


def _clue_refs(case: CasePackage) -> list[EntityRef]:
    return [
        EntityRef(
            id=clue.id,
            aliases=_clean_aliases(
                {
                    clue.id,
                    clue.title,
                    *COMMON_CLUE_ALIASES.get(clue.id, ()),
                },
                allow_generic=False,
            ),
        )
        for clue in case.clues
    ]


def _hotspot_refs(case: CasePackage) -> list[EntityRef]:
    refs: list[EntityRef] = []
    for scene in case.scenes:
        for hotspot in scene.hotspots:
            refs.append(
                EntityRef(
                    id=hotspot.id,
                    aliases=_clean_aliases(
                        {
                            hotspot.id,
                            hotspot.name,
                            *COMMON_HOTSPOT_ALIASES.get(hotspot.id, ()),
                        },
                        allow_generic=False,
                    ),
                )
            )
    return refs


def _scene_refs(case: CasePackage) -> list[EntityRef]:
    return [
        EntityRef(id=scene.id, aliases=_clean_aliases({scene.id, scene.name}))
        for scene in case.scenes
    ]


def _claim_refs(case: CasePackage) -> list[EntityRef]:
    return [
        EntityRef(
            id=claim.id,
            aliases=_clean_aliases(
                {claim.id, *COMMON_CLAIM_ALIASES.get(claim.id, ())},
                allow_generic=False,
            ),
        )
        for claim in case.solution_claims.claims
    ]


def _matches(text: str, refs: list[EntityRef]) -> list[EntityMatch]:
    normalized_text = _normalize(text)
    matches: list[EntityMatch] = []
    for ref in refs:
        for alias in ref.aliases:
            normalized_alias = _normalize(alias)
            if not normalized_alias:
                continue
            if normalized_alias in normalized_text:
                matches.append(
                    EntityMatch(
                        id=ref.id,
                        alias=alias,
                        score=_score_alias(normalized_alias, normalized_text),
                    )
                )
                break
    return sorted(matches, key=lambda item: (item.score, len(item.alias)), reverse=True)


def _matched_ids(matches: list[EntityMatch]) -> list[str]:
    return list(dict.fromkeys(match.id for match in matches))


def _score_alias(normalized_alias: str, normalized_text: str) -> float:
    exact_bonus = 0.4 if normalized_alias == normalized_text else 0.0
    coverage = min(len(normalized_alias) / max(len(normalized_text), 1), 1.0)
    length_bonus = min(len(normalized_alias) / 12, 0.5)
    return round(0.5 + exact_bonus + coverage + length_bonus, 4)


def _is_ambiguous_top_match(matches: list[EntityMatch]) -> bool:
    if len(matches) < 2:
        return False
    top_score = matches[0].score
    top_matches = [match for match in matches if abs(match.score - top_score) < 0.0001]
    return len({match.id for match in top_matches}) > 1


def _clean_aliases(aliases: set[str], *, allow_generic: bool = True) -> tuple[str, ...]:
    cleaned = {
        alias.strip()
        for alias in aliases
        if alias
        and len(_normalize(alias)) >= 2
        and (allow_generic or not _is_generic_alias(alias))
    }
    return tuple(sorted(cleaned, key=lambda item: (len(_normalize(item)), item), reverse=True))


def _is_generic_alias(alias: str) -> bool:
    return alias in {"线索", "证据", "人物", "地点", "房间", "现场"}


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _has_ask_marker(text: str) -> bool:
    if any(marker in text for marker in ("询问", "追问", "打听", "质问", "问问")):
        return True
    return re.search(r"问(?!题)", text) is not None


def _has_present_pattern(text: str) -> bool:
    if any(marker in text for marker in ("给看", "出示", "展示", "拿出", "拿给", "递给")):
        return True
    if "给" in text and "看" in text:
        return True
    if "让" in text and "看看" in text:
        return True
    return _has_any(text, PRESENT_MARKERS) and _has_any(text, PRESENT_OBJECT_MARKERS)


def _looks_like_ask_about(text: str) -> bool:
    if _looks_like_inspecting_object(text):
        return False
    if _has_generic_subject_reference(text):
        return True
    if "关于" in text or "的事" in text or "是不是" in text or "为什么" in text:
        return True
    if _has_any(text, tuple(COMMON_CLUE_ALIASES_ALIAS_FLAT)):
        return True
    return False


def _looks_like_inspecting_object(text: str) -> bool:
    return _has_any(text, INSPECT_MARKERS) and _has_any(
        text,
        (
            "药盒",
            "药瓶",
            "配电箱",
            "电箱",
            "电闸",
            "断路器",
            "门锁",
            "录音机",
            "壁炉",
        ),
    )


def _looks_like_observing_character_response(text: str) -> bool:
    return "看看" in text and _has_any(text, ("会说什么", "怎么说", "什么反应"))


COMMON_CLUE_ALIASES_ALIAS_FLAT = tuple(
    alias for aliases in COMMON_CLUE_ALIASES.values() for alias in aliases
)


def _has_multiple_actions(text: str) -> bool:
    marker_count = sum(1 for marker in MULTI_ACTION_MARKERS if marker in text)
    if marker_count == 0:
        return False
    action_hits = 0
    for markers in (
        INSPECT_MARKERS,
        TALK_MARKERS,
        ("询问", "追问", "打听", "质问", "问问", "问"),
        PRESENT_MARKERS,
        ACCUSE_MARKERS,
    ):
        if markers == ("询问", "追问", "打听", "质问", "问问", "问"):
            matched = _has_ask_marker(text)
        else:
            matched = _has_any(text, markers)
        if matched:
            action_hits += 1
    return action_hits >= 2


def _has_negated_accusation(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "不觉得",
            "不认为",
            "不指控",
            "没有要指控",
            "不是凶手",
        )
    )


def _target_after_negation(text: str) -> str | None:
    if "不是" in text:
        return "是"
    return None


def _has_generic_character_target(text: str) -> bool:
    return _has_any(text, GENERIC_CHARACTER_TERMS)


def _has_generic_doctor(text: str) -> bool:
    return "医生" in text


def _has_generic_inspect_target(text: str) -> bool:
    return _has_any(text, GENERIC_HOTSPOT_TERMS)


def _has_generic_subject_reference(text: str) -> bool:
    return _has_any(text, GENERIC_SUBJECT_TERMS)


def _has_unknown_named_character(text: str) -> bool:
    return _has_any(text, UNKNOWN_CHARACTER_TERMS)


def _has_unknown_subject_reference(text: str) -> bool:
    return _has_any(text, UNKNOWN_SUBJECT_TERMS)


def _strategy(matches: list[EntityMatch]) -> str | None:
    if not matches:
        return None
    return matches[0].strategy


def _combined_strategy(
    matches: list[EntityMatch],
    subject_candidates: list[str],
) -> str | None:
    if matches and subject_candidates:
        return matches[0].strategy
    return _strategy(matches)


def _action_result(
    text: str,
    action: PlayerAction,
    confidence: float,
    *,
    target_candidates: list[str],
    subject_candidates: list[str],
    resolver_strategy: str | None,
) -> RouteResult:
    return RouteResult(
        action=action,
        confidence=confidence,
        status=ActionRouteStatus.RESOLVED,
        trace=RouterTrace.from_text(
            text,
            recognized_action=action.type.value,
            target_candidates=target_candidates,
            subject_candidates=subject_candidates,
            confidence=confidence,
            resolver_strategy=resolver_strategy,
        ),
    )


def _clarify(
    text: str,
    missing_slots: list[str],
    reason: str,
    *,
    target_candidates: list[str],
    subject_candidates: list[str],
) -> RouteResult:
    return RouteResult(
        action=None,
        confidence=0.0,
        status=ActionRouteStatus.NEEDS_CLARIFICATION,
        needs_clarification=True,
        missing_slots=missing_slots,
        reason=reason,
        trace=RouterTrace.from_text(
            text,
            recognized_action=None,
            target_candidates=target_candidates,
            subject_candidates=subject_candidates,
            reason=reason,
        ),
    )


def _unknown(
    text: str,
    reason: str,
    *,
    target_candidates: list[str] | None = None,
    subject_candidates: list[str] | None = None,
) -> RouteResult:
    return RouteResult(
        action=None,
        confidence=0.0,
        status=ActionRouteStatus.UNKNOWN,
        reason=reason,
        trace=RouterTrace.from_text(
            text,
            recognized_action=None,
            target_candidates=target_candidates or [],
            subject_candidates=subject_candidates or [],
            reason=reason,
        ),
    )


def _hash_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _doctor_matches(refs: list[EntityRef]) -> list[EntityMatch]:
    matches = [
        EntityMatch(id=ref.id, alias="医生", score=1.0)
        for ref in refs
        if any("医生" in alias for alias in ref.aliases)
    ]
    return sorted(matches, key=lambda item: item.id)
