from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.cases.loader import CaseLoader  # noqa: E402
from app.domain.models import (  # noqa: E402
    ActionType,
    CasePackage,
    PlayerAction,
    PresentationMode,
    SubjectType,
)
from app.runtime.action_router import ActionRouter  # noqa: E402
from app.runtime.service import create_runtime  # noqa: E402
from app.runtime.tracing import RuntimeTracer  # noqa: E402


@dataclass(frozen=True)
class ParsedCommand:
    command: str
    action: PlayerAction | None = None
    error: str | None = None


def main(argv: list[str] | None = None) -> None:
    _configure_stdio()
    args = _parse_args(argv)
    case = CaseLoader().load(PROJECT / "cases" / args.case_id)
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer(
            jsonl_path=args.trace_jsonl,
            log_path=args.trace_log,
            enabled=not args.no_trace,
        ),
    )
    session = runtime.session_store.create(case)
    print(f"Case: {case.meta.title} ({case.meta.id})")
    print(f"Session: {session.id}")
    print("Type help for commands.")

    while True:
        try:
            raw_line = input("> ")
        except EOFError:
            break
        parsed = parse_player_command(raw_line, case=case)
        if parsed.command in {"quit", "exit"}:
            break
        if parsed.command == "help":
            _print_help()
            continue
        if parsed.command == "state":
            _print_state(runtime, case, session)
            continue
        if parsed.command == "events":
            _print_events(session)
            continue
        if parsed.command == "memory":
            _print_memory(session)
            continue
        if parsed.error is not None:
            print(f"Error: {parsed.error}")
            continue
        if parsed.action is None:
            continue
        response = runtime.action_service.handle(session=session, action=parsed.action)
        if response.speech:
            print(f"NPC: {response.speech}")
        print(
            f"accepted={str(response.accepted).lower()} "
            f"phase={response.state.narrative_phase} "
            f"events={','.join(event.type.value for event in response.new_events)}"
        )


def parse_player_command(
    raw_line: str,
    *,
    case: CasePackage | None = None,
) -> ParsedCommand:
    line = raw_line.strip()
    if not line:
        return ParsedCommand(command="empty")
    parts = line.split()
    command = parts[0].lower()
    if command in {"quit", "exit", "help", "state", "events", "memory"}:
        return ParsedCommand(command=command)
    try:
        if command == "inspect":
            if len(parts) != 2:
                return ParsedCommand(command=command, error="usage: inspect <hotspot>")
            return ParsedCommand(
                command=command,
                action=PlayerAction(type=ActionType.INSPECT, target_id=parts[1]),
            )
        if command == "talk":
            if len(parts) < 3:
                return ParsedCommand(command=command, error="usage: talk <npc> <text>")
            return ParsedCommand(
                command=command,
                action=PlayerAction(
                    type=ActionType.TALK,
                    target_id=parts[1],
                    text=" ".join(parts[2:]),
                ),
            )
        if command == "ask":
            if len(parts) < 4:
                return ParsedCommand(
                    command=command,
                    error="usage: ask <npc> clue|character|scene <id> [text]",
                )
            subject_type = SubjectType(parts[2])
            subject_id = parts[3]
            text = " ".join(parts[4:]) if len(parts) > 4 else None
            return ParsedCommand(
                command=command,
                action=PlayerAction(
                    type=ActionType.ASK_ABOUT,
                    target_id=parts[1],
                    subject_type=subject_type,
                    subject_id=subject_id,
                    text=text,
                ),
            )
        if command == "present":
            if len(parts) < 3:
                return ParsedCommand(
                    command=command,
                    error=(
                        "usage: present <npc> <clue> "
                        "[private [text] | public <scene> [text]]"
                    ),
                )
            presentation_mode = PresentationMode.PRIVATE
            scene_id = None
            text_parts = parts[3:]
            if text_parts:
                mode_token = text_parts[0].lower()
                if mode_token == "private":
                    text_parts = text_parts[1:]
                elif mode_token in {"public", "scene_shared"}:
                    if len(text_parts) < 2:
                        return ParsedCommand(
                            command=command,
                            error="usage: present <npc> <clue> public <scene> [text]",
                        )
                    presentation_mode = PresentationMode.SCENE_SHARED
                    scene_id = text_parts[1]
                    text_parts = text_parts[2:]
            return ParsedCommand(
                command=command,
                action=PlayerAction(
                    type=ActionType.PRESENT_CLUE,
                    target_id=parts[1],
                    clue_id=parts[2],
                    scene_id=scene_id,
                    presentation_mode=presentation_mode,
                    text=" ".join(text_parts) if text_parts else None,
                ),
            )
        if command == "accuse":
            if len(parts) < 4:
                return ParsedCommand(
                    command=command,
                    error="usage: accuse <npc> <claim> <evidence...>",
                )
            return ParsedCommand(
                command=command,
                action=PlayerAction(
                    type=ActionType.ACCUSE,
                    target_id=parts[1],
                    claim_id=parts[2],
                    evidence_clue_ids=parts[3:],
                    text=line,
                ),
            )
    except ValueError as exc:
        return ParsedCommand(command=command, error=str(exc))
    if case is not None:
        routed = ActionRouter(case).route(line)
        if routed.action is not None:
            return ParsedCommand(command="natural_language", action=routed.action)
        if routed.needs_clarification:
            missing = ", ".join(routed.missing_slots)
            return ParsedCommand(
                command="natural_language",
                error=f"needs clarification: {missing}",
            )
    return ParsedCommand(command=command, error=f"unknown command: {command}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the terminal AgentLoop MVP.")
    parser.add_argument("--case-id", default="fake_case_001")
    parser.add_argument(
        "--trace-jsonl",
        type=Path,
        default=PROJECT / "logs" / "runtime_trace.jsonl",
    )
    parser.add_argument(
        "--trace-log",
        type=Path,
        default=PROJECT / "logs" / "runtime_trace.log",
    )
    parser.add_argument("--no-trace", action="store_true")
    return parser.parse_args(argv)


def _configure_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _print_help() -> None:
    print("inspect <hotspot>")
    print("talk <npc> <text>")
    print("ask <npc> clue|character|scene <id> [text]")
    print("present <npc> <clue> [private [text] | public <scene> [text]]")
    print("accuse <npc> <claim> <evidence...>")
    print("state | events | memory | quit")


def _print_state(runtime: object, case: object, session: object) -> None:
    from app.storage.memory import build_state_summary

    state = build_state_summary(case, session)
    print(state.model_dump_json(indent=2))


def _print_events(session: object) -> None:
    for event in session.events:
        print(f"{event.created_at} {event.type.value} actor={event.actor_id}")


def _print_memory(session: object) -> None:
    if not session.memory_snapshots:
        print("No memory snapshots.")
        return
    for snapshot in session.memory_snapshots.values():
        print(
            f"{snapshot.memory_id} salience={snapshot.salience:g} "
            f"scope={snapshot.memory_scope} layer={snapshot.memory_layer} "
            f"sources={','.join(snapshot.source_event_ids)}"
        )
        print(f"  {snapshot.content}")


if __name__ == "__main__":
    main()
