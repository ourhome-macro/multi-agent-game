from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway, load_dotenv
from app.agents.llm_contract import build_llm_agent_input, validate_llm_agent_output
from app.agents.llm_stub import LLMAgentStub
from app.agents.protocol import AgentProtocol
from app.agents.real_llm_agent import OpenAILLMAgent
from app.cases.loader import CaseLoader
from app.director.narrative_director import NarrativeDirector, detect_world_info_mentions
from app.domain.models import (
    ActionType,
    AgentIntent,
    AgentIntentType,
    CasePackage,
    EventType,
    PlayerAction,
    SessionState,
)
from app.rules.engine import RuleEngine
from app.runtime.events import EventRecorder
from app.runtime.service import create_runtime
from app.scenarios.validation import discover_standard_scenarios, read_scenario_yaml
from app.storage.memory import build_state_summary

ShadowBackend = Literal["stub", "real"]
GenerationStatus = Literal["ok", "skipped", "failed"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASE_REPORT_ROOT = PROJECT_ROOT / "doc" / "case"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "doc" / "evaluations" / "llm_shadow"
SHADOW_EVAL_ENV = "LLM_SHADOW_EVAL"
RAW_TRANSCRIPT_ENV = "LLM_SHADOW_WRITE_RAW"
RAW_TRANSCRIPT_DIR = PROJECT_ROOT / ".shadow_eval" / "private_transcripts"


@dataclass(frozen=True)
class ShadowGenerationResult:
    status: GenerationStatus
    intent: AgentIntent
    llm_success: bool
    schema_valid: bool
    fallback_used: bool
    error_type: str | None
    sanitized_error: str | None
    latency_ms: int


@dataclass(frozen=True)
class LLMShadowEvalStep:
    case_id: str
    scenario_path: str
    scenario_id: str
    step_index: int
    step_id: str
    action_type: str
    target_id: str
    current_phase: str
    llm_backend: ShadowBackend
    llm_success: bool
    schema_valid: bool
    director_allowed: bool
    director_blocked: bool
    block_reason: str | None
    rejected_world_info_ids: list[str]
    disclosure_claim_count: int
    missing_disclosure_claim: bool
    speech_touched_world_info: bool
    fallback_used: bool
    state_unchanged: bool
    event_count_before: int
    event_count_after: int
    latency_ms: int
    action: dict[str, Any]
    generated_intent: dict[str, Any]
    disclosure_claims: list[dict[str, Any]]
    skipped: bool = False
    skip_reason: str | None = None
    error_type: str | None = None
    sanitized_error: str | None = None
    safe_fallback_used: bool = False

    def model_dump(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scenario_path": self.scenario_path,
            "scenario_id": self.scenario_id,
            "step_index": self.step_index,
            "step_id": self.step_id,
            "action_type": self.action_type,
            "target_id": self.target_id,
            "current_phase": self.current_phase,
            "llm_backend": self.llm_backend,
            "llm_success": self.llm_success,
            "schema_valid": self.schema_valid,
            "director_allowed": self.director_allowed,
            "director_blocked": self.director_blocked,
            "block_reason": self.block_reason,
            "rejected_world_info_ids": self.rejected_world_info_ids,
            "disclosure_claim_count": self.disclosure_claim_count,
            "missing_disclosure_claim": self.missing_disclosure_claim,
            "speech_touched_world_info": self.speech_touched_world_info,
            "fallback_used": self.fallback_used,
            "state_unchanged": self.state_unchanged,
            "event_count_before": self.event_count_before,
            "event_count_after": self.event_count_after,
            "latency_ms": self.latency_ms,
            "action": self.action,
            "generated_intent": self.generated_intent,
            "disclosure_claims": self.disclosure_claims,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "error_type": self.error_type,
            "sanitized_error": self.sanitized_error,
            "safe_fallback_used": self.safe_fallback_used,
        }


@dataclass(frozen=True)
class LLMShadowEvalReport:
    case_id: str
    scenario_path: str
    scenario_id: str
    generated_at: str
    llm_backend: ShadowBackend
    real_shadow_enabled: bool
    state_unchanged: bool
    steps: list[LLMShadowEvalStep]

    def model_dump(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scenario_path": self.scenario_path,
            "scenario_id": self.scenario_id,
            "generated_at": self.generated_at,
            "llm_backend": self.llm_backend,
            "backend": self.llm_backend,
            "real_shadow_enabled": self.real_shadow_enabled,
            "real_backend_enabled": self.real_shadow_enabled,
            "state_unchanged": self.state_unchanged,
            "summary": summarize_shadow_steps(self.steps),
            "steps": [step.model_dump() for step in self.steps],
        }


def run_standard_path_shadow_eval(
    *,
    case_dir: Path,
    scenario_path: Path | None = None,
    backend: ShadowBackend | None = None,
    agent: AgentProtocol | None = None,
    report_root: Path = DEFAULT_CASE_REPORT_ROOT,
    write_report: bool = True,
    step_index: int | None = None,
) -> LLMShadowEvalReport:
    load_dotenv()
    case = CaseLoader().load(case_dir)
    selected_scenario_path = scenario_path or case_dir / "scenarios" / "standard_path.yaml"
    scenario = read_scenario_yaml(selected_scenario_path)
    selected_backend = backend or shadow_backend_from_env()
    report = run_shadow_eval(
        case=case,
        scenario=scenario,
        scenario_path=selected_scenario_path,
        backend=selected_backend,
        real_shadow_enabled=real_shadow_eval_enabled(),
        agent=agent,
        step_index=step_index,
    )
    if write_report:
        write_shadow_report(report, report_root=report_root)
    return report


def run_all_standard_path_shadow_evals(
    *,
    cases_root: Path = PROJECT_ROOT / "cases",
    backend: ShadowBackend | None = None,
    report_root: Path = DEFAULT_CASE_REPORT_ROOT,
    summary_dir: Path = DEFAULT_SUMMARY_DIR,
) -> list[LLMShadowEvalReport]:
    load_dotenv()
    reports = [
        run_standard_path_shadow_eval(
            case_dir=scenario_path.parents[1],
            scenario_path=scenario_path,
            backend=backend,
            report_root=report_root,
            write_report=True,
        )
        for scenario_path in discover_standard_scenarios(cases_root)
    ]
    write_shadow_summary(reports, summary_dir=summary_dir)
    return reports


def run_shadow_eval(
    *,
    case: CasePackage,
    scenario: Mapping[str, object],
    scenario_path: Path,
    backend: ShadowBackend,
    real_shadow_enabled: bool,
    agent: AgentProtocol | None = None,
    step_index: int | None = None,
) -> LLMShadowEvalReport:
    runtime = create_runtime([case], agent_gateway=AgentGateway(backend="mock"))
    session = runtime.session_store.create(case)
    director = NarrativeDirector()
    steps: list[LLMShadowEvalStep] = []
    scenario_id = scenario_path.stem

    for index, raw_step in enumerate(_expect_steps(scenario), start=1):
        action = PlayerAction.model_validate(raw_step["action"])
        should_shadow = _is_agent_action(action) and (
            step_index is None or index == step_index
        )
        if should_shadow:
            steps.append(
                _evaluate_shadow_step(
                    case=case,
                    session=session,
                    scenario_path=scenario_path,
                    scenario_id=scenario_id,
                    step_index=index,
                    step_id=_step_id(raw_step, index),
                    action=action,
                    backend=backend,
                    real_shadow_enabled=real_shadow_enabled,
                    agent=agent,
                    director=director,
                )
            )
        runtime.action_service.handle(session=session, action=action)

    return LLMShadowEvalReport(
        case_id=case.meta.id,
        scenario_path=_display_path(scenario_path),
        scenario_id=scenario_id,
        generated_at=datetime.now(UTC).isoformat(),
        llm_backend=backend,
        real_shadow_enabled=real_shadow_enabled,
        state_unchanged=all(step.state_unchanged for step in steps),
        steps=steps,
    )


def write_shadow_report(
    report: LLMShadowEvalReport,
    *,
    report_root: Path = DEFAULT_CASE_REPORT_ROOT,
) -> tuple[Path, Path]:
    output_dir = report_root / report.case_id
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "llm_shadow_report.json"
    md_path = output_dir / "llm_shadow_report.md"
    json_path.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_shadow_report_markdown(report), encoding="utf-8")
    return json_path, md_path


