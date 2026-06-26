from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.models import (
    AgentMemorySnapshot,
    EventType,
    MemoryOperation,
    SessionState,
    WorldEvent,
)
from app.runtime.events import EventRecorder

DEFAULT_ARCHIVE_AFTER_DAYS = 7
DEFAULT_REINFORCED_EVENT_COUNT = 2
ARCHIVABLE_SCOPES = {"session", "npc_private", "scene_shared"}


class MemoryArchivalSystem:
    def __init__(
        self,
        recorder: EventRecorder,
        *,
        archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
        reinforced_event_count: int = DEFAULT_REINFORCED_EVENT_COUNT,
    ) -> None:
        self._recorder = recorder
        self._archive_after = timedelta(days=archive_after_days)
        self._reinforced_event_count = reinforced_event_count

    def apply(
        self,
        *,
        session: SessionState,
        caused_by_event_id: str | None = None,
    ) -> list[WorldEvent]:
        as_of = _archive_as_of(session, caused_by_event_id)
        if as_of is None:
            return []

        events: list[WorldEvent] = []
        for snapshot in sorted(
            session.memory_snapshots.values(),
            key=lambda item: item.memory_id,
        ):
            if not self._should_archive(snapshot, as_of):
                continue
            events.append(
                self._archive_snapshot(
                    session=session,
                    snapshot=snapshot,
                    caused_by_event_id=caused_by_event_id,
                )
            )
        return events

    def _should_archive(self, snapshot: AgentMemorySnapshot, as_of: datetime) -> bool:
        if snapshot.memory_layer != "working":
            return False
        if snapshot.memory_scope not in ARCHIVABLE_SCOPES:
            return False
        archive_after = _archive_after(snapshot, self._archive_after)
        if archive_after is None:
            return False
        reinforced_event_count = _reinforced_event_count(
            snapshot,
            self._reinforced_event_count,
        )
        if _reinforcement_count(snapshot) >= reinforced_event_count:
            return False
        updated_at = _parse_datetime(snapshot.updated_at or snapshot.created_at)
        if updated_at is None:
            return False
        return as_of - updated_at >= archive_after

    def _archive_snapshot(
        self,
        *,
        session: SessionState,
        snapshot: AgentMemorySnapshot,
        caused_by_event_id: str | None,
    ) -> WorldEvent:
        payload = _snapshot_payload(snapshot)
        payload["memory_layer"] = "archival"
        payload["operation"] = "archive"
        payload["archived_from_layer"] = snapshot.memory_layer
        payload["archival_policy"] = {
            "archive_after_days": self._archive_after.days,
            "reinforced_event_count": self._reinforced_event_count,
        }
        event = self._recorder.append(
            session,
            actor_id="memory_archival_system",
            event_type=EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
            payload=payload,
            caused_by_event_id=caused_by_event_id,
        )
        session.memory_snapshots[snapshot.memory_id] = snapshot.model_copy(
            update={
                "memory_layer": "archival",
                "last_operation": MemoryOperation.ARCHIVE,
                "last_updated_event_id": event.id,
                "updated_at": event.created_at,
            }
        )
        return event


def _snapshot_payload(snapshot: AgentMemorySnapshot) -> dict[str, object]:
    return {
        "memory_id": snapshot.memory_id,
        "rule_id": snapshot.rule_id,
        "memory_type": snapshot.memory_type,
        "memory_scope": snapshot.memory_scope,
        "memory_layer": snapshot.memory_layer,
        "subject_id": snapshot.subject_id,
        "owner_character_id": snapshot.owner_character_id,
        "visible_to_character_ids": list(snapshot.visible_to_character_ids),
        "content": snapshot.content,
        "source_event_ids": list(snapshot.source_event_ids),
        "source_memory_ids": list(snapshot.source_memory_ids),
        "salience": snapshot.salience,
        "confidence": snapshot.confidence,
        "visibility": snapshot.visibility,
        "metadata": dict(snapshot.metadata),
    }


def _archive_as_of(
    session: SessionState,
    caused_by_event_id: str | None,
) -> datetime | None:
    if caused_by_event_id is not None:
        for event in reversed(session.events):
            if event.id != caused_by_event_id:
                continue
            parsed = _parse_datetime(event.created_at)
            if parsed is not None:
                return parsed
            break
    return _latest_external_event_time(session)


def _latest_external_event_time(session: SessionState) -> datetime | None:
    for event in reversed(session.events):
        if (
            event.actor_id == "memory_archival_system"
            and event.payload.get("operation") == "archive"
        ):
            continue
        parsed = _parse_datetime(event.created_at)
        if parsed is not None:
            return parsed
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _reinforcement_count(snapshot: AgentMemorySnapshot) -> int:
    return len({event_id for event_id in snapshot.source_event_ids if event_id})


def _archive_after(
    snapshot: AgentMemorySnapshot,
    default: timedelta,
) -> timedelta | None:
    policy = snapshot.metadata.get("decay_policy")
    if policy == "never_archive":
        return None
    if policy == "ephemeral":
        return timedelta(days=0)
    if isinstance(policy, dict):
        if policy.get("name") == "never_archive":
            return None
        if policy.get("name") == "ephemeral":
            return timedelta(days=0)
        days = policy.get("archive_after_days")
        if isinstance(days, int):
            return timedelta(days=days)
    return default


def _reinforced_event_count(
    snapshot: AgentMemorySnapshot,
    default: int,
) -> int:
    policy = snapshot.metadata.get("decay_policy")
    if isinstance(policy, dict):
        count = policy.get("reinforced_event_count")
        if isinstance(count, int):
            return count
    if policy == "sticky":
        return max(default, 3)
    return default
