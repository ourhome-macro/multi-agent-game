from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.evaluations.llm_shadow_eval import (  # noqa: E402
    DEFAULT_CASE_REPORT_ROOT,
    DEFAULT_SUMMARY_DIR,
    run_all_standard_path_shadow_evals,
    run_standard_path_shadow_eval,
)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.all:
        reports = run_all_standard_path_shadow_evals(
            cases_root=_resolve_cli_path(args.cases_root),
            backend=args.backend,
            report_root=_resolve_cli_path(args.report_root),
            summary_dir=_resolve_cli_path(args.summary_dir),
        )
        print(json.dumps([report.model_dump() for report in reports], ensure_ascii=False, indent=2))
        return

    case_id = args.case or args.case_id
    case_dir = _resolve_case_dir(case_id=case_id, case_dir=args.case_dir)
    scenario_path = (
        _resolve_cli_path(args.scenario)
        if args.scenario is not None
        else case_dir / "scenarios" / "standard_path.yaml"
    )
    report = run_standard_path_shadow_eval(
        case_dir=case_dir,
        scenario_path=scenario_path,
        backend=args.backend,
        report_root=_resolve_cli_path(args.report_root),
        step_index=args.step,
    )
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run LLM Shadow Eval v0 for standard_path scenarios."
    )
    parser.add_argument("--case", dest="case", help="Case id, for example mist_clock_manor.")
    parser.add_argument("--case-id", default="mist_clock_manor")
    parser.add_argument("--step", type=int, help="1-based scenario step index to shadow eval.")
    parser.add_argument("--case-dir", type=Path)
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--cases-root", type=Path, default=PROJECT / "cases")
    parser.add_argument("--report-root", type=Path, default=DEFAULT_CASE_REPORT_ROOT)
    parser.add_argument("--summary-dir", type=Path, default=DEFAULT_SUMMARY_DIR)
    parser.add_argument("--backend", choices=["stub", "real"])
    parser.add_argument("--all", action="store_true")
    return parser.parse_args(argv)


def _resolve_case_dir(*, case_id: str, case_dir: Path | None) -> Path:
    if case_dir is not None:
        return _resolve_cli_path(case_dir)
    return PROJECT / "cases" / case_id


def _resolve_cli_path(path: Path) -> Path:
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


if __name__ == "__main__":
    main()
