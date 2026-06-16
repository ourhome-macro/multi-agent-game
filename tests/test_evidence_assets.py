from __future__ import annotations

import json
from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import PlayerAction
from app.runtime.events import EventRecorder
from app.runtime.service import create_runtime
from app.storage.memory import InMemorySessionStore, build_state_summary

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_state_summary_exposes_discovered_evidence_asset_from_player_knowledge() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    summary = response.state.model_dump(mode="json")
    assert len(summary["evidence_assets"]) == 1

    clue = next(item for item in case.clues if item.id == "scratched_drawer")
    evidence = summary["evidence_assets"][0]
    assert evidence == {
        "id": "scratched_drawer",
        "title": clue.title,
        "summary": clue.description,
        "source": "clue",
        "clue_id": "scratched_drawer",
        "world_info_id": "desk_forced_open",
        "source_knowledge_id": "player_knowledge.desk_forced_open",
        "unlocked_at_event_id": session.player_knowledge[
            "player_knowledge.desk_forced_open"
        ].source_event_id,
    }


def test_state_summary_does_not_expose_undiscovered_evidence_assets() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)

    summary = build_state_summary(case, session).model_dump(mode="json")

    assert summary["discovered_clues"] == []
    assert summary["player_knowledge"] == []
    assert summary["evidence_assets"] == []


def test_evidence_assets_do_not_leak_hidden_truth_world_info() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    serialized_evidence = json.dumps(
        response.state.model_dump(mode="json")["evidence_assets"],
        ensure_ascii=False,
    )
    assert "will_swapped" not in serialized_evidence
    assert "killer_is_niece" not in serialized_evidence
    assert "遗嘱被调换" not in serialized_evidence
    assert "真凶是林侄女" not in serialized_evidence
