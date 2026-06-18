from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from app.cases.linter import lint_production_case

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


def test_mist_clock_manor_authoring_linter_passes_production_case() -> None:
    report = lint_production_case(CASE_DIR)

    assert report.passed is True
    assert report.violations == []


def test_case_linter_cli_outputs_json_and_exit_zero() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.scripts.case_linter",
            "--case",
            "mist_clock_manor",
            "--format",
            "json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert '"passed": true' in result.stdout
    assert '"violation_count": 0' in result.stdout


def test_case_linter_rejects_broken_authoring_invariants(tmp_path: Path) -> None:
    case_dir = _copy_case(tmp_path)

    world_info = _read_yaml_list(case_dir / "world_info.yaml")
    timed_lock = _item_by_id(world_info, "timed_lock_modified")
    timed_lock["claim_graph"]["safe_fragments"] = []
    death_chain = _item_by_id(world_info, "death_chain_shared")
    death_chain["title"] = "共同促成死亡"
    _write_yaml(case_dir / "world_info.yaml", world_info)

    narrative_rules = _read_yaml_mapping(case_dir / "narrative_rules.yaml")
    narrative_rules["beats"][0]["all_discovered"].append("backup_timer")
    _write_yaml(case_dir / "narrative_rules.yaml", narrative_rules)

    scenes = _read_yaml_list(case_dir / "scenes.yaml")
    study_lock = _hotspot_by_id(scenes, "study_lock")
    unlock = study_lock["backtrack_unlocks"][0]
    unlock["conditions"]["prior_inspected_hotspots"] = []
    _write_yaml(case_dir / "scenes.yaml", scenes)

    npc_skills = _read_yaml_list(case_dir / "npc_skills.yaml")
    del _item_by_id(npc_skills, "jiang_lock_boundary")["proposed_action_policy"][
        "max_relationship_delta"
    ]
    _write_yaml(case_dir / "npc_skills.yaml", npc_skills)

    memory_rules = _read_yaml_list(case_dir / "memory_derivation_rules.yaml")
    first_effect = memory_rules[0]["produces"][0]
    first_effect["source_event_ids"] = []
    first_effect["metadata"].pop("authority_source")
    _write_yaml(case_dir / "memory_derivation_rules.yaml", memory_rules)

    standard_path = _read_yaml_mapping(case_dir / "scenarios" / "standard_path.yaml")
    standard_path["expected_final_player_world_info_ids"].append(
        "backup_timer_kept_recorder_power"
    )
    _write_yaml(case_dir / "scenarios" / "standard_path.yaml", standard_path)

    report = lint_production_case(case_dir)
    codes = {violation.code for violation in report.violations}

    assert report.passed is False
    assert "world_info.high_sensitivity.safe_fragment_missing" in codes
    assert "optional_clue.core_beat" in codes
    assert "optional_world_info.standard_path" in codes
    assert "backtrack.first_inspection_unlock" in codes
    assert "npc_skill.relationship_delta_cap_missing" in codes
    assert "memory_rule.source_event_ids_missing" in codes
    assert "memory_rule.authority_missing" in codes
    assert "forbidden_term.public_exact_match" in codes


def _copy_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "mist_clock_manor"
    shutil.copytree(CASE_DIR, case_dir)
    return case_dir


def _read_yaml_list(path: Path) -> list[dict[str, object]]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, list)
    return loaded


def _read_yaml_mapping(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _write_yaml(path: Path, value: object) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _item_by_id(items: list[dict[str, object]], item_id: str) -> dict[str, object]:
    return next(item for item in items if item["id"] == item_id)


def _hotspot_by_id(scenes: list[dict[str, object]], hotspot_id: str) -> dict[str, object]:
    for scene in scenes:
        for hotspot in scene["hotspots"]:
            if hotspot["id"] == hotspot_id:
                return hotspot
    raise AssertionError(f"missing hotspot {hotspot_id}")
