from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.domain.models import CasePackage, PlayerAction, SessionState

ALL_MEMORY_TYPES = ("episodic", "belief", "relationship", "strategy")
AGENT_MEMORY_SCOPES = ("case", "session", "npc_private", "scene_shared")
ALL_MEMORY_LAYERS = ("core", "working", "archival")
HARD_FORBIDDEN_SCOPES = ("director_audit",)
HARD_FORBIDDEN_LAYERS = ("archival",)
DEFAULT_MAX_MEMORY_ITEMS = 8
REQUIRED_SKILL_FIELDS = {
    "id",
    "description",
    "trigger",
    "include",
    "forbid",
    "projection",
    "disclosure",
}


@dataclass(frozen=True)
class MemoryProjectionSkill:
    id: str
    description: str
    trigger: dict[str, Any]
    include: dict[str, Any]
    forbid: dict[str, Any]
    projection: dict[str, Any]
    disclosure: dict[str, Any]
    body: str
    source_path: Path


@dataclass(frozen=True)
class MemoryRetrievalPlan:
    skill_id: str
    included_memory_types: tuple[str, ...]
    included_scopes: tuple[str, ...]
    included_layers: tuple[str, ...]
    forbidden_scopes: tuple[str, ...]
    forbidden_layers: tuple[str, ...]
    max_memory_items: int
    inject_portrait_summary: bool
    allow_recent_events: bool
    handoff_to_director: bool = False
    disclosure_level: str | None = None

    def trace_summary(self, *, selected_count: int) -> dict[str, object]:
        return {
            "skill_id": self.skill_id,
            "included_memory_types": list(self.included_memory_types),
            "included_scopes": list(self.included_scopes),
            "included_layers": list(self.included_layers),
            "forbidden_scopes": list(self.forbidden_scopes),
            "forbidden_layers": list(self.forbidden_layers),
            "selected_count": selected_count,
        }


