from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.agents.context import build_agent_context
from app.agents.llm_contract import build_llm_agent_input
from app.agents.real_llm_agent import OpenAILLMAgent
from app.domain.models import (
    ActionResponse,
    ActionType,
    CasePackage,
    EventType,
    PlayerAction,
    SessionState,
    WorldEvent,
)
from app.runtime.replay import replay_events
from app.runtime.service import RuntimeContainer
from app.scenarios.validation import read_scenario_yaml
from app.storage.memory import build_state_summary


@dataclass(frozen=True)
class ExpectedDirectorBlock:
    target_id: str
    blocked_fact_id: str
    world_info_id: str
    matched_by: str = "forbidden_term"
    matched_text: str = "[redacted]"
    safe_fallback_used: bool = True


@dataclass(frozen=True)
class ScenarioStep:
    name: str
    action: PlayerAction
    expected_events: list[EventType]
    expected_phase: str
    expected_player_world_info_ids: set[str]
    accepted: bool = True
    director_blocked: bool = False
    expected_new_awareness: list[tuple[str, str]] = field(default_factory=list)
    expected_block: ExpectedDirectorBlock | None = None


@dataclass(frozen=True)
class ScenarioEvaluationSpec:
    case_id: str
    expected_final_phase: str
    expected_final_beats: set[str]
    expected_final_player_world_info_ids: set[str]
    forbidden_public_terms: set[str]
    steps: list[ScenarioStep]


@dataclass(frozen=True)
class ScenarioEvaluationResult:
    session: SessionState
    responses: list[ActionResponse]


_SCENARIO_FIELDS = frozenset(
    {
        "case_id",
        "expected_final_phase",
        "expected_final_beats",
        "expected_final_player_world_info_ids",
        "forbidden_public_terms",
        "steps",
        "reconstruction",
    }
)
_SCENARIO_STEP_FIELDS = frozenset(
    {
        "name",
        "label",
        "action",
        "expected_events",
        "expected_phase",
        "expected_player_world_info_ids",
        "accepted",
        "director_blocked",
        "expected_new_awareness",
        "expected_block",
    }
)
_EXPECTED_DIRECTOR_BLOCK_FIELDS = frozenset(
    {
        "target_id",
        "blocked_fact_id",
        "world_info_id",
        "matched_by",
        "matched_text",
        "safe_fallback_used",
    }
)
_EXPECTED_AWARENESS_FIELDS = frozenset({"character_id", "world_info_id"})


def load_standard_scenario_evaluation_spec(
    case_id: str,
    *,
    cases_root: str | Path = Path("cases"),
) -> ScenarioEvaluationSpec:
    scenario_path = Path(cases_root) / case_id / "scenarios" / "standard_path.yaml"
    return load_scenario_evaluation_spec(scenario_path)


def load_scenario_evaluation_spec(path: str | Path) -> ScenarioEvaluationSpec:
    scenario_path = Path(path)
    raw_scenario = _read_scenario_yaml(scenario_path)
    return _build_scenario_evaluation_spec(raw_scenario, scenario_path)


