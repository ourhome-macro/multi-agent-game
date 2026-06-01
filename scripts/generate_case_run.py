from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.scenarios.validation import discover_standard_scenarios  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.all:
        for scenario_path in discover_standard_scenarios(_resolve_cli_path(args.cases_root)):
            case_dir = scenario_path.parents[1]
            output_dir = _resolve_output_dir(case_id=case_dir.name, output_dir=args.output_dir)
            if args.output_dir is not None:
                output_dir = output_dir / case_dir.name
            _write_case_run(case_dir=case_dir, scenario_path=scenario_path, output_dir=output_dir)
        return

    case_id = args.case_id
    case_dir = _resolve_case_dir(case_id=case_id, case_dir=args.case_dir)
    scenario_path = _resolve_scenario_path(
        case_id=case_id,
        case_dir=case_dir,
        scenario=args.scenario,
    )
    output_dir = _resolve_output_dir(case_id=case_id, output_dir=args.output_dir)
    _write_case_run(case_dir=case_dir, scenario_path=scenario_path, output_dir=output_dir)


def _write_case_run(*, case_dir: Path, scenario_path: Path, output_dir: Path) -> None:
    run_payload, markdown = generate_case_run(
        case_dir=case_dir,
        scenario_path=scenario_path,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "standard_run.json"
    md_path = output_dir / "case_reconstruction.md"
    json_path.write_text(
        json.dumps(run_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(markdown, encoding="utf-8")

    _validate_outputs(
        json_path=json_path,
        md_path=md_path,
        case_id=str(run_payload["case_id"]),
    )
    print(json_path)
    print(md_path)
    print(json.dumps(run_payload["replay_check"], ensure_ascii=False, indent=2))


def generate_case_run(*, case_dir: Path, scenario_path: Path) -> tuple[dict[str, Any], str]:
    from app.cases.loader import CaseLoader
    from app.domain.models import EventType
    from app.runtime.replay import replay_events
    from app.runtime.service import create_runtime
    from app.storage.memory import build_state_summary
    from tests.utils.scenario_evaluation import load_scenario_evaluation_spec

    case = CaseLoader().load(case_dir)
    scenario = _read_scenario_yaml(scenario_path)
    spec = load_scenario_evaluation_spec(scenario_path)
    if spec.case_id != case.meta.id:
        raise ValueError(
            f"Scenario case_id {spec.case_id!r} does not match case {case.meta.id!r}"
        )

    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    step_records: list[dict[str, Any]] = []
    raw_steps = _expect_sequence(scenario["steps"], "steps")

    for index, (step, raw_step) in enumerate(zip(spec.steps, raw_steps, strict=True), start=1):
        raw_step_mapping = _expect_mapping(raw_step, f"steps[{index - 1}]")
        label = _step_label(raw_step_mapping, step.name)
        before_event_count = len(session.events)
        response = runtime.action_service.handle(session=session, action=step.action)
        new_events = session.events[before_event_count:]
        step_records.append(
            {
                "step": index,
                "name": step.name,
                "label": label,
                "action": step.action.model_dump(mode="json"),
                "accepted": response.accepted,
                "expected_accepted": step.accepted,
                "director_blocked": response.director_blocked,
                "expected_director_blocked": step.director_blocked,
                "phase_after": session.narrative.phase,
                "expected_phase": step.expected_phase,
                "speech": response.speech,
                "director_reason": response.director_reason,
                "new_event_types": [event.type.value for event in new_events],
                "expected_event_types": [event.value for event in step.expected_events],
                "new_awareness": _new_awareness_pairs(new_events, EventType),
                "expected_new_awareness": [
                    {"character_id": character_id, "world_info_id": world_info_id}
                    for character_id, world_info_id in step.expected_new_awareness
                ],
                "new_director_blocks": _director_blocks(new_events, EventType),
                "new_events": [event.model_dump(mode="json") for event in new_events],
                "known_world_info_after": sorted(_player_world_info_ids(session)),
                "expected_player_world_info_after": sorted(
                    step.expected_player_world_info_ids
                ),
                "discovered_clues_after": sorted(session.discovered_clues),
            }
        )

    replayed = replay_events(case, session.events)
    state_summary = build_state_summary(case, session)
    replay_summary = build_state_summary(case, replayed)
    replay_check = _build_replay_check(
        session=session,
        replayed=replayed,
        state_summary=state_summary,
        replay_summary=replay_summary,
    )

    run_payload: dict[str, Any] = {
        "case_id": case.meta.id,
        "case_title": case.meta.title,
        "generated_at": datetime.now(UTC).isoformat(),
        "scenario_path": _display_path(scenario_path),
        "case_dir": _display_path(case_dir),
        "session_id": session.id,
        "standard_path": step_records,
        "final_state_summary": state_summary.model_dump(mode="json"),
        "final_player_knowledge": _dump_model_map(session.player_knowledge),
        "final_character_fact_awareness": _dump_model_map(
            session.character_fact_awareness
        ),
        "final_character_impressions": _dump_nested_model_map(
            session.character_impressions
        ),
        "final_memory_candidates": _dump_model_map(session.memory_candidates),
        "final_memory_snapshots": _dump_model_map(session.memory_snapshots),
        "completed_beats": sorted(session.narrative.completed_beats),
        "expected_completed_beats": sorted(spec.expected_final_beats),
        "discovered_clues": sorted(session.discovered_clues),
        "event_log": [event.model_dump(mode="json") for event in session.events],
        "replay_check": replay_check,
    }
    markdown = _build_markdown(
        case=case,
        session=session,
        step_records=step_records,
        run_payload=run_payload,
        scenario=scenario,
    )
    return run_payload, markdown


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a case standard_path scenario and write JSON/Markdown artifacts."
    )
    parser.add_argument("--case-id", default="mist_clock_manor")
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--case-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--cases-root",
        type=Path,
        default=PROJECT / "cases",
        help="Root used by --all discovery. Defaults to project cases directory.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Discover and generate artifacts for every standard_path.yaml under cases root.",
    )
    return parser.parse_args(argv)


def _resolve_case_dir(*, case_id: str, case_dir: Path | None) -> Path:
    if case_dir is not None:
        return _resolve_cli_path(case_dir)
    return PROJECT / "cases" / case_id


def _resolve_scenario_path(*, case_id: str, case_dir: Path, scenario: Path | None) -> Path:
    if scenario is not None:
        return _resolve_cli_path(scenario)
    return case_dir / "scenarios" / "standard_path.yaml"


def _resolve_output_dir(*, case_id: str, output_dir: Path | None) -> Path:
    if output_dir is not None:
        return _resolve_cli_path(output_dir)
    return PROJECT / "doc" / "case" / case_id


def _resolve_cli_path(path: Path) -> Path:
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def _read_scenario_yaml(path: Path) -> Mapping[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Scenario YAML does not exist: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"Scenario YAML root must be a mapping: {path}")
    return cast(Mapping[str, object], loaded)


def _step_label(raw_step: Mapping[str, object], fallback: str) -> str:
    raw_label = raw_step.get("label")
    return raw_label if isinstance(raw_label, str) and raw_label else fallback


def _new_awareness_pairs(new_events: list[Any], event_type: Any) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for event in new_events:
        if event.type != event_type.CHARACTER_FACT_AWARENESS_UPDATED:
            continue
        pairs.append(
            {
                "character_id": str(event.payload.get("character_id", "")),
                "world_info_id": str(event.payload.get("world_info_id", "")),
            }
        )
    return pairs


def _director_blocks(new_events: list[Any], event_type: Any) -> list[dict[str, Any]]:
    return [
        event.payload
        for event in new_events
        if event.type == event_type.DIRECTOR_BLOCKED
    ]


def _player_world_info_ids(session: Any) -> set[str]:
    return {
        knowledge.world_info_id
        for knowledge in session.player_knowledge.values()
        if knowledge.world_info_id is not None
    }


def _build_replay_check(
    *,
    session: Any,
    replayed: Any,
    state_summary: Any,
    replay_summary: Any,
) -> dict[str, Any]:
    replay_check = {
        "event_count": len(session.events),
        "replayed_event_count": len(replayed.events),
        "state_summary_equal": state_summary.model_dump(mode="json")
        == replay_summary.model_dump(mode="json"),
        "player_knowledge_equal": _dump_model_map(session.player_knowledge)
        == _dump_model_map(replayed.player_knowledge),
        "character_fact_awareness_equal": _dump_model_map(
            session.character_fact_awareness
        )
        == _dump_model_map(replayed.character_fact_awareness),
        "character_impressions_equal": _dump_nested_model_map(
            session.character_impressions
        )
        == _dump_nested_model_map(replayed.character_impressions),
        "memory_candidates_equal": _dump_model_map(session.memory_candidates)
        == _dump_model_map(replayed.memory_candidates),
        "memory_snapshots_equal": _snapshot_fingerprint_map(session.memory_snapshots)
        == _snapshot_fingerprint_map(replayed.memory_snapshots),
    }
    replay_check["all_equal"] = all(
        value for value in replay_check.values() if isinstance(value, bool)
    )
    return replay_check


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


def _dump_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): _dump_value(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_dump_value(item) for item in value]
    if isinstance(value, set):
        return sorted(value)
    return value


