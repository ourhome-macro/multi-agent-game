from __future__ import annotations

from app.domain.models import EventType, WorldEvent


def render_player_journey(events: list[WorldEvent]) -> str:
    id_map = {event.id: f"event_{index:03d}" for index, event in enumerate(events, start=1)}
    initial_phase = _initial_phase(events)
    final_phase = _final_phase(events, initial_phase)
    completed_beats = _completed_beats(events)
    discovered_clues = _discovered_clues(events)
    player_knowledge = _player_knowledge(events)
    relationships = _relationship_changes(events)
    memory_snapshots = _memory_snapshots(events, id_map)
    accusation = _accusation_result(events)

    lines = [
        f"# {events[0].case_id} Player Journey",
        "",
        "## Case summary",
        "",
        f"- Case ID: `{events[0].case_id}`",
        "- Session ID: `session`",
        f"- Initial phase: `{initial_phase}`",
        f"- Final phase: `{final_phase}`",
        f"- Event count: `{len(events)}`",
        "",
        "## Timeline",
        "",
    ]
    lines.extend(_timeline(events, id_map))
    lines.extend(
        [
            "",
            "## Discovered clues",
            "",
            *_format_list(discovered_clues),
            "",
            "## Player knowledge",
            "",
            *_format_list(player_knowledge),
            "",
            "## Relationship changes",
            "",
            *_format_list(relationships),
            "",
            "## Memory snapshots",
            "",
            *_format_list(memory_snapshots),
            "",
            "## Accusation result",
            "",
            accusation,
            "",
            "## Final runtime state summary",
            "",
            f"- Narrative phase: `{final_phase}`",
            f"- Completed beats: `{', '.join(completed_beats)}`",
            f"- Discovered clues: `{', '.join(discovered_clues)}`",
            f"- Player knowledge: `{', '.join(item.split('`')[1] for item in player_knowledge)}`",
            "- Memory snapshots: "
            f"`{', '.join(item.split('`')[1] for item in memory_snapshots)}`",
            f"- Relationship records: `{len(relationships)}`",
            f"- Event count: `{len(events)}`",
            "",
        ]
    )
    return "\n".join(lines)


def _initial_phase(events: list[WorldEvent]) -> str:
    first = events[0]
    return str(first.payload.get("initial_phase", "unknown"))


def _final_phase(events: list[WorldEvent], initial_phase: str) -> str:
    phase = initial_phase
    for event in events:
        if event.type == EventType.NARRATIVE_PHASE_CHANGED:
            phase = str(event.payload["phase"])
    return phase


def _completed_beats(events: list[WorldEvent]) -> list[str]:
    return [
        str(event.payload["beat_id"])
        for event in events
        if event.type == EventType.NARRATIVE_BEAT_COMPLETED
    ]


def _discovered_clues(events: list[WorldEvent]) -> list[str]:
    return [
        str(event.payload["clue_id"])
        for event in events
        if event.type == EventType.CLUE_DISCOVERED
    ]


def _player_knowledge(events: list[WorldEvent]) -> list[str]:
    knowledge: list[str] = []
    for event in events:
        if event.type != EventType.PLAYER_KNOWLEDGE_UPDATED:
            continue
        knowledge.append(
            "`{knowledge_id}` from clue `{clue_id}`: {title} - {summary}".format(
                knowledge_id=event.payload["knowledge_id"],
                clue_id=event.payload["clue_id"],
                title=event.payload["title"],
                summary=event.payload["summary"],
            )
        )
    return knowledge


def _relationship_changes(events: list[WorldEvent]) -> list[str]:
    changes: list[str] = []
    for event in events:
        if event.type == EventType.RELATIONSHIP_CHANGED:
            changes.append(
                "`{source_id}->{target_id}` deltas {deltas}; current {current}".format(
                    source_id=event.payload["source_id"],
                    target_id=event.payload["target_id"],
                    deltas=event.payload["deltas"],
                    current=event.payload["current"],
                )
            )
        if event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
            changes.append(
                "`{source_id}->{target_id}` crossed `{metric}` as `{state}`".format(
                    source_id=event.payload["source_id"],
                    target_id=event.payload["target_id"],
                    metric=event.payload["metric"],
                    state=event.payload["state"],
                )
            )
    return changes


def _memory_snapshots(events: list[WorldEvent], id_map: dict[str, str]) -> list[str]:
    snapshots: list[str] = []
    contents = {
        str(event.payload["memory_id"]): str(event.payload["content"])
        for event in events
        if event.type == EventType.MEMORY_CANDIDATE_CREATED
    }
    for event in events:
        if event.type != EventType.AGENT_MEMORY_SNAPSHOT_UPDATED:
            continue
        raw_memory_id = str(event.payload["memory_id"])
        memory_id = _safe_memory_id(raw_memory_id)
        source_ids = [
            id_map.get(str(item), str(item)) for item in event.payload["source_event_ids"]
        ]
        template = (
            "`{memory_id}` {operation}; salience `{salience}`; sources `{sources}`; "
            "{content}"
        )
        snapshots.append(
            template.format(
                memory_id=memory_id,
                operation=event.payload["operation"],
                salience=event.payload["salience"],
                sources=", ".join(source_ids),
                content=contents.get(raw_memory_id, ""),
            )
        )
    return snapshots