class ScenarioEvaluationHarness:
    def __init__(
        self,
        *,
        case: CasePackage,
        runtime: RuntimeContainer,
        spec: ScenarioEvaluationSpec,
    ) -> None:
        self._case = case
        self._runtime = runtime
        self._spec = spec
        self._world_info_ids = {world_info.id for world_info in case.world_info}
        self._forbidden_terms = {
            blocked_term
            for fact in case.forbidden_facts
            for blocked_term in fact.blocked_terms
        } | spec.forbidden_public_terms
        self._private_values = _private_character_values(case)

    def run(self) -> ScenarioEvaluationResult:
        session = self._runtime.session_store.create(self._case)
        responses: list[ActionResponse] = []

        self._assert_initial_state(session)
        for step in self._spec.steps:
            before_event_count = len(session.events)
            response = self._runtime.action_service.handle(
                session=session,
                action=step.action,
            )
            responses.append(response)

            self._assert_step_response(step, response, session)
            self._assert_step_awareness_delta(
                step=step,
                session=session,
                before_event_count=before_event_count,
            )
            self._assert_public_outputs_are_sanitized(response=response, session=session)
            self._assert_narrative_phase_authority(response.new_events)
            self._assert_player_knowledge_is_world_info_anchored(session)
            self._assert_disclosure_claims_are_auditable(response.new_events, session)
            self._assert_context_strategy_consistency(step.action, session)

        self._assert_final_state(session)
        self._assert_replay_equivalence(session)
        return ScenarioEvaluationResult(session=session, responses=responses)

    def assert_llm_fallback_does_not_pollute_state(
        self,
        *,
        session: SessionState,
        action: PlayerAction,
    ) -> None:
        context = build_agent_context(self._case, session, action)
        before = _state_fingerprint(self._case, session)
        intent = OpenAILLMAgent(api_key="").generate(context)
        after = _state_fingerprint(self._case, session)

        assert before == after
        assert intent.proposed_actions == []
        assert intent.memory_refs == []
        assert intent.disclosure_claims == []
        assert context.target_agent_id in intent.speech
        self._assert_text_has_no_private_or_forbidden_values(intent.speech)

    def _assert_initial_state(self, session: SessionState) -> None:
        assert session.case_id == self._spec.case_id
        assert session.narrative.phase == self._case.meta.initial_phase
        assert not session.player_knowledge
        assert not session.discovered_clues

    def _assert_step_response(
        self,
        step: ScenarioStep,
        response: ActionResponse,
        session: SessionState,
    ) -> None:
        assert response.accepted is step.accepted, step.name
        assert response.director_blocked is step.director_blocked, step.name
        assert [event.type for event in response.new_events] == step.expected_events, step.name
        assert session.narrative.phase == step.expected_phase, step.name
        assert _player_world_info_ids(session) == step.expected_player_world_info_ids, step.name
        if step.expected_block is not None:
            self._assert_director_block(step.expected_block, response.new_events)
        else:
            assert not any(
                event.type == EventType.DIRECTOR_BLOCKED for event in response.new_events
            )

    def _assert_step_awareness_delta(
        self,
        *,
        step: ScenarioStep,
        session: SessionState,
        before_event_count: int,
    ) -> None:
        new_awareness_events = [
            event
            for event in session.events[before_event_count:]
            if event.type == EventType.CHARACTER_FACT_AWARENESS_UPDATED
        ]
        observed = {
            (str(event.payload["character_id"]), str(event.payload["world_info_id"]))
            for event in new_awareness_events
        }
        assert observed == set(step.expected_new_awareness), step.name

    def _assert_director_block(
        self,
        expected: ExpectedDirectorBlock,
        events: list[WorldEvent],
    ) -> None:
        block_event = next(event for event in events if event.type == EventType.DIRECTOR_BLOCKED)
        payload = block_event.payload
        assert payload["target_id"] == expected.target_id
        assert payload["blocked_fact_id"] == expected.blocked_fact_id
        assert payload["world_info_id"] == expected.world_info_id
        assert payload["matched_by"] == expected.matched_by
        assert payload["matched_text"] == expected.matched_text
        assert payload["safe_fallback_used"] is expected.safe_fallback_used
        assert payload["detected_directness"] == "direct_claim"
        assert payload["disclosure_claims"] == []

    def _assert_public_outputs_are_sanitized(
        self,
        *,
        response: ActionResponse,
        session: SessionState,
    ) -> None:
        for text in [
            response.model_dump_json(),
            build_state_summary(self._case, session).model_dump_json(),
        ]:
            self._assert_text_has_no_private_or_forbidden_values(text)
            assert '"forbidden_facts":' not in text
            assert '"solution_claims":' not in text
            assert '"inner_context":' not in text

    def _assert_narrative_phase_authority(self, events: list[WorldEvent]) -> None:
        for event in events:
            if event.type == EventType.NARRATIVE_PHASE_CHANGED:
                assert event.actor_id == "rule_trigger_system"
                assert event.payload["phase"] == event.payload["to_phase"]
                assert event.payload["trigger_beat_id"]
            if event.type == EventType.RULE_REJECTED:
                assert event.actor_id == "rule_engine"

    def _assert_player_knowledge_is_world_info_anchored(self, session: SessionState) -> None:
        for knowledge in session.player_knowledge.values():
            assert knowledge.world_info_id in self._world_info_ids
            assert knowledge.knowledge_id == f"player_knowledge.{knowledge.world_info_id}"
            assert knowledge.confidence == 1.0
            assert knowledge.acquisition == "discovered"
            assert knowledge.source_type == "clue"

    def _assert_disclosure_claims_are_auditable(
        self,
        events: list[WorldEvent],
        session: SessionState,
    ) -> None:
        for event in events:
            if event.type not in {EventType.NPC_REPLIED, EventType.DIRECTOR_BLOCKED}:
                continue
            claims = event.payload.get("disclosure_claims", [])
            if not claims:
                continue
            target_id = str(event.actor_id)
            action = PlayerAction(type=ActionType.TALK, target_id=target_id, text="audit context")
            context = build_agent_context(self._case, session, action)
            assert context.inner_context is not None
            strategy_ids = {
                strategy.world_info_id
                for strategy in context.inner_context.fact_disclosure_strategies
            }
            for claim in claims:
                assert claim["world_info_id"] in strategy_ids
                assert claim["mode"] != "full"

    def _assert_context_strategy_consistency(
        self,
        action: PlayerAction,
        session: SessionState,
    ) -> None:
        if action.type not in {"talk", "ask_about", "present_clue"}:
            return
        context = build_agent_context(self._case, session, action)
        contract_input = build_llm_agent_input(context)
        if context.inner_context is None:
            return
        strategy_ids = {
            strategy.world_info_id for strategy in context.inner_context.fact_disclosure_strategies
        }
        constraint_ids = {
            constraint.item_id
            for constraint in contract_input.disclosure_constraints
            if constraint.item_kind == "world_info"
        }
        assert strategy_ids == constraint_ids
        for strategy in context.inner_context.fact_disclosure_strategies:
            assert "full" in {mode.value for mode in strategy.forbidden_modes}
            assert "full" not in {mode.value for mode in strategy.allowed_modes}

    def _assert_final_state(self, session: SessionState) -> None:
        assert session.narrative.phase == self._spec.expected_final_phase
        assert self._spec.expected_final_beats.issubset(session.narrative.completed_beats)
        assert _player_world_info_ids(session) == self._spec.expected_final_player_world_info_ids
        assert session.memory_snapshots
        assert session.character_impressions

    def _assert_replay_equivalence(self, session: SessionState) -> None:
        replayed = replay_events(self._case, session.events)
        assert _state_fingerprint(self._case, replayed) == _state_fingerprint(
            self._case,
            session,
        )
        assert replayed.character_fact_awareness == session.character_fact_awareness
        assert replayed.character_impressions == session.character_impressions
        assert replayed.memory_candidates == session.memory_candidates
        assert replayed.memory_snapshots == session.memory_snapshots
        assert len(replayed.events) == len(session.events)

    def _assert_text_has_no_private_or_forbidden_values(self, text: str) -> None:
        for value in [*self._private_values, *self._forbidden_terms]:
            if not value:
                continue
            assert value not in text