def write_shadow_summary(
    reports: list[LLMShadowEvalReport],
    *,
    summary_dir: Path = DEFAULT_SUMMARY_DIR,
) -> tuple[Path, Path]:
    summary_dir.mkdir(parents=True, exist_ok=True)
    payload = build_shadow_summary(reports)
    json_path = summary_dir / "summary.json"
    md_path = summary_dir / "summary.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_shadow_summary_markdown(payload), encoding="utf-8")
    return json_path, md_path


def build_shadow_summary(reports: list[LLMShadowEvalReport]) -> dict[str, Any]:
    all_steps = [step for report in reports for step in report.steps]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(reports),
        "cases": [report.case_id for report in reports],
        **summarize_shadow_steps(all_steps),
        "reports": [
            {
                "case_id": report.case_id,
                "scenario_path": report.scenario_path,
                "llm_backend": report.llm_backend,
                **summarize_shadow_steps(report.steps),
            }
            for report in reports
        ],
    }


def summarize_shadow_steps(steps: Sequence[LLMShadowEvalStep]) -> dict[str, Any]:
    return {
        "total_shadow_calls": len(steps),
        "schema_failure_count": sum(not step.schema_valid for step in steps),
        "director_block_count": sum(step.director_blocked for step in steps),
        "missing_disclosure_claim_count": sum(step.missing_disclosure_claim for step in steps),
        "speech_touched_world_info_count": sum(step.speech_touched_world_info for step in steps),
        "mode_violation_count": sum(_is_mode_violation(step) for step in steps),
        "full_reveal_block_count": sum(_is_full_reveal_block(step) for step in steps),
        "fallback_count": sum(step.fallback_used for step in steps),
        "skipped_count": sum(step.skipped for step in steps),
        "state_unchanged": all(step.state_unchanged for step in steps),
    }


