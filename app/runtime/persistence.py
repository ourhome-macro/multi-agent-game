from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import WorldEvent


class JsonlEventStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def save(self, events: list[WorldEvent]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as event_file:
            for event in events:
                event_file.write(event.model_dump_json() + "\n")

    def load(self) -> list[WorldEvent]:
        if not self._path.exists():
            return []
        events: list[WorldEvent] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(WorldEvent.model_validate(json.loads(line)))
        return events