class ScenarioSpecLoadError(ValueError):
    pass


def _read_scenario_yaml(path: Path) -> Mapping[str, object]:
    try:
        return read_scenario_yaml(path)
    except ValueError as exc:
        raise ScenarioSpecLoadError(str(exc)) from exc


def _build_scenario_evaluation_spec(
    raw_scenario: Mapping[str, object],
    path: Path,
) -> ScenarioEvaluationSpec:
    _reject_unknown_fields(raw_scenario, _SCENARIO_FIELDS, f"scenario file {path}")
    _require_fields(
        raw_scenario,
        {
            "case_id",
            "expected_final_phase",
            "expected_final_beats",
            "expected_final_player_world_info_ids",
            "forbidden_public_terms",
            "steps",
        },
        f"scenario file {path}",
    )

    return ScenarioEvaluationSpec(
        case_id=_expect_str(raw_scenario["case_id"], "case_id"),
        expected_final_phase=_expect_str(
            raw_scenario["expected_final_phase"],
            "expected_final_phase",
        ),
        expected_final_beats=_expect_string_set(
            raw_scenario["expected_final_beats"],
            "expected_final_beats",
        ),
        expected_final_player_world_info_ids=_expect_string_set(
            raw_scenario["expected_final_player_world_info_ids"],
            "expected_final_player_world_info_ids",
        ),
        forbidden_public_terms=_expect_string_set(
            raw_scenario["forbidden_public_terms"],
            "forbidden_public_terms",
        ),
        steps=_build_scenario_steps(raw_scenario["steps"]),
    )