def _snapshot_fingerprint_map(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _snapshot_fingerprint(value)
        for key, value in sorted(mapping.items(), key=lambda item: item[0])
    }


def _snapshot_fingerprint(value: Any) -> dict[str, Any]:
    payload = _dump_value(value)
    if not isinstance(payload, dict):
        raise ValueError("Memory snapshot fingerprint expects mapping payload")
    return {
        key: item
        for key, item in payload.items()
        if key not in {"created_at", "updated_at"}
    }


def _build_markdown(
    *,
    case: Any,
    session: Any,
    step_records: list[dict[str, Any]],
    run_payload: dict[str, Any],
    scenario: Mapping[str, object],
) -> str:
    reconstruction = scenario.get("reconstruction")
    if reconstruction is None:
        reconstruction = {}
    if not isinstance(reconstruction, Mapping):
        raise ValueError("Scenario reconstruction must be a mapping when provided")

    world_info_by_id = {item.id: item for item in case.world_info}
    clue_by_id = {item.id: item for item in case.clues}
    character_by_id = {item.id: item for item in case.characters}

    overview = _text_block(
        reconstruction.get("overview"),
        case.meta.description or "未提供案件概览。",
    )
    runtime_note = _text_block(
        reconstruction.get("runtime_note"),
        "运行时通过结构化 PlayerAction、Rule Engine、Narrative Director 和事件日志推进案件。",
    )
    director_note = _text_block(
        reconstruction.get("director_note"),
        "本次标准路径未提供额外 Director 说明。",
    )
    facts = _numbered_lines(
        reconstruction.get("facts")
        or _fallback_fact_reconstruction(session, world_info_by_id)
    )

    return f"""# 《{case.meta.title}》标准运行复盘

> 本文档由 `scripts/generate_case_run.py` 执行 `{case.meta.id}` 标准路径后生成。
> 对应机器可读日志见 `standard_run.json`。

## 案件概览

{overview}

{runtime_note}

## 标准调查路径

{chr(10).join(_step_lines(step_records))}

## 案件事实重建

{facts}

## 玩家最终已知

{chr(10).join(_player_knowledge_lines(session, world_info_by_id, clue_by_id))}

## 角色认知变化

{chr(10).join(_awareness_lines(session, world_info_by_id, character_by_id))}

## Director 拦截结果

{director_note}

{chr(10).join(_director_lines(step_records))}

## Replay 校验

{chr(10).join(_replay_lines(run_payload["replay_check"]))}

## 最终状态

- 最终 phase：`{session.narrative.phase}`
- 完成 beats：{_inline_code_list(sorted(session.narrative.completed_beats))}
- 已发现线索：{_inline_code_list(sorted(session.discovered_clues))}
- 事件总数：{len(session.events)}

## 产物说明

- `standard_run.json`：标准路径动作、每步新增事件、最终状态、完整事件日志和 replay 校验结果。
- 本文档：面向案件作者和系统评测的复盘文档，不作为玩家端直接展示文本。
"""