def shadow_backend_from_env() -> ShadowBackend:
    if real_shadow_eval_enabled() and os.getenv("LLM_BACKEND", "").strip().lower() == "real":
        return "real"
    legacy_backend = os.getenv("LLM_SHADOW_EVAL_BACKEND", "").strip().lower()
    if legacy_backend == "real" and real_shadow_eval_enabled():
        return "real"
    return "stub"


def real_shadow_eval_enabled() -> bool:
    return os.getenv(SHADOW_EVAL_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _evaluate_shadow_step(
    *,
    case: CasePackage,
    session: SessionState,
    scenario_path: Path,
    scenario_id: str,
    step_index: int,
    step_id: str,
    action: PlayerAction,
    backend: ShadowBackend,
    real_shadow_enabled: bool,
    agent: AgentProtocol | None,
    director: NarrativeDirector,
) -> LLMShadowEvalStep:
    before = _state_fingerprint(case, session)
    event_count_before = len(session.events)
    shadow_session = session.model_copy(deep=True)
    _prepare_shadow_context_session(case, shadow_session, action)
    context = build_agent_context(case, shadow_session, action).model_copy(deep=True)
    generation = _generate_shadow_intent(
        context=context,
        backend=backend,
        real_shadow_enabled=real_shadow_enabled,
        agent=agent,
    )
    decision = director.validate(case, shadow_session.narrative, generation.intent, context)
    touched_world_info_ids = _touched_world_info_ids(generation.intent.speech, case)
    claim_world_info_ids = {
        claim.world_info_id for claim in generation.intent.disclosure_claims
    }
    after = _state_fingerprint(case, session)
    event_count_after = len(session.events)
    rejected_world_info_ids = sorted(
        {
            item
            for item in [
                decision.world_info_id,
                decision.blocked_fact_id,
                *touched_world_info_ids,
            ]
            if item
        }
    )

    return LLMShadowEvalStep(
        case_id=case.meta.id,
        scenario_path=_display_path(scenario_path),
        scenario_id=scenario_id,
        step_index=step_index,
        step_id=step_id,
        action_type=action.type.value,
        target_id=action.target_id,
        current_phase=session.narrative.phase,
        llm_backend=backend,
        llm_success=generation.llm_success,
        schema_valid=generation.schema_valid,
        director_allowed=decision.allowed,
        director_blocked=not decision.allowed,
        block_reason=_sanitize_reason(decision.reason),
        rejected_world_info_ids=rejected_world_info_ids,
        disclosure_claim_count=len(generation.intent.disclosure_claims),
        missing_disclosure_claim=bool(touched_world_info_ids - claim_world_info_ids),
        speech_touched_world_info=bool(touched_world_info_ids),
        fallback_used=generation.fallback_used or decision.safe_fallback_used,
        state_unchanged=before == after and event_count_before == event_count_after,
        event_count_before=event_count_before,
        event_count_after=event_count_after,
        latency_ms=generation.latency_ms,
        action=_action_summary(action),
        generated_intent=_intent_summary(generation.intent),
        disclosure_claims=[
            _safe_disclosure_claim_summary(claim.model_dump(mode="json"))
            for claim in generation.intent.disclosure_claims
        ],
        skipped=generation.status == "skipped",
        skip_reason=generation.sanitized_error if generation.status == "skipped" else None,
        error_type=generation.error_type,
        sanitized_error=generation.sanitized_error,
        safe_fallback_used=decision.safe_fallback_used,
    )


def _generate_shadow_intent(
    *,
    context: Any,
    backend: ShadowBackend,
    real_shadow_enabled: bool,
    agent: AgentProtocol | None,
) -> ShadowGenerationResult:
    start = perf_counter()
    if agent is not None:
        return _generate_from_agent(agent=agent, context=context, start=start)
    if backend == "stub":
        return _generate_from_agent(agent=LLMAgentStub(), context=context, start=start)
    if not real_shadow_enabled:
        return _skipped_generation(context, start, "shadow_eval_disabled")
    if not os.getenv("OPENAI_API_KEY"):
        return _skipped_generation(context, start, "missing_api_key")
    return _generate_from_real_llm(context=context, start=start)


def _generate_from_agent(
    *,
    agent: AgentProtocol,
    context: Any,
    start: float,
) -> ShadowGenerationResult:
    try:
        intent = agent.generate(context)
        AgentIntent.model_validate(intent.model_dump(mode="json"))
    except Exception as exc:
        return _failed_generation(context, start, exc)
    return ShadowGenerationResult(
        status="ok",
        intent=intent,
        llm_success=True,
        schema_valid=True,
        fallback_used=False,
        error_type=None,
        sanitized_error=None,
        latency_ms=_elapsed_ms(start),
    )


def _generate_from_real_llm(*, context: Any, start: float) -> ShadowGenerationResult:
    agent = OpenAILLMAgent()
    try:
        contract_input = build_llm_agent_input(context)
        response_payload = agent._create_response(contract_input.model_dump(mode="json"))
        output_payload = agent._extract_json_payload(response_payload)
        intent = validate_llm_agent_output(output_payload, contract_input)
    except Exception as exc:
        return _failed_generation(context, start, exc, fallback_used=True)
    return ShadowGenerationResult(
        status="ok",
        intent=intent,
        llm_success=True,
        schema_valid=True,
        fallback_used=False,
        error_type=None,
        sanitized_error=None,
        latency_ms=_elapsed_ms(start),
    )


def _skipped_generation(context: Any, start: float, reason: str) -> ShadowGenerationResult:
    return ShadowGenerationResult(
        status="skipped",
        intent=_safe_fallback_intent(context),
        llm_success=False,
        schema_valid=False,
        fallback_used=True,
        error_type=reason,
        sanitized_error=reason,
        latency_ms=_elapsed_ms(start),
    )


def _failed_generation(
    context: Any,
    start: float,
    exc: Exception,
    *,
    fallback_used: bool = True,
) -> ShadowGenerationResult:
    return ShadowGenerationResult(
        status="failed",
        intent=_safe_fallback_intent(context),
        llm_success=False,
        schema_valid=False,
        fallback_used=fallback_used,
        error_type=type(exc).__name__,
        sanitized_error=_sanitize_error(exc),
        latency_ms=_elapsed_ms(start),
    )


def _safe_fallback_intent(context: Any) -> AgentIntent:
    target_agent_id = getattr(context, "target_agent_id", "agent")
    return AgentIntent(
        speech=f"{target_agent_id} cannot answer through the LLM backend.",
        intent=AgentIntentType.REFUSE,
        emotional_shift={},
        proposed_actions=[],
        memory_refs=[],
        disclosure_claims=[],
    )


def render_shadow_report_markdown(report: LLMShadowEvalReport) -> str:
    summary = summarize_shadow_steps(report.steps)
    lines = [
        f"# LLM Shadow Eval Report: {report.case_id}",
        "",
        f"- Scenario: `{report.scenario_path}`",
        f"- Backend: `{report.llm_backend}`",
        f"- Real shadow enabled: `{str(report.real_shadow_enabled).lower()}`",
        f"- State unchanged: `{str(report.state_unchanged).lower()}`",
        "",
        "## Summary",
        "",
        *_summary_lines(summary),
        "",
        "## Steps",
        "",
    ]
    for step in report.steps:
        lines.extend(
            [
                f"### Step {step.step_index}: {step.step_id}",
                "",
                f"- Action: `{step.action_type}` -> `{step.target_id}`",
                f"- Phase: `{step.current_phase}`",
                f"- LLM success: `{str(step.llm_success).lower()}`",
                f"- Schema valid: `{str(step.schema_valid).lower()}`",
                f"- Director blocked: `{str(step.director_blocked).lower()}`",
                f"- Block reason: `{step.block_reason or 'none'}`",
                f"- Disclosure claims: `{step.disclosure_claim_count}`",
                f"- Speech touched WorldInfo: `{str(step.speech_touched_world_info).lower()}`",
                f"- Missing disclosure claim: `{str(step.missing_disclosure_claim).lower()}`",
                f"- Fallback used: `{str(step.fallback_used).lower()}`",
                f"- State unchanged: `{str(step.state_unchanged).lower()}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_shadow_summary_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# LLM Shadow Eval Summary",
        "",
        f"- Case count: `{payload['case_count']}`",
        "",
        "## Totals",
        "",
        *_summary_lines(payload),
        "",
        "## Cases",
        "",
    ]
    for report in payload["reports"]:
        lines.append(
            f"- `{report['case_id']}`: calls=`{report['total_shadow_calls']}`, "
            f"blocks=`{report['director_block_count']}`, "
            f"schema_failures=`{report['schema_failure_count']}`, "
            f"state_unchanged=`{str(report['state_unchanged']).lower()}`"
        )
    return "\n".join(lines).rstrip() + "\n"


def _summary_lines(summary: Mapping[str, Any]) -> list[str]:
    keys = [
        "total_shadow_calls",
        "schema_failure_count",
        "director_block_count",
        "missing_disclosure_claim_count",
        "speech_touched_world_info_count",
        "mode_violation_count",
        "full_reveal_block_count",
        "fallback_count",
        "skipped_count",
        "state_unchanged",
    ]
    return [f"- {key}: `{str(summary[key]).lower()}`" for key in keys if key in summary]


def _intent_summary(intent: AgentIntent) -> dict[str, Any]:
    return {
        "intent": intent.intent.value,
        "speech_summary": "[redacted]",
        "speech_redacted": True,
        "speech_length": len(intent.speech),
        "proposed_action_count": len(intent.proposed_actions),
        "proposed_action_types": [
            action.type.value for action in intent.proposed_actions
        ],
        "memory_ref_count": len(intent.memory_refs),
        "disclosure_claim_count": len(intent.disclosure_claims),
    }


def _action_summary(action: PlayerAction) -> dict[str, Any]:
    return {
        "type": action.type.value,
        "target_id": action.target_id,
        "clue_id": action.clue_id,
        "claim_id": action.claim_id,
        "evidence_clue_ids": list(action.evidence_clue_ids),
        "subject_type": action.subject_type.value if action.subject_type else None,
        "subject_id": action.subject_id,
        "force_forbidden": action.force_forbidden,
        "text_redacted": action.text is not None,
        "text_length": len(action.text) if action.text is not None else 0,
    }


def _safe_disclosure_claim_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "world_info_id": payload.get("world_info_id"),
        "mode": payload.get("mode"),
        "tactic": payload.get("tactic"),
        "source_ref_count": len(payload.get("source_refs", [])),
        "claim_ref_count": len(payload.get("claim_refs", [])),
    }


def _prepare_shadow_context_session(
    case: CasePackage,
    session: SessionState,
    action: PlayerAction,
) -> None:
    recorder = EventRecorder()
    if action.type == ActionType.TALK:
        recorder.append(
            session,
            actor_id="player",
            event_type=EventType.PLAYER_TALKED,
            payload={"target_id": action.target_id, "text": action.text},
        )
        return
    if action.type == ActionType.ASK_ABOUT:
        RuleEngine(recorder).apply_ask_about(case=case, session=session, action=action)
        return
    if action.type == ActionType.PRESENT_CLUE:
        RuleEngine(recorder).apply_present_clue(case=case, session=session, action=action)


def _is_agent_action(action: PlayerAction) -> bool:
    return action.type in {ActionType.TALK, ActionType.ASK_ABOUT, ActionType.PRESENT_CLUE}


def _state_fingerprint(case: CasePackage, session: SessionState) -> dict[str, Any]:
    return {
        "summary": build_state_summary(case, session).model_dump(mode="json"),
        "narrative": session.narrative.model_dump(mode="json"),
        "relationships": _dump_model_map(session.relationships),
        "relationship_thresholds_crossed": sorted(session.relationship_thresholds_crossed),
        "discovered_clues": sorted(session.discovered_clues),
        "player_knowledge": _dump_model_map(session.player_knowledge),
        "character_fact_awareness": _dump_model_map(session.character_fact_awareness),
        "memory_candidates": _dump_model_map(session.memory_candidates),
        "memory_snapshots": _snapshot_fingerprint_map(session.memory_snapshots),
        "character_impressions": _dump_nested_model_map(session.character_impressions),
        "event_log": [event.model_dump(mode="json") for event in session.events],
    }


def _dump_model_map(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _dump_value(value)
        for key, value in sorted(mapping.items(), key=lambda item: item[0])
    }


def _dump_nested_model_map(mapping: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        outer_key: _dump_model_map(inner_mapping)
        for outer_key, inner_mapping in sorted(mapping.items(), key=lambda item: item[0])
    }


def _snapshot_fingerprint_map(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: {
            field: item
            for field, item in _dump_value(value).items()
            if field not in {"created_at", "updated_at"}
        }
        for key, value in sorted(mapping.items(), key=lambda item: item[0])
    }


def _dump_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): _dump_value(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, list):
        return [_dump_value(item) for item in value]
    return value