def _build_scenario_steps(value: object) -> list[ScenarioStep]:
    raw_steps = _expect_sequence(value, "steps")
    return [
        _build_scenario_step(_expect_mapping(step, f"steps[{index}]"), index)
        for index, step in enumerate(raw_steps)
    ]


def _build_scenario_step(raw_step: Mapping[str, object], index: int) -> ScenarioStep:
    context = f"steps[{index}]"
    _reject_unknown_fields(raw_step, _SCENARIO_STEP_FIELDS, context)
    _require_fields(
        raw_step,
        {
            "name",
            "action",
            "expected_events",
            "expected_phase",
            "expected_player_world_info_ids",
        },
        context,
    )

    return ScenarioStep(
        name=_expect_str(raw_step["name"], f"{context}.name"),
        action=_build_player_action(raw_step["action"], f"{context}.action"),
        expected_events=_build_expected_events(
            raw_step["expected_events"],
            f"{context}.expected_events",
        ),
        expected_phase=_expect_str(raw_step["expected_phase"], f"{context}.expected_phase"),
        expected_player_world_info_ids=_expect_string_set(
            raw_step["expected_player_world_info_ids"],
            f"{context}.expected_player_world_info_ids",
        ),
        accepted=_expect_bool(raw_step.get("accepted", True), f"{context}.accepted"),
        director_blocked=_expect_bool(
            raw_step.get("director_blocked", False),
            f"{context}.director_blocked",
        ),
        expected_new_awareness=_build_expected_new_awareness(
            raw_step.get("expected_new_awareness", []),
            f"{context}.expected_new_awareness",
        ),
        expected_block=_build_expected_block(
            raw_step.get("expected_block"),
            f"{context}.expected_block",
        ),
    )


def _build_player_action(value: object, context: str) -> PlayerAction:
    raw_action = _expect_mapping(value, context)
    try:
        return PlayerAction.model_validate(dict(raw_action))
    except ValidationError as exc:
        raise ScenarioSpecLoadError(f"Invalid PlayerAction at {context}: {exc}") from exc


def _build_expected_events(value: object, context: str) -> list[EventType]:
    raw_events = _expect_sequence(value, context)
    return [
        _build_event_type(raw_event, f"{context}[{index}]")
        for index, raw_event in enumerate(raw_events)
    ]


def _build_event_type(value: object, context: str) -> EventType:
    if isinstance(value, EventType):
        return value
    if not isinstance(value, str):
        raise ScenarioSpecLoadError(f"{context} must be an EventType value string")
    try:
        return EventType(value)
    except ValueError as exc:
        valid_values = ", ".join(event.value for event in EventType)
        raise ScenarioSpecLoadError(
            f"Unknown EventType at {context}: {value!r}. Valid values: {valid_values}"
        ) from exc


def _build_expected_new_awareness(value: object, context: str) -> list[tuple[str, str]]:
    raw_awareness_items = _expect_sequence(value, context)
    return [
        _build_expected_awareness_item(raw_item, f"{context}[{index}]")
        for index, raw_item in enumerate(raw_awareness_items)
    ]


def _build_expected_awareness_item(value: object, context: str) -> tuple[str, str]:
    if isinstance(value, Mapping):
        raw_item = _expect_mapping(value, context)
        _reject_unknown_fields(raw_item, _EXPECTED_AWARENESS_FIELDS, context)
        _require_fields(raw_item, _EXPECTED_AWARENESS_FIELDS, context)
        return (
            _expect_str(raw_item["character_id"], f"{context}.character_id"),
            _expect_str(raw_item["world_info_id"], f"{context}.world_info_id"),
        )

    raw_pair = _expect_sequence(value, context)
    if len(raw_pair) != 2:
        raise ScenarioSpecLoadError(
            f"{context} must contain exactly character_id and world_info_id"
        )
    return (
        _expect_str(raw_pair[0], f"{context}[0]"),
        _expect_str(raw_pair[1], f"{context}[1]"),
    )


