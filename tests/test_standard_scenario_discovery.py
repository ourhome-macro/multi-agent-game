from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import PlayerAction
from app.runtime.service import create_runtime
from app.scenarios.validation import (
    discover_standard_scenarios,
    load_scenario_package,
    validate_scenario_package,
)
from tests.utils.scenario_evaluation import (
    ScenarioEvaluationHarness,
    load_scenario_evaluation_spec,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = PROJECT_ROOT / "cases"


def test_discovers_and_runs_all_standard_scenarios() -> None:
    scenario_paths = discover_standard_scenarios(CASES_ROOT)

    assert scenario_paths
    assert CASES_ROOT / "mist_clock_manor" / "scenarios" / "standard_path.yaml" in scenario_paths

    for scenario_path in scenario_paths:
        scenario_package = load_scenario_package(scenario_path)
        validate_scenario_package(scenario_package)
        case = CaseLoader().load(scenario_package.case_dir)
        spec = load_scenario_evaluation_spec(scenario_path)
        harness = ScenarioEvaluationHarness(case=case, runtime=create_runtime([case]), spec=spec)
        result = harness.run()

        first_character_id = case.characters[0].id
        harness.assert_llm_fallback_does_not_pollute_state(
            session=result.session,
            action=PlayerAction(
                type="talk",
                target_id=first_character_id,
                text="LLM fallback check.",
            ),
        )
