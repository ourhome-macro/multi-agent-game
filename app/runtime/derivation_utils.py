from __future__ import annotations

AUTHORITY_SOURCE_PLAYER_EVIDENCE = "player_evidence"
AUTHORITY_SOURCE_RULE_DERIVED = "rule_derived"
PRIVACY_REASON_PRIVATE_PRESENTATION = "private_presentation"
PRIVACY_REASON_SCENE_SHARED_PRESENTATION = "scene_shared_presentation"
PRIVACY_REASON_SCENE_SHARED_PRIVATE_INTERPRETATION = "scene_shared_private_interpretation"


def memory_id(*parts: object) -> str:
    return ".".join(str(part) for part in parts)


def clue_discovered_memory_id(clue_id: object) -> str:
    return memory_id("memory", "player", "clue_discovered", clue_id)


def reconstruction_memory_id(
    memory_type: str,
    case_thread_id: object,
    *,
    character_id: object | None = None,
) -> str:
    parts: list[object] = ["memory", "player", memory_type, "reconstruction"]
    if character_id is not None:
        parts.append(character_id)
    parts.append(case_thread_id)
    return memory_id(*parts)


def asked_about_memory_id(
    target_id: object,
    subject_type: object,
    subject_id: object,
) -> str:
    return memory_id("memory", "player", "asked_about", target_id, subject_type, subject_id)


def presented_clue_memory_id(target_id: object, clue_id: object) -> str:
    return memory_id("memory", "player", "presented_clue", target_id, clue_id)


def scene_shared_presented_clue_memory_id(scene_id: object, clue_id: object) -> str:
    return memory_id("memory", "player", "scene_shared", "presented_clue", scene_id, clue_id)


def scene_shared_private_memory_id(
    memory_type: str,
    character_id: object,
    scene_id: object,
    clue_id: object,
) -> str:
    return memory_id(
        "memory",
        "player",
        "scene_shared",
        memory_type,
        character_id,
        scene_id,
        clue_id,
    )


def player_accused_memory_id(target_id: object, claim_id: object) -> str:
    return memory_id("memory", "player", "accused", target_id, claim_id)


def accusation_evaluated_memory_id(
    target_id: object,
    claim_id: object,
    result: object,
) -> str:
    return memory_id("memory", "player", "accusation_evaluated", target_id, claim_id, result)


def relationship_threshold_memory_id(
    source_id: object,
    metric: object,
    state_name: object,
) -> str:
    return memory_id(
        "memory",
        "player",
        "relationship_threshold",
        source_id,
        "player",
        metric,
        state_name,
    )


def director_blocked_memory_id(target_id: object, blocked_fact_id: object) -> str:
    return memory_id("memory", "player", "director_blocked", target_id, blocked_fact_id)


def append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def identifier_topic_tags(identifier: str) -> list[str]:
    tags: list[str] = []
    for part in identifier.split("_"):
        if part:
            append_unique(tags, part)
    if identifier:
        append_unique(tags, identifier)
    return tags


def clue_memory_metadata(
    *,
    clue_id: str,
    related_event_ids: list[str] | None = None,
    related_character_ids: list[str] | None = None,
    world_info_ids: list[str] | None = None,
    case_thread_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "clue_id": clue_id,
        "topic_tags": ordered_unique(
            [
                *identifier_topic_tags(clue_id),
                *(related_event_ids or []),
                *(related_character_ids or []),
            ]
        ),
    }
    if world_info_ids:
        metadata["world_info_id"] = world_info_ids[0]
    if case_thread_metadata:
        metadata.update(case_thread_metadata)
    return metadata


def case_thread_metadata_for_claim(
    *,
    claim_id: str,
    clue_id: str,
    required_evidence: list[str],
) -> dict[str, object]:
    adjacent_clue_ids = [
        evidence_id
        for evidence_id in required_evidence
        if evidence_id != clue_id
    ]
    return {
        "case_thread_id": claim_id,
        "chain_node_id": clue_id,
        "adjacent_clue_ids": adjacent_clue_ids,
        "key_clue": True,
        "is_plot_critical": True,
    }


def case_thread_topic_tags(
    *,
    case_thread_id: str,
    clue_ids: list[str],
) -> list[str]:
    return ordered_unique([case_thread_id, "reconstruction", *clue_ids])


def role_reconstruction_metadata(
    *,
    thread_metadata: dict[str, object],
    case_thread_id: str,
    character_id: str,
    adjacent_clue_ids: list[str],
) -> dict[str, object]:
    return {
        **thread_metadata,
        "phase_ids": ["reconstruction", "resolved"],
        "topic_tags": ordered_unique(
            [
                case_thread_id,
                "reconstruction",
                character_id,
                *role_reconstruction_topic_tags(character_id),
                *adjacent_clue_ids,
            ]
        ),
        "authority_source": AUTHORITY_SOURCE_RULE_DERIVED,
    }


def claim_supports_reconstruction_thread(allowed_phases: list[str]) -> bool:
    return bool({"reconstruction", "resolved"} & {str(phase) for phase in allowed_phases})


def role_reconstruction_topic_tags(character_id: str) -> list[str]:
    tags_by_character = {
        "shen_zhaoye": ["cut_power_trace", "power_cut"],
        "qi_yan": ["echo_tape", "tape_swapped"],
        "lin_qichi": ["bitter_wine", "sedative"],
        "jiang_yanhui": ["empty_capsules", "delayed_lock_marks", "lock_modified"],
    }
    return tags_by_character.get(character_id, [])


def ordered_unique(items: list[str]) -> list[str]:
    unique: list[str] = []
    for item in items:
        append_unique(unique, item)
    return unique


def clamp01(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 4)


def clamp_relationship(value: float) -> float:
    return round(min(max(value, -1.0), 1.0), 4)