def _build_expected_block(value: object, context: str) -> ExpectedDirectorBlock | None:
    if value is None:
        return None

    raw_block = _expect_mapping(value, context)
    _reject_unknown_fields(raw_block, _EXPECTED_DIRECTOR_BLOCK_FIELDS, context)
    _require_fields(
        raw_block,
        {"target_id", "blocked_fact_id", "world_info_id"},
        context,
    )

    return ExpectedDirectorBlock(
        target_id=_expect_str(raw_block["target_id"], f"{context}.target_id"),
        blocked_fact_id=_expect_str(
            raw_block["blocked_fact_id"],
            f"{context}.blocked_fact_id",
        ),
        world_info_id=_expect_str(raw_block["world_info_id"], f"{context}.world_info_id"),
        matched_by=_expect_str(
            raw_block.get("matched_by", "forbidden_term"),
            f"{context}.matched_by",
        ),
        matched_text=_expect_str(
            raw_block.get("matched_text", "[redacted]"),
            f"{context}.matched_text",
        ),
        safe_fallback_used=_expect_bool(
            raw_block.get("safe_fallback_used", True),
            f"{context}.safe_fallback_used",
        ),
    )


def _expect_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ScenarioSpecLoadError(f"{context} must be a mapping")

    for key in value:
        if not isinstance(key, str):
            raise ScenarioSpecLoadError(f"{context} has a non-string key: {key!r}")

    return value


def _expect_sequence(value: object, context: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ScenarioSpecLoadError(f"{context} must be a list")
    return value


def _expect_str(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ScenarioSpecLoadError(f"{context} must be a string")
    return value


def _expect_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ScenarioSpecLoadError(f"{context} must be a boolean")
    return value


def _expect_string_set(value: object, context: str) -> set[str]:
    return {
        _expect_str(item, f"{context}[{index}]")
        for index, item in enumerate(_expect_sequence(value, context))
    }


def _reject_unknown_fields(
    value: Mapping[str, object],
    allowed_fields: frozenset[str],
    context: str,
) -> None:
    unknown_fields = sorted(set(value) - allowed_fields)
    if unknown_fields:
        raise ScenarioSpecLoadError(f"{context} has unknown fields: {unknown_fields}")


def _require_fields(
    value: Mapping[str, object],
    required_fields: set[str] | frozenset[str],
    context: str,
) -> None:
    missing_fields = sorted(required_fields - set(value))
    if missing_fields:
        raise ScenarioSpecLoadError(f"{context} is missing required fields: {missing_fields}")


def _state_fingerprint(case: CasePackage, session: SessionState) -> dict[str, object]:
    summary = build_state_summary(case, session).model_dump(mode="json")
    return {
        "summary": summary,
        "player_knowledge": {
            key: value.model_dump(mode="json")
            for key, value in sorted(session.player_knowledge.items())
        },
        "character_fact_awareness": {
            key: value.model_dump(mode="json")
            for key, value in sorted(session.character_fact_awareness.items())
        },
        "character_impressions": {
            observer_id: {
                target_id: impression.model_dump(mode="json")
                for target_id, impression in sorted(targets.items())
            }
            for observer_id, targets in sorted(session.character_impressions.items())
        },
        "memory_candidates": {
            key: value.model_dump(mode="json")
            for key, value in sorted(session.memory_candidates.items())
        },
        "memory_snapshots": {
            key: _snapshot_fingerprint(value.model_dump(mode="json"))
            for key, value in sorted(session.memory_snapshots.items())
        },
        "events_count": len(session.events),
    }


def _snapshot_fingerprint(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"created_at", "updated_at"}
    }


def _player_world_info_ids(session: SessionState) -> set[str]:
    return {
        knowledge.world_info_id
        for knowledge in session.player_knowledge.values()
        if knowledge.world_info_id is not None
    }


def _private_character_values(case: CasePackage) -> list[str]:
    values: list[str] = []
    for character in case.characters:
        values.extend(goal.summary for goal in character.private.goals)
        values.extend(secret.summary for secret in character.private.secrets)
        values.extend(knowledge.summary for knowledge in character.private.knowledge)
    return values
