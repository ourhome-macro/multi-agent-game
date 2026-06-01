from __future__ import annotations

import argparse
from pathlib import Path

from app.scenarios.validation import validate_standard_scenarios


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate standard scenario files.")
    parser.add_argument("path", nargs="?", default="cases")
    args = parser.parse_args()
    for case_id in validate_standard_scenarios(Path(args.path)):
        print(f"OK {case_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
