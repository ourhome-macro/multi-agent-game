from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.protocol import AgentProtocol
from app.cases.loader import CaseLoader
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    DisclosureClaim,
    DisclosureMode,
    PlayerAction,
    RhetoricTactic,
)
from app.evaluations.llm_shadow_eval import (
    run_all_standard_path_shadow_evals,
    run_shadow_eval,
    run_standard_path_shadow_eval,
    write_shadow_report,
)
from app.runtime.service import create_runtime
from tests.utils.scenario_evaluation import load_scenario_evaluation_spec

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
MIST_CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


def test_shadow_eval_does_not_write_world_event_or_pollute_session_state() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    before = session.model_dump(mode="json")
    report = run_shadow_eval(
        case=case,
        scenario=_single_step_scenario(
            PlayerAction(type="talk", target_id="butler", text="Shadow check.")
        ),
        scenario_path=FAKE_CASE_001_DIR / "scenarios" / "shadow_unit.yaml",
        backend="stub",
        real_shadow_enabled=False,
        agent=_StaticAgent(
            AgentIntent(
                speech="I can offer a careful hint, but no state should change.",
                intent=AgentIntentType.ANSWER,
                disclosure_claims=[_claim("desk_forced_open", DisclosureMode.HINT)],
            )
        ),
    )

    step = report.steps[0]
    assert step.state_unchanged is True
    assert step.event_count_before == step.event_count_after == 1
    assert session.model_dump(mode="json") == before


def test_shadow_eval_only_processes_dialogue_actions_and_skips_inspect_accuse() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    scenario = {
        "case_id": "fake_case_001",
        "steps": [
            {
                "name": "inspect",
                "action": PlayerAction(
                    type="inspect",
                    target_id="desk",
                ).model_dump(mode="json"),
            },
            {
                "name": "talk",
                "action": PlayerAction(
                    type="talk",
                    target_id="butler",
                    text="Talk.",
                ).model_dump(mode="json"),
            },
            {
                "name": "accuse",
                "action": PlayerAction(
                    type="accuse",
                    target_id="butler",
                    claim_id="butler_moved_key",
                    evidence_clue_ids=["scratched_drawer"],
                    text="Accuse.",
                ).model_dump(mode="json"),
            },
        ],
    }

    report = run_shadow_eval(
        case=case,
        scenario=scenario,
        scenario_path=FAKE_CASE_001_DIR / "scenarios" / "shadow_unit.yaml",
        backend="stub",
        real_shadow_enabled=False,
        agent=_StaticAgent(AgentIntent(speech="Safe.", intent=AgentIntentType.ANSWER)),
    )

    assert [step.step_index for step in report.steps] == [2]
    assert report.steps[0].action_type == "talk"


def test_shadow_eval_allows_compliant_hint() -> None:
    report = _run_case_001_shadow_step(
        PlayerAction(type="talk", target_id="butler", text="Where were you?"),
        AgentIntent(
            speech="Some opened places matter, but I will not draw the whole shape.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim("desk_forced_open", DisclosureMode.HINT)],
        ),
    )

    step = report.steps[0]
    assert step.director_allowed is True
    assert step.director_blocked is False
    assert step.block_reason is None


def test_shadow_eval_blocks_unauthorized_disclosure_claim() -> None:
    report = _run_case_001_shadow_step(
        PlayerAction(type="talk", target_id="butler", text="Tell me everything."),
        AgentIntent(
            speech="I should not say this outright.",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[_claim("desk_forced_open", DisclosureMode.FULL)],
        ),
    )

    step = report.steps[0]
    assert step.director_blocked is True
    assert step.block_reason is not None
    assert "attempted full reveal" in step.block_reason
    assert step.fallback_used is True


def test_shadow_eval_blocks_speech_touching_world_info_without_claim() -> None:
    report = _run_case_001_shadow_step(
        PlayerAction(type="talk", target_id="butler", text="What do you know?"),
        AgentIntent(
            speech="文件不是原来的",
            intent=AgentIntentType.ANSWER,
            disclosure_claims=[],
        ),
    )

    step = report.steps[0]
    assert step.director_blocked is True
    assert step.speech_touched_world_info is True
    assert step.missing_disclosure_claim is True
    assert "without a disclosure claim" in str(step.block_reason)


def test_shadow_eval_records_schema_invalid_without_state_pollution() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    report = run_shadow_eval(
        case=case,
        scenario=_single_step_scenario(
            PlayerAction(type="talk", target_id="butler", text="Bad schema.")
        ),
        scenario_path=FAKE_CASE_001_DIR / "scenarios" / "shadow_unit.yaml",
        backend="stub",
        real_shadow_enabled=False,
        agent=_InvalidAgent(),
    )

    step = report.steps[0]
    assert step.llm_success is False
    assert step.schema_valid is False
    assert step.fallback_used is True
    assert step.error_type is not None
    assert step.state_unchanged is True
    assert step.event_count_before == step.event_count_after