def _touched_world_info_ids(speech: str, case: CasePackage) -> set[str]:
    return {mention.world_info_id for mention in detect_world_info_mentions(speech, case)}


def _is_mode_violation(step: LLMShadowEvalStep) -> bool:
    reason = (step.block_reason or "").casefold()
    return "is not allowed" in reason or "is forbidden" in reason


def _is_full_reveal_block(step: LLMShadowEvalStep) -> bool:
    reason = (step.block_reason or "").casefold()
    return "attempted full reveal" in reason


def _sanitize_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    return reason.replace('"', "'")


def _sanitize_error(exc: Exception) -> str:
    message = str(exc).splitlines()[0]
    if len(message) > 160:
        return f"{message[:157]}..."
    return message


def _elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


def _expect_steps(scenario: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw_steps = scenario.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("Scenario must contain a steps list")
    steps: list[Mapping[str, object]] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, Mapping):
            raise ValueError(f"steps[{index}] must be a mapping")
        if "action" not in raw_step:
            raise ValueError(f"steps[{index}] is missing action")
        steps.append(raw_step)
    return steps


def _step_id(raw_step: Mapping[str, object], index: int) -> str:
    name = raw_step.get("name")
    if isinstance(name, str) and name:
        return name
    return f"step_{index:03d}"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())
