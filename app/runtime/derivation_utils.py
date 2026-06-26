from __future__ import annotations


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
