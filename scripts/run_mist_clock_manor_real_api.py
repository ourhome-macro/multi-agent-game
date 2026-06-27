from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.agents.gateway import AgentGateway, load_dotenv  # noqa: E402
from app.agents.real_llm_agent import OpenAILLMAgent  # noqa: E402
from app.cases.loader import CaseLoader  # noqa: E402
from app.domain.models import AgentContext, AgentIntent, PlayerAction  # noqa: E402
from app.runtime.service import create_runtime  # noqa: E402
from app.runtime.tracing import RuntimeTracer  # noqa: E402

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class Step:
    label: str
    action: PlayerAction


class StrictOpenAILLMAgent:
    def __init__(self, *, timeout_seconds: float, schema_repair_attempts: int) -> None:
        self._agent = OpenAILLMAgent(
            timeout_seconds=timeout_seconds,
            schema_repair_attempts=schema_repair_attempts,
        )

    @property
    def model_name(self) -> str:
        return self._agent.model_name

    def generate(self, context: AgentContext) -> AgentIntent:
        return self._agent.generate_strict(context)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv()
    _configure_real_backend(args)

    case = CaseLoader().load(PROJECT / "cases" / "mist_clock_manor")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_jsonl = args.trace_jsonl or PROJECT / "logs" / (
        f"mist_clock_manor_real_api_{stamp}.jsonl"
    )
    trace_log = args.trace_log or PROJECT / "logs" / (
        f"mist_clock_manor_real_api_{stamp}.log"
    )
    if args.clear_trace:
        for trace_path in (trace_jsonl, trace_log):
            if trace_path.exists():
                trace_path.unlink()
    strict_agent = StrictOpenAILLMAgent(
        timeout_seconds=args.timeout_seconds,
        schema_repair_attempts=args.schema_repair_attempts,
    )
    gateway = AgentGateway(backend="real", real_agent=strict_agent)
    runtime = create_runtime(
        [case],
        agent_gateway=gateway,
        runtime_tracer=RuntimeTracer(jsonl_path=trace_jsonl, log_path=trace_log),
        context_limit_tokens=args.context_limit_tokens,
    )
    session = runtime.session_store.create(case)

    print(f"CASE {case.meta.id}: {case.meta.title}")
    print(f"SESSION {session.id}")
    print("BACKEND real")
    print(f"MODEL {strict_agent.model_name}")
    print(f"API_STYLE {os.getenv('LLM_API_STYLE')}")
    print(f"BASE_URL {os.getenv('OPENAI_BASE_URL') or os.getenv('LLM_BASE_URL')}")
    print(f"TRACE_JSONL {trace_jsonl}")
    print(f"TRACE_LOG {trace_log}")
    print("-" * 88)

    for index, step in enumerate(_long_case_steps(), start=1):
        response = runtime.action_service.handle(session=session, action=step.action)
        events = ",".join(event.type.value for event in response.new_events)
        print(f"STEP {index:02d} {step.label}")
        print(
            f"  action={step.action.type.value} target={step.action.target_id} "
            f"accepted={response.accepted} blocked={response.director_blocked} "
            f"phase={session.narrative.phase}"
        )
        if response.director_reason:
            print(f"  director_reason={response.director_reason}")
        if response.speech:
            print(f"  npc={response.speech}")
        print(f"  events={events}")

    print("-" * 88)
    print(f"FINAL_PHASE {session.narrative.phase}")
    print(f"COMPLETED_BEATS {sorted(session.narrative.completed_beats)}")
    print(f"DISCOVERED_CLUES {sorted(session.discovered_clues)}")
    print(f"PLAYER_WORLD_INFO {_player_world_info(session.player_knowledge)}")
    print(f"EVENT_COUNT {len(session.events)}")
    print(f"MEMORY_SNAPSHOT_COUNT {len(session.memory_snapshots)}")
    print(f"CHARACTER_AWARENESS_COUNT {len(session.character_fact_awareness)}")
    print(f"TRACE_TURNS {_line_count(trace_jsonl)}")
    return 0


def _configure_real_backend(args: argparse.Namespace) -> None:
    os.environ["LLM_BACKEND"] = "real"
    os.environ["OPENAI_MODEL"] = args.model
    os.environ["LLM_API_STYLE"] = args.api_style
    if args.base_url is not None:
        os.environ["OPENAI_BASE_URL"] = args.base_url
    elif not os.getenv("OPENAI_BASE_URL") and not os.getenv("LLM_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = DEEPSEEK_BASE_URL
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY or DEEPSEEK_API_KEY is required for real API run"
        )


