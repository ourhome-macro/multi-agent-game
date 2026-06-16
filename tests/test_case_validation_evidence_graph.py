from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.cases.errors import CaseLoadError
from app.cases.loader import CaseLoader


def test_rejects_reachable_clue_without_world_info_anchor() -> None:
    case_dir = _new_case_dir("orphan_clue_case")
    _write_minimal_case(
        case_dir,
        scenes_yaml=_scene_with_clues(["orphan_clue"]),
        clues_yaml=(
            "- id: orphan_clue\n"
            "  title: Orphan Clue\n"
            "  description: This clue has no fact anchor.\n"
        ),
    )

    with pytest.raises(
        CaseLoadError,
        match="Clue 'orphan_clue' reveals_world_info must reference at least one world_info",
    ):
        CaseLoader().load(case_dir)


def test_rejects_isolated_world_info_not_used_by_authoring_graph() -> None:
    case_dir = _new_case_dir("isolated_world_info_case")
    _write_minimal_case(
        case_dir,
        world_info_yaml=(
            "- id: orphan_fact\n"
            "  title: Orphan Fact\n"
            "  description: No clue, character state, claim, or graph references this fact.\n"
        ),
    )

    with pytest.raises(CaseLoadError, match="WorldInfo ids.*orphan_fact"):
        CaseLoader().load(case_dir)


def test_rejects_claim_graph_unlock_player_knowledge_that_cannot_be_produced(
) -> None:
    case_dir = _new_case_dir("bad_claim_graph_knowledge_case")
    _write_minimal_case(
        case_dir,
        world_info_yaml=(
            "- id: fact\n"
            "  title: Fact\n"
            "  description: A grounded fact.\n"
            "  claim_graph:\n"
            "    safe_fragments:\n"
            "      - id: safe_summary\n"
            "        summary: This fragment should be locked by real player knowledge.\n"
            "        unlock_conditions:\n"
            "          player_knowledge_ids:\n"
            "            - player_knowledge.missing_fact\n"
        ),
        scenes_yaml=_scene_with_clues(["fact_clue"]),
        clues_yaml=(
            "- id: fact_clue\n"
            "  title: Fact Clue\n"
            "  description: A reachable clue.\n"
            "  reveals_world_info:\n"
            "    - fact\n"
        ),
    )

    with pytest.raises(
        CaseLoadError,
        match=(
            "WorldInfo 'fact' safe fragment 'safe_summary' player_knowledge_ids "
            "references unavailable player knowledge: .*player_knowledge.missing_fact"
        ),
    ):
        CaseLoader().load(case_dir)


def test_rejects_high_sensitivity_safe_fragment_without_unlock_conditions(
) -> None:
    case_dir = _new_case_dir("leaky_safe_fragment_case")
    _write_minimal_case(
        case_dir,
        world_info_yaml=(
            "- id: killer_fact\n"
            "  title: Killer Fact\n"
            "  description: A late-game truth.\n"
            "  sensitivity: high\n"
            "  claim_graph:\n"
            "    safe_fragments:\n"
            "      - id: identity_hint\n"
            "        summary: A fragment that would leak too early.\n"
        ),
        scenes_yaml=_scene_with_clues(["killer_clue"]),
        clues_yaml=(
            "- id: killer_clue\n"
            "  title: Killer Clue\n"
            "  description: A reachable clue.\n"
            "  reveals_world_info:\n"
            "    - killer_fact\n"
        ),
    )

    with pytest.raises(
        CaseLoadError,
        match=(
            "WorldInfo 'killer_fact' safe fragment 'identity_hint' "
            "unlock_conditions must not be empty"
        ),
    ):
        CaseLoader().load(case_dir)


def test_rejects_solution_claim_world_info_not_produced_by_required_evidence() -> None:
    case_dir = _new_case_dir("bad_solution_graph_case")
    _write_minimal_case(
        case_dir,
        world_info_yaml=(
            "- id: found_fact\n"
            "  title: Found Fact\n"
            "  description: This fact can be discovered.\n"
            "- id: missing_from_evidence_fact\n"
            "  title: Missing From Evidence Fact\n"
            "  description: This fact exists but the claim evidence does not produce it.\n"
        ),
        scenes_yaml=_scene_with_clues(["found_clue"]),
        clues_yaml=(
            "- id: found_clue\n"
            "  title: Found Clue\n"
            "  description: A reachable clue.\n"
            "  reveals_world_info:\n"
            "    - found_fact\n"
        ),
        solution_claims_yaml=(
            "claims:\n"
            "  - id: bad_claim\n"
            "    target_id: npc\n"
            "    required_evidence:\n"
            "      - found_clue\n"
            "    required_world_info:\n"
            "      - missing_from_evidence_fact\n"
            "    allowed_phases:\n"
            "      - opening\n"
            "    result: correct\n"
        ),
    )

    with pytest.raises(
        CaseLoadError,
        match=(
            "Solution claim 'bad_claim' required_world_info not produced by "
            "required_evidence: .*missing_from_evidence_fact"
        ),
    ):
        CaseLoader().load(case_dir)


