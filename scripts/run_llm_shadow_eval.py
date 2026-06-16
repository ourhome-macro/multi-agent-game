from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.evaluations.llm_shadow_eval import main  # noqa: E402

if __name__ == "__main__":
    main()