def _accusation_result(events: list[WorldEvent]) -> str:
    for event in events:
        if event.type != EventType.ACCUSATION_EVALUATED:
            continue
        return (
            "- Target `{target_id}`, claim `{claim_id}`, result `{result}`, "
            "matched evidence `{matched}`, missing evidence `{missing}`"
        ).format(
            target_id=event.payload["target_id"],
            claim_id=event.payload["claim_id"],
            result=event.payload["result"],
            matched=", ".join(event.payload["matched_required_evidence"]),
            missing=", ".join(event.payload["missing_required_evidence"]),
        )
    return "- No accusation was evaluated."


def _timeline(events: list[WorldEvent], id_map: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for event in events:
        event_id = id_map[event.id]
        lines.append(f"- `{event_id}` `{event.type}`: {_timeline_text(event, id_map)}")
    return lines


def _timeline_text(event: WorldEvent, id_map: dict[str, str]) -> str:
    payload = event.payload
    if event.type == EventType.SESSION_CREATED:
        return f"Session created for `{payload['case_id']}` in phase `{payload['initial_phase']}`."
    if event.type == EventType.PLAYER_INSPECTED:
        return f"Player inspected `{payload['target_id']}`."
    if event.type == EventType.CLUE_DISCOVERED:
        return f"Clue `{payload['clue_id']}` discovered."
    if event.type == EventType.PLAYER_KNOWLEDGE_UPDATED:
        return f"Player knowledge `{payload['knowledge_id']}` updated."
    if event.type == EventType.MEMORY_CANDIDATE_CREATED:
        return f"Memory candidate `{_safe_memory_id(str(payload['memory_id']))}` created."
    if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED:
        return (
            f"Memory snapshot `{_safe_memory_id(str(payload['memory_id']))}` "
            f"{payload['operation']} from `{_cause(event, id_map)}`."
        )
    if event.type == EventType.CHARACTER_IMPRESSION_UPDATED:
        return "Private character impression updated."
    if event.type == EventType.CHARACTER_FACT_AWARENESS_UPDATED:
        return "Private character fact awareness updated."
    if event.type == EventType.PLAYER_TALKED:
        return f"Player talked to `{payload['target_id']}`."
    if event.type == EventType.PLAYER_ASKED_ABOUT:
        return (
            f"Player asked `{payload['target_id']}` about "
            f"`{payload['subject_type']}:{payload['subject_id']}`."
        )
    if event.type == EventType.PLAYER_PRESENTED_CLUE:
        return f"Player presented clue `{payload['clue_id']}` to `{payload['target_id']}`."
    if event.type == EventType.NPC_SKILL_SELECTED:
        selected_ids = ", ".join(str(item) for item in payload["selected_skill_ids"])
        return f"NPC skill selected for `{payload['target_id']}`: `{selected_ids}`."
    if event.type == EventType.NPC_SKILL_REJECTED:
        rejected = payload.get("rejected_skills", [])
        rejected_ids = ", ".join(str(item["skill_id"]) for item in rejected)
        return f"NPC skill rejected for `{payload['target_id']}`: `{rejected_ids}`."
    if event.type == EventType.NPC_SKILL_COOLDOWN_UPDATED:
        return f"NPC skill cooldown updated for `{payload['target_id']}`."
    if event.type == EventType.NPC_REPLIED:
        return f"NPC replied: \"{payload['speech']}\""
    if event.type == EventType.RELATIONSHIP_CHANGED:
        return f"Relationship `{payload['source_id']}->{payload['target_id']}` changed."
    if event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
        return (
            f"Relationship threshold `{payload['metric']}` crossed as "
            f"`{payload['state']}`."
        )
    if event.type == EventType.DIRECTOR_BLOCKED:
        return "Director blocked an unsafe reply."
    if event.type == EventType.RULE_REJECTED:
        return (
            f"Rejected `{payload['action_type']}`: "
            f"{payload['reason']}."
        )
    if event.type == EventType.NARRATIVE_BEAT_COMPLETED:
        return f"Narrative beat `{payload['beat_id']}` completed."
    if event.type == EventType.NARRATIVE_PHASE_CHANGED:
        return f"Narrative phase changed from `{payload['from_phase']}` to `{payload['phase']}`."
    if event.type == EventType.PLAYER_ACCUSED:
        return (
            f"Player accused `{payload['target_id']}` with claim "
            f"`{payload['claim_id']}`."
        )
    if event.type == EventType.ACCUSATION_EVALUATED:
        return (
            f"Accusation `{payload['claim_id']}` evaluated as "
            f"`{payload['result']}`."
        )
    return "Event recorded."


def _safe_memory_id(memory_id: str) -> str:
    prefix = "memory.player.director_blocked."
    if not memory_id.startswith(prefix):
        return memory_id
    parts = memory_id.split(".")
    if len(parts) < 5:
        return "memory.player.director_blocked.redacted"
    return ".".join([*parts[:4], "redacted_fact"])


def _cause(event: WorldEvent, id_map: dict[str, str]) -> str:
    if event.caused_by_event_id is None:
        return "none"
    return id_map.get(event.caused_by_event_id, event.caused_by_event_id)


def _format_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]
