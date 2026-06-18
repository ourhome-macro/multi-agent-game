from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.cases.linter import PRODUCTION_CASE_ID, lint_production_case


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run production authoring lint for mist_clock_manor."
    )
    parser.add_argument("--case", default=PRODUCTION_CASE_ID)
    parser.add_argument("--cases-root", default="cases")
    parser.add_argument("--format", choices=("summary", "json", "md"), default="summary")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    case_dir = Path(args.cases_root) / args.case
    report = lint_production_case(case_dir, case_id=args.case)
    rendered = _render_report(report, args.format)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report.passed else 1


def _render_report(report: object, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if output_format == "md":
        return report.to_markdown()
    status = "PASS" if report.passed else "FAIL"
    lines = [
        f"case_linter {status} case={report.case_id} violations={len(report.violations)}"
    ]
    for violation in report.violations:
        lines.append(f"- [{violation.code}] {violation.path}: {violation.message}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