def _step_lines(step_records: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for record in step_records:
        block = "；Director 拦截" if record["director_blocked"] else ""
        lines.append(
            f"{record['step']}. {record['label']}：accepted="
            f"{str(record['accepted']).lower()}，phase=`{record['phase_after']}`"
            f"{block}。事件：{_inline_code_list(record['new_event_types'])}。"
            f"玩家已知：{_inline_code_list(record['known_world_info_after'])}。"
        )
    return lines


def _player_knowledge_lines(
    session: Any,
    world_info_by_id: Mapping[str, Any],
    clue_by_id: Mapping[str, Any],
) -> list[str]:
    lines: list[str] = []
    for knowledge in sorted(
        session.player_knowledge.values(),
        key=lambda item: item.knowledge_id,
    ):
        clue_id = knowledge.clue_id or ""
        world_info_id = knowledge.world_info_id or ""
        lines.append(
            f"- `{world_info_id}`：{_world_info_title(world_info_by_id, world_info_id)}；"
            f"来源线索 `{clue_id}`（{_clue_title(clue_by_id, clue_id)}），"
            f"source_type=`{knowledge.source_type}`，"
            f"acquisition=`{knowledge.acquisition}`，置信度 {knowledge.confidence:g}。"
        )
    return lines or ["- 无。"]


def _awareness_lines(
    session: Any,
    world_info_by_id: Mapping[str, Any],
    character_by_id: Mapping[str, Any],
) -> list[str]:
    lines: list[str] = []
    for awareness in sorted(
        session.character_fact_awareness.values(),
        key=lambda item: item.awareness_id,
    ):
        lines.append(
            f"- {_character_name(character_by_id, awareness.character_id)} / "
            f"`{awareness.character_id}` 认知 `{awareness.world_info_id}`："
            f"{_world_info_title(world_info_by_id, awareness.world_info_id)}，"
            f"stance=`{awareness.stance}`，source_type=`{awareness.source_type}`，"
            f"置信度 {awareness.confidence:g}。"
        )
    return lines or ["- 无。"]


def _director_lines(step_records: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for record in step_records:
        for block in record["new_director_blocks"]:
            lines.append(
                f"- 第 {record['step']} 步 `{record['label']}` 触发 "
                f"`director.blocked`：target=`{block.get('target_id')}`，"
                f"blocked_fact=`{block.get('blocked_fact_id')}`，"
                f"world_info=`{block.get('world_info_id')}`，"
                f"matched_text=`{block.get('matched_text')}`。"
            )
    return lines or ["- 本次标准路径未触发 `director.blocked`。"]


def _replay_lines(replay_check: Mapping[str, Any]) -> list[str]:
    return [
        f"- `{key}`：{str(value).lower() if isinstance(value, bool) else value}"
        for key, value in replay_check.items()
    ]


def _text_block(value: object, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str):
        return "\n\n".join(str(item) for item in value)
    raise ValueError("Text block must be a string or list of strings")


def _numbered_lines(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, Sequence):
        raise ValueError("Fact reconstruction must be a string or list")
    if not value:
        return "1. 未提供事实重建。"
    return "\n".join(f"{index}. {item}" for index, item in enumerate(value, start=1))


def _fallback_fact_reconstruction(
    session: Any,
    world_info_by_id: Mapping[str, Any],
) -> list[str]:
    facts: list[str] = []
    for world_info_id in sorted(_player_world_info_ids(session)):
        facts.append(
            f"玩家确认 `{world_info_id}`：{_world_info_title(world_info_by_id, world_info_id)}。"
        )
    return facts


def _world_info_title(world_info_by_id: Mapping[str, Any], world_info_id: str) -> str:
    item = world_info_by_id.get(world_info_id)
    return str(item.title) if item is not None else world_info_id


def _clue_title(clue_by_id: Mapping[str, Any], clue_id: str) -> str:
    item = clue_by_id.get(clue_id)
    return str(item.title) if item is not None else clue_id


def _character_name(character_by_id: Mapping[str, Any], character_id: str) -> str:
    item = character_by_id.get(character_id)
    return str(item.display_name) if item is not None else character_id


def _inline_code_list(values: Sequence[str]) -> str:
    if not values:
        return "无"
    return ", ".join(f"`{value}`" for value in values)


def _validate_outputs(*, json_path: Path, md_path: Path, case_id: str) -> None:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    assert payload["case_id"] == case_id
    assert payload["final_state_summary"]["narrative_phase"] == "resolved"
    assert payload["replay_check"]["all_equal"] is True
    assert markdown.startswith("# 《")
    assert "\u003f" * 8 not in markdown


def _expect_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a mapping")
    return cast(Mapping[str, object], value)


def _expect_sequence(value: object, context: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{context} must be a list")
    return value


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT))
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    main()