class SkillLoader:
    def __init__(
        self,
        *,
        app_skill_dir: Path | None = None,
        cases_root: Path | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self._app_skill_dir = app_skill_dir or (
            Path(__file__).resolve().parent / "skills" / "memory_projection"
        )
        self._cases_root = cases_root or (project_root / "cases")

    def load(self, case: CasePackage) -> list[MemoryProjectionSkill]:
        skills: dict[str, MemoryProjectionSkill] = {}
        for path in self._skill_paths(self._app_skill_dir):
            skill = self._load_file(path)
            skills[skill.id] = skill
        case_skill_dir = (
            self._cases_root
            / case.meta.id
            / "skills"
            / "memory_projection"
        )
        for path in self._skill_paths(case_skill_dir):
            skill = self._load_file(path)
            skills[skill.id] = skill
        return [skills[skill_id] for skill_id in sorted(skills)]

    def _skill_paths(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(directory.glob("*.md"))

    def _load_file(self, path: Path) -> MemoryProjectionSkill:
        frontmatter, body = _split_frontmatter(path)
        missing = REQUIRED_SKILL_FIELDS - set(frontmatter)
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise ValueError(f"Memory projection skill {path} is missing {missing_fields}")
        return MemoryProjectionSkill(
            id=str(frontmatter["id"]),
            description=str(frontmatter["description"]),
            trigger=_mapping(frontmatter["trigger"], field_name="trigger", path=path),
            include=_mapping(frontmatter["include"], field_name="include", path=path),
            forbid=_mapping(frontmatter["forbid"], field_name="forbid", path=path),
            projection=_mapping(
                frontmatter["projection"],
                field_name="projection",
                path=path,
            ),
            disclosure=_mapping(
                frontmatter["disclosure"],
                field_name="disclosure",
                path=path,
            ),
            body=body,
            source_path=path,
        )


class SkillSelector:
    def select(
        self,
        *,
        skills: list[MemoryProjectionSkill],
        action: PlayerAction,
    ) -> MemoryProjectionSkill:
        matches = [
            (_trigger_specificity(skill.trigger), skill.id, skill)
            for skill in skills
            if _trigger_matches(skill.trigger, action)
        ]
        if not matches:
            raise ValueError(f"No memory projection skill matches action {action.type.value}")
        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return matches[0][2]


class RetrievalPlanner:
    def __init__(
        self,
        *,
        skill_loader: SkillLoader | None = None,
        skill_selector: SkillSelector | None = None,
    ) -> None:
        self._skill_loader = skill_loader or SkillLoader()
        self._skill_selector = skill_selector or SkillSelector()

    def select_skill(
        self,
        *,
        case: CasePackage,
        action: PlayerAction,
    ) -> MemoryProjectionSkill:
        return self._skill_selector.select(
            skills=self._skill_loader.load(case),
            action=action,
        )

    def plan(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> MemoryRetrievalPlan:
        skill = self.select_skill(case=case, action=action)
        plan = _base_plan(skill)
        for rule in _progressive_rules(skill):
            when = _mapping(rule.get("when", {}), field_name="when", path=skill.source_path)
            if _conditions_match(when, case=case, session=session, action=action):
                plan = _apply_rule(plan, rule)
        return plan


def _split_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Memory projection skill {path} must start with YAML frontmatter")
    end_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if end_index is None:
        raise ValueError(f"Memory projection skill {path} has unterminated frontmatter")
    frontmatter = yaml.safe_load("\n".join(lines[1:end_index])) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError(f"Memory projection skill {path} frontmatter must be a mapping")
    return frontmatter, "\n".join(lines[end_index + 1 :]).strip()


def _mapping(value: object, *, field_name: str, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} field {field_name} must be a mapping")
    return dict(value)


TRIGGER_ACCESSORS: dict[str, Callable[[PlayerAction], str | None]] = {
    "action_type": lambda action: action.type.value,
    "subject_type": lambda action: action.subject_type.value
    if action.subject_type is not None
    else None,
    "presentation_mode": lambda action: action.effective_presentation_mode.value
    if action.effective_presentation_mode is not None
    else None,
}


def _trigger_matches(trigger: dict[str, Any], action: PlayerAction) -> bool:
    for key, expected in trigger.items():
        accessor = TRIGGER_ACCESSORS.get(key)
        if accessor is None:
            return False
        if not _value_matches(expected, accessor(action)):
            return False
    return True


def _trigger_specificity(trigger: dict[str, Any]) -> int:
    return sum(1 for value in trigger.values() if value not in (None, "*", ["*"]))


def _value_matches(expected: object, actual: str | None) -> bool:
    if expected == "*":
        return True
    if isinstance(expected, list):
        return actual in {str(item) for item in expected}
    return actual == str(expected)


def _base_plan(skill: MemoryProjectionSkill) -> MemoryRetrievalPlan:
    forbidden_scopes = _ordered_unique(
        [
            *_string_tuple(
                skill.forbid.get("memory_scopes"),
                default=HARD_FORBIDDEN_SCOPES,
            ),
            *HARD_FORBIDDEN_SCOPES,
        ]
    )
    forbidden_layers = _ordered_unique(
        [
            *_string_tuple(
                skill.forbid.get("memory_layers"),
                default=HARD_FORBIDDEN_LAYERS,
            ),
            *HARD_FORBIDDEN_LAYERS,
        ]
    )
    return MemoryRetrievalPlan(
        skill_id=skill.id,
        included_memory_types=_string_tuple(
            skill.include.get("memory_types"),
            default=ALL_MEMORY_TYPES,
        ),
        included_scopes=_without_forbidden(
            _string_tuple(
                skill.include.get("memory_scopes"),
                default=AGENT_MEMORY_SCOPES,
            ),
            forbidden_scopes,
        ),
        included_layers=_without_forbidden(
            _string_tuple(
                skill.include.get("memory_layers"),
                default=("core", "working"),
            ),
            forbidden_layers,
        ),
        forbidden_scopes=forbidden_scopes,
        forbidden_layers=forbidden_layers,
        max_memory_items=_int_value(
            skill.projection.get("max_memory_items"),
            default=DEFAULT_MAX_MEMORY_ITEMS,
        ),
        inject_portrait_summary=_bool_value(
            skill.projection.get("portrait_summary"),
            default=True,
        ),
        allow_recent_events=_bool_value(
            skill.projection.get("recent_events"),
            default=True,
        ),
        disclosure_level=_optional_str(skill.disclosure.get("level")),
    )


def _progressive_rules(skill: MemoryProjectionSkill) -> list[dict[str, Any]]:
    raw_rules = skill.disclosure.get("progressive", [])
    if not isinstance(raw_rules, list):
        raise ValueError(f"{skill.source_path} disclosure.progressive must be a list")
    return [
        dict(rule)
        for rule in raw_rules
        if isinstance(rule, dict)
    ]


def _apply_rule(
    plan: MemoryRetrievalPlan,
    rule: dict[str, Any],
) -> MemoryRetrievalPlan:
    include = rule.get("include", {})
    forbid = rule.get("forbid", {})
    projection = rule.get("projection", {})
    disclosure = rule.get("disclosure", {})
    include_map = include if isinstance(include, dict) else {}
    forbid_map = forbid if isinstance(forbid, dict) else {}
    projection_map = projection if isinstance(projection, dict) else {}
    disclosure_map = disclosure if isinstance(disclosure, dict) else {}

    forbidden_scopes = _ordered_unique(
        [
            *plan.forbidden_scopes,
            *_string_tuple(forbid_map.get("memory_scopes"), default=()),
            *HARD_FORBIDDEN_SCOPES,
        ]
    )
    forbidden_layers = _ordered_unique(
        [
            *plan.forbidden_layers,
            *_string_tuple(forbid_map.get("memory_layers"), default=()),
            *HARD_FORBIDDEN_LAYERS,
        ]
    )
    included_types = _string_tuple(
        include_map.get("memory_types"),
        default=plan.included_memory_types,
    )
    included_scopes = _without_forbidden(
        _string_tuple(
            include_map.get("memory_scopes"),
            default=plan.included_scopes,
        ),
        forbidden_scopes,
    )
    included_layers = _without_forbidden(
        _string_tuple(
            include_map.get("memory_layers"),
            default=plan.included_layers,
        ),
        forbidden_layers,
    )
    return MemoryRetrievalPlan(
        skill_id=plan.skill_id,
        included_memory_types=included_types,
        included_scopes=included_scopes,
        included_layers=included_layers,
        forbidden_scopes=forbidden_scopes,
        forbidden_layers=forbidden_layers,
        max_memory_items=_int_value(
            projection_map.get("max_memory_items"),
            default=plan.max_memory_items,
        ),
        inject_portrait_summary=_bool_value(
            projection_map.get("portrait_summary"),
            default=plan.inject_portrait_summary,
        ),
        allow_recent_events=_bool_value(
            projection_map.get("recent_events"),
            default=plan.allow_recent_events,
        ),
        handoff_to_director=_bool_value(
            disclosure_map.get("handoff_to_director"),
            default=plan.handoff_to_director,
        ),
        disclosure_level=_optional_str(disclosure_map.get("level"))
        or plan.disclosure_level,
    )


CONDITION_EVALUATORS: dict[
    str,
    Callable[[object, CasePackage, SessionState, PlayerAction], bool],
] = {
    "phase": lambda expected, case, session, action: _value_matches(
        expected,
        session.narrative.phase,
    ),
    "phase_in": lambda expected, case, session, action: _value_matches(
        expected,
        session.narrative.phase,
    ),
    "completed_beats_any": lambda expected, case, session, action: bool(
        set(_string_tuple(expected, default=())) & set(session.narrative.completed_beats)
    ),
    "completed_beats_all": lambda expected, case, session, action: set(
        _string_tuple(expected, default=())
    ).issubset(session.narrative.completed_beats),
    "subject_clue_discovered": lambda expected, case, session, action: _bool_value(
        expected,
        default=False,
    )
    == _subject_clue_discovered(session, action),
}


def _conditions_match(
    conditions: dict[str, Any],
    *,
    case: CasePackage,
    session: SessionState,
    action: PlayerAction,
) -> bool:
    for key, expected in conditions.items():
        evaluator = CONDITION_EVALUATORS.get(key)
        if evaluator is None:
            return False
        if not evaluator(expected, case, session, action):
            return False
    return True


def _subject_clue_discovered(session: SessionState, action: PlayerAction) -> bool:
    clue_id = action.clue_id
    if clue_id is None and action.subject_type == "clue":
        clue_id = action.subject_id
    if clue_id is None:
        return True
    return clue_id in session.discovered_clues


def _string_tuple(value: object, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if value == "*":
        return default
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    return default


def _without_forbidden(
    values: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> tuple[str, ...]:
    forbidden_set = set(forbidden)
    return tuple(value for value in values if value not in forbidden_set)


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def _int_value(value: object, *, default: int) -> int:
    if value is None:
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _bool_value(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
