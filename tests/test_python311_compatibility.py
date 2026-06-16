from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_turn_plan_uses_python311_compatible_syntax() -> None:
    source_path = PROJECT_ROOT / "app" / "agents" / "turn_plan.py"

    ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
        feature_version=(3, 11),
    )