def test_real_shadow_eval_without_api_key_is_safely_skipped(monkeypatch: Any) -> None:
    monkeypatch.setenv("LLM_SHADOW_EVAL", "1")
    monkeypatch.setenv("LLM_BACKEND", "real")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    case = CaseLoader().load(FAKE_CASE_001_DIR)

    report = run_shadow_eval(
        case=case,
        scenario=_single_step_scenario(
            PlayerAction(type="talk", target_id="butler", text="No key.")
        ),
        scenario_path=FAKE_CASE_001_DIR / "scenarios" / "shadow_unit.yaml",
        backend="real",
        real_shadow_enabled=True,
    )

    step = report.steps[0]
    assert step.skipped is True
    assert step.skip_reason == "missing_api_key"
    assert step.llm_success is False
    assert step.state_unchanged is True


def test_step_filter_runs_only_selected_dialogue_step(tmp_path: Path) -> None:
    report = run_standard_path_shadow_eval(
        case_dir=MIST_CASE_DIR,
        report_root=tmp_path,
        step_index=6,
    )

    assert [step.step_index for step in report.steps] == [6]
    assert report.steps[0].action_type == "talk"


def test_all_mode_discovers_standard_paths_and_writes_summary(tmp_path: Path) -> None:
    reports = run_all_standard_path_shadow_evals(
        cases_root=PROJECT_ROOT / "cases",
        report_root=tmp_path / "case",
        summary_dir=tmp_path / "summary",
    )
    summary_payload = json.loads(
        (tmp_path / "summary" / "summary.json").read_text(encoding="utf-8")
    )

    assert {report.case_id for report in reports} == {"mist_clock_manor"}
    assert (tmp_path / "summary" / "summary.md").exists()
    assert summary_payload["case_count"] == 1
    assert summary_payload["total_shadow_calls"] == len(reports[0].steps)


def test_report_generation_writes_json_md_and_excludes_sensitive_raw_text(
    tmp_path: Path,
) -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    report = _run_case_001_shadow_step(
        PlayerAction(type="talk", target_id="butler", text="Report check."),
        AgentIntent(
            speech="I will keep this cautious.",
            intent=AgentIntentType.REFUSE,
        ),
    )

    json_path, md_path = write_shadow_report(report, report_root=tmp_path)
    serialized = json_path.read_text(encoding="utf-8") + md_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert json_path == tmp_path / "fake_case_001" / "llm_shadow_report.json"
    assert md_path == tmp_path / "fake_case_001" / "llm_shadow_report.md"
    assert payload["summary"]["total_shadow_calls"] == 1
    assert "text" not in payload["steps"][0]["action"]
    assert payload["steps"][0]["action"]["text_redacted"] is True
    assert "I will keep this cautious" not in serialized
    assert "Report check" not in serialized
    assert "solution_claims" not in serialized
    for private_value in _private_character_values(case):
        assert private_value not in serialized
    for fact in case.forbidden_facts:
        assert fact.text not in serialized
        for blocked_term in fact.blocked_terms:
            assert blocked_term not in serialized


def test_mist_clock_manor_standard_path_can_run_shadow_eval(tmp_path: Path) -> None:
    report = run_standard_path_shadow_eval(
        case_dir=MIST_CASE_DIR,
        report_root=tmp_path,
    )
    spec = load_scenario_evaluation_spec(MIST_CASE_DIR / "scenarios" / "standard_path.yaml")
    expected_agent_step_count = sum(
        step.action.type in {"talk", "ask_about", "present_clue"} for step in spec.steps
    )

    assert report.case_id == "mist_clock_manor"
    assert report.scenario_id == "standard_path"
    assert report.llm_backend == "stub"
    assert report.real_shadow_enabled is False
    assert report.state_unchanged is True
    assert len(report.steps) == expected_agent_step_count
    assert (tmp_path / "mist_clock_manor" / "llm_shadow_report.json").exists()
    assert (tmp_path / "mist_clock_manor" / "llm_shadow_report.md").exists()


class _StaticAgent(AgentProtocol):
    def __init__(self, intent: AgentIntent) -> None:
        self._intent = intent

    def generate(self, context: AgentContext) -> AgentIntent:
        _ = context
        return self._intent


class _InvalidAgent:
    def generate(self, context: AgentContext) -> object:
        _ = context
        return {"speech": "invalid"}


def _run_case_001_shadow_step(
    action: PlayerAction,
    intent: AgentIntent,
):
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    return run_shadow_eval(
        case=case,
        scenario=_single_step_scenario(action),
        scenario_path=FAKE_CASE_001_DIR / "scenarios" / "shadow_unit.yaml",
        backend="stub",
        real_shadow_enabled=False,
        agent=_StaticAgent(intent),
    )


def _single_step_scenario(action: PlayerAction) -> dict[str, object]:
    return {
        "case_id": "fake_case_001",
        "steps": [
            {
                "name": "shadow step",
                "action": action.model_dump(mode="json"),
            }
        ],
    }


def _claim(world_info_id: str, mode: DisclosureMode) -> DisclosureClaim:
    return DisclosureClaim(
        world_info_id=world_info_id,
        mode=mode,
        tactic=RhetoricTactic.SHIFT_FOCUS,
    )


def _private_character_values(case: object) -> list[str]:
    values: list[str] = []
    for character in case.characters:
        values.extend(goal.summary for goal in character.private.goals)
        values.extend(secret.summary for secret in character.private.secrets)
        values.extend(knowledge.summary for knowledge in character.private.knowledge)
    return values
