from __future__ import annotations

import argparse
from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import PlayerAction


def validate_case(case_dir: Path) -> str:
    package = CaseLoader().load(case_dir)
    schema = PlayerAction.model_json_schema()
    properties = schema.get("properties", {})
    if "target_id" not in properties or "target" in properties:
        raise ValueError("PlayerAction target field must be target_id only")
    return package.meta.id


def validate_cases(path: Path) -> list[str]:
    if path.is_dir() and (path / "case.yaml").exists():
        case_dirs = [path]
    elif path.is_dir():
        case_dirs = sorted(item for item in path.iterdir() if item.is_dir())
    else:
        case_dirs = [path]
    validated_ids: list[str] = []
    for case_dir in case_dirs:
        if not (case_dir / "case.yaml").exists():
            continue
        validated_ids.append(validate_case(case_dir))
    if not validated_ids:
        raise ValueError(f"No case packages found under {path}")
    return validated_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate case packages.")
    parser.add_argument("path", nargs="?", default="cases")
    args = parser.parse_args()
    for case_id in validate_cases(Path(args.path)):
        print(f"OK {case_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
