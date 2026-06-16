from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import EventType, PlayerAction
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime
from app.scenarios.validation import discover_scenarios
from tests.utils.scenario_evaluation import (
    ScenarioEvaluationHarness,
    load_scenario_evaluation_spec,
    load_standard_scenario_evaluation_spec,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "mist_clock_manor"
CASE_DIR = PROJECT_ROOT / "cases" / CASE_ID


def test_mist_clock_manor_standard_scenario_level_evaluation() -> None:
    case = CaseLoader().load(CASE_DIR)
    spec = load_standard_scenario_evaluation_spec(CASE_ID, cases_root=PROJECT_ROOT / "cases")
    harness = ScenarioEvaluationHarness(case=case, runtime=create_runtime([case]), spec=spec)
    result = harness.run()

    harness.assert_llm_fallback_does_not_pollute_state(
        session=result.session,
        action=PlayerAction(type="talk", target_id="jiang_yanhui", text="LLM fallback check."),
    )


def test_mist_clock_manor_deviation_scenarios_are_discovered_and_run() -> None:
    scenario_paths = discover_scenarios(CASE_DIR, pattern="deviation_*.yaml")

    assert {path.name for path in scenario_paths} == {
        "deviation_ask_wrong_npc_about_wine.yaml",
        "deviation_backtrack_study_lock_after_tape.yaml",
        "deviation_direct_spoiler_probe.yaml",
        "deviation_out_of_order_medicine_probe.yaml",
        "deviation_repeat_present_same_clue.yaml",
        "deviation_wrong_accusation_before_reconstruction.yaml",
    }

    for scenario_path in scenario_paths:
        case = CaseLoader().load(CASE_DIR)
        spec = load_scenario_evaluation_spec(scenario_path)
        harness = ScenarioEvaluationHarness(case=case, runtime=create_runtime([case]), spec=spec)
        result = harness.run()

        harness.assert_llm_fallback_does_not_pollute_state(
            session=result.session,
            action=PlayerAction(
                type="talk",
                target_id="jiang_yanhui",
                text="LLM fallback check.",
            ),
        )


def test_mist_clock_manor_backtrack_lock_clue_is_rule_event_auditable() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    for target_id in ("wine_table", "study_lock", "tape_recorder"):
        runtime.action_service.handle(
            session=session,
            action=PlayerAction(type="inspect", target_id=target_id),
        )

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="study_lock"),
    )

    backtrack_event = next(
        event
        for event in response.new_events
        if event.type == EventType.CLUE_DISCOVERED
        and event.payload["clue_id"] == "lock_test_scrap"
    )
    assert backtrack_event.actor_id == "system"
    assert backtrack_event.payload == {
        "clue_id": "lock_test_scrap",
        "source_hotspot_id": "study_lock",
        "source_backtrack_unlock_id": "study_lock_after_tape_review",
    }
    assert "lock_test_scrap" in session.discovered_clues
    assert "player_knowledge.lock_delay_tested" in session.player_knowledge

    replayed = replay_events(case, session.events)
    assert replayed.discovered_clues == session.discovered_clues
    assert replayed.player_knowledge == session.player_knowledge