def test_rejects_solution_claim_unreachable_required_evidence() -> None:
    case_dir = _new_case_dir("unreachable_solution_evidence_case")
    _write_minimal_case(
        case_dir,
        world_info_yaml=(
            "- id: reachable_fact\n"
            "  title: Reachable Fact\n"
            "  description: This fact can be discovered.\n"
            "- id: unreachable_fact\n"
            "  title: Unreachable Fact\n"
            "  description: This fact is only tied to an unreachable clue.\n"
        ),
        scenes_yaml=_scene_with_clues(["reachable_clue"]),
        clues_yaml=(
            "- id: reachable_clue\n"
            "  title: Reachable Clue\n"
            "  description: A reachable clue.\n"
            "  reveals_world_info:\n"
            "    - reachable_fact\n"
            "- id: unreachable_clue\n"
            "  title: Unreachable Clue\n"
            "  description: This clue is never discovered.\n"
            "  reveals_world_info:\n"
            "    - unreachable_fact\n"
        ),
        solution_claims_yaml=(
            "claims:\n"
            "  - id: unreachable_claim\n"
            "    target_id: npc\n"
            "    required_evidence:\n"
            "      - unreachable_clue\n"
            "    required_world_info:\n"
            "      - unreachable_fact\n"
            "    allowed_phases:\n"
            "      - opening\n"
            "    result: correct\n"
        ),
    )

    with pytest.raises(
        CaseLoadError,
        match=(
            "Solution claim 'unreachable_claim' required_evidence contains "
            "unreachable clues: .*unreachable_clue"
        ),
    ):
        CaseLoader().load(case_dir)


def _write_minimal_case(
    case_dir: Path,
    *,
    world_info_yaml: str = "[]\n",
    scenes_yaml: str | None = None,
    clues_yaml: str = "[]\n",
    solution_claims_yaml: str | None = None,
) -> None:
    (case_dir / "case.yaml").write_text(
        "id: validation_case\n"
        "title: Validation Case\n"
        "description: ''\n"
        "initial_phase: opening\n",
        encoding="utf-8",
    )
    (case_dir / "characters.yaml").write_text(
        "- id: npc\n"
        "  name: NPC\n"
        "  role: Witness\n",
        encoding="utf-8",
    )
    (case_dir / "world_info.yaml").write_text(world_info_yaml, encoding="utf-8")
    (case_dir / "scenes.yaml").write_text(
        scenes_yaml or _scene_with_clues([]),
        encoding="utf-8",
    )
    (case_dir / "clues.yaml").write_text(clues_yaml, encoding="utf-8")
    (case_dir / "relationships.yaml").write_text("[]\n", encoding="utf-8")
    (case_dir / "forbidden_facts.yaml").write_text("[]\n", encoding="utf-8")
    (case_dir / "mock_dialogues.yaml").write_text(
        "- character_id: npc\n"
        "  default_speech: ok\n",
        encoding="utf-8",
    )
    (case_dir / "narrative_rules.yaml").write_text(
        "phases:\n"
        "  - id: opening\n"
        "beats: []\n",
        encoding="utf-8",
    )
    if solution_claims_yaml is not None:
        (case_dir / "solution_claims.yaml").write_text(
            solution_claims_yaml,
            encoding="utf-8",
        )


def _new_case_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / "tmp" / "case_validation_evidence_graph"
    case_dir = root / f"{name}-{uuid4()}"
    case_dir.mkdir(parents=True)
    return case_dir


def _scene_with_clues(clue_ids: list[str]) -> str:
    clue_lines = "".join(f"        - {clue_id}\n" for clue_id in clue_ids)
    discover_clues = clue_lines or "        []\n"
    return (
        "- id: room\n"
        "  name: Room\n"
        "  characters:\n"
        "    - npc\n"
        "  hotspots:\n"
        "    - id: desk\n"
        "      name: Desk\n"
        "      discover_clues:\n"
        f"{discover_clues}"
    )