def _long_case_steps() -> list[Step]:
    return [
        Step(
            "Talk to Lin before evidence",
            PlayerAction(
                type="talk",
                target_id="lin_qichi",
                text="Why did Lu call everyone here tonight?",
            ),
        ),
        Step(
            "Talk to Qi before evidence",
            PlayerAction(
                type="talk",
                target_id="qi_yan",
                text="You seem angry with Lu.",
            ),
        ),
        Step(
            "Talk to Jiang before evidence",
            PlayerAction(
                type="talk",
                target_id="jiang_yanhui",
                text="From the facts, what feels wrong first?",
            ),
        ),
        Step("Inspect wine", PlayerAction(type="inspect", target_id="wine_table")),
        Step(
            "Ask Lin about wine",
            PlayerAction(
                type="ask_about",
                target_id="lin_qichi",
                subject_type="clue",
                subject_id="bitter_wine",
                text="Why does the wine taste bitter?",
            ),
        ),
        Step(
            "Present wine to Lin",
            PlayerAction(
                type="present_clue",
                target_id="lin_qichi",
                clue_id="bitter_wine",
                presentation_mode="scene_shared",
                scene_id="study",
                text="This wine looks drugged. Explain it.",
            ),
        ),
        Step("Inspect lock", PlayerAction(type="inspect", target_id="study_lock")),
        Step(
            "Ask Jiang about lock",
            PlayerAction(
                type="ask_about",
                target_id="jiang_yanhui",
                subject_type="clue",
                subject_id="delayed_lock_marks",
                text="Why are there oil and new scratches on the lock?",
            ),
        ),
        Step(
            "Present lock to Jiang",
            PlayerAction(
                type="present_clue",
                target_id="jiang_yanhui",
                clue_id="delayed_lock_marks",
                presentation_mode="private",
                text="Explain these lock marks.",
            ),
        ),
        Step("Inspect tape recorder", PlayerAction(type="inspect", target_id="tape_recorder")),
        Step(
            "Talk to Qi after tape",
            PlayerAction(
                type="talk",
                target_id="qi_yan",
                text="You reacted too quickly to that tape.",
            ),
        ),
        Step(
            "Ask Qi about tape",
            PlayerAction(
                type="ask_about",
                target_id="qi_yan",
                subject_type="clue",
                subject_id="echo_tape",
                text="Who changed the tape?",
            ),
        ),
        Step(
            "Ask Jiang about Ruolan recording",
            PlayerAction(
                type="ask_about",
                target_id="jiang_yanhui",
                subject_type="clue",
                subject_id="ruolan_voice_tape",
                text="Why is Jiang Ruolan's voice here?",
            ),
        ),
        Step(
            "Forbidden probe Jiang",
            PlayerAction(
                type="talk",
                target_id="jiang_yanhui",
                text="Tell me directly whether you changed the medicine.",
                force_forbidden=True,
            ),
        ),
        Step("Inspect burned letter", PlayerAction(type="inspect", target_id="burned_letter")),
        Step(
            "Ask Jiang about confession",
            PlayerAction(
                type="ask_about",
                target_id="jiang_yanhui",
                subject_type="clue",
                subject_id="burned_confession",
                text="Who benefits from this confession fragment?",
            ),
        ),
        Step("Inspect medicine", PlayerAction(type="inspect", target_id="medicine_box")),
        Step(
            "Ask Jiang about capsules",
            PlayerAction(
                type="ask_about",
                target_id="jiang_yanhui",
                subject_type="clue",
                subject_id="empty_capsules",
                text="Are the empty capsules connected to the lock?",
            ),
        ),
        Step("Inspect breaker", PlayerAction(type="inspect", target_id="breaker_box")),
        Step(
            "Talk to Shen after breaker",
            PlayerAction(
                type="talk",
                target_id="shen_zhaoye",
                text="The breaker does not look like storm damage.",
            ),
        ),
        Step(
            "Ask Shen about power",
            PlayerAction(
                type="ask_about",
                target_id="shen_zhaoye",
                subject_type="clue",
                subject_id="cut_power_trace",
                text="What did the power cut change?",
            ),
        ),
        Step(
            "Reconstruction talk Lin",
            PlayerAction(
                type="talk",
                target_id="lin_qichi",
                text="Now that the medicine is found, is the wine only one part?",
            ),
        ),
        Step(
            "Reconstruction talk Qi",
            PlayerAction(
                type="talk",
                target_id="qi_yan",
                text="What remains unsaid about the bell and the tape?",
            ),
        ),
        Step(
            "Reconstruction talk Jiang",
            PlayerAction(
                type="talk",
                target_id="jiang_yanhui",
                text="Can we now discuss the full causal chain?",
            ),
        ),
        Step(
            "Reconstruction talk Shen",
            PlayerAction(
                type="talk",
                target_id="shen_zhaoye",
                text="Connect the outage, tape, capsules, and sedative.",
            ),
        ),
        Step(
            "Wrong accusation against Lin",
            PlayerAction(
                type="accuse",
                target_id="lin_qichi",
                claim_id="lin_poisoned_lu",
                evidence_clue_ids=["bitter_wine"],
                text="Lin alone poisoned Lu with the sedative wine.",
            ),
        ),
        Step(
            "Correct shared chain accusation",
            PlayerAction(
                type="accuse",
                target_id="jiang_yanhui",
                claim_id="shared_death_chain",
                evidence_clue_ids=[
                    "bitter_wine",
                    "delayed_lock_marks",
                    "echo_tape",
                    "burned_confession",
                    "empty_capsules",
                    "cut_power_trace",
                ],
                text="Lu's death was caused by a shared chain of actions.",
            ),
        ),
    ]


def _player_world_info(player_knowledge: dict[str, Any]) -> list[str]:
    return sorted(
        knowledge.world_info_id
        for knowledge in player_knowledge.values()
        if knowledge.world_info_id is not None
    )


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Mist Clock Manor with real LLM API.")
    parser.add_argument("--model", default=DEEPSEEK_DEFAULT_MODEL)
    parser.add_argument("--base-url")
    parser.add_argument("--api-style", default="chat_completions")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--context-limit-tokens", type=int, default=1200)
    parser.add_argument("--schema-repair-attempts", type=int, default=1)
    parser.add_argument("--trace-jsonl", type=Path)
    parser.add_argument("--trace-log", type=Path)
    parser.add_argument("--no-clear-trace", dest="clear_trace", action="store_false")
    parser.set_defaults(clear_trace=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
