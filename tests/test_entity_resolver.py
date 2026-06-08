from __future__ import annotations

from pathlib import Path

import pytest

from app.cases.loader import CaseLoader
from app.runtime.action_router import EntityKind, EntityResolver, EntityResolveStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


@pytest.fixture()
def resolver() -> EntityResolver:
    return EntityResolver(CaseLoader().load(CASE_DIR))


@pytest.mark.parametrize(
    ("raw_text", "expected_id"),
    [
        ("江医生", "jiang_yanhui"),
        ("江言晖", "jiang_yanhui"),
        ("江雁回", "jiang_yanhui"),
        ("江律师", "jiang_yanhui"),
        ("沈医生", "shen_zhaoye"),
        ("沈照夜", "shen_zhaoye"),
        ("照夜", "shen_zhaoye"),
        ("林栖迟", "lin_qichi"),
        ("林女士", "lin_qichi"),
        ("祁宴", "qi_yan"),
    ],
)
def test_entity_resolver_maps_character_aliases(
    resolver: EntityResolver,
    raw_text: str,
    expected_id: str,
) -> None:
    result = resolver.resolve(raw_text, EntityKind.CHARACTER)

    assert result.status == EntityResolveStatus.RESOLVED
    assert result.best_id == expected_id


@pytest.mark.parametrize(
    "raw_text",
    [
        "医生",
        "那位医生",
    ],
)
def test_entity_resolver_requires_clarification_for_ambiguous_character_alias(
    resolver: EntityResolver,
    raw_text: str,
) -> None:
    result = resolver.resolve(raw_text, EntityKind.CHARACTER)

    assert result.status == EntityResolveStatus.AMBIGUOUS
    assert set(result.candidate_ids) == {"jiang_yanhui", "shen_zhaoye"}


@pytest.mark.parametrize(
    ("raw_text", "expected_id"),
    [
        ("空胶囊", "empty_capsules"),
        ("胶囊壳", "empty_capsules"),
        ("空药壳", "empty_capsules"),
        ("药瓶里的空胶囊", "empty_capsules"),
        ("药盒", "empty_capsules"),
        ("药瓶", "empty_capsules"),
        ("配电箱", "cut_power_trace"),
        ("电箱", "cut_power_trace"),
        ("电闸", "cut_power_trace"),
        ("断路器", "cut_power_trace"),
        ("书房门锁", "delayed_lock_marks"),
        ("门锁痕迹", "delayed_lock_marks"),
        ("锁上的划痕", "delayed_lock_marks"),
        ("延迟锁痕", "delayed_lock_marks"),
    ],
)
def test_entity_resolver_maps_clue_aliases(
    resolver: EntityResolver,
    raw_text: str,
    expected_id: str,
) -> None:
    result = resolver.resolve(raw_text, EntityKind.CLUE)

    assert result.status == EntityResolveStatus.RESOLVED
    assert result.best_id == expected_id


@pytest.mark.parametrize(
    ("raw_text", "expected_id"),
    [
        ("药盒", "medicine_box"),
        ("药柜里的药盒", "medicine_box"),
        ("药瓶", "medicine_box"),
        ("配电箱", "breaker_box"),
        ("电箱", "breaker_box"),
        ("电闸", "breaker_box"),
        ("断路器", "breaker_box"),
        ("书房门锁", "study_lock"),
        ("门锁", "study_lock"),
        ("录音机", "tape_recorder"),
    ],
)
def test_entity_resolver_maps_hotspot_aliases(
    resolver: EntityResolver,
    raw_text: str,
    expected_id: str,
) -> None:
    result = resolver.resolve(raw_text, EntityKind.HOTSPOT)

    assert result.status == EntityResolveStatus.RESOLVED
    assert result.best_id == expected_id


@pytest.mark.parametrize(
    ("raw_text", "expected_id"),
    [
        ("共同死亡链", "shared_death_chain"),
        ("死亡链", "shared_death_chain"),
        ("江医生造成共同死亡", "shared_death_chain"),
        ("林栖迟下毒", "lin_poisoned_lu"),
        ("红酒下毒", "lin_poisoned_lu"),
    ],
)
def test_entity_resolver_maps_claim_aliases(
    resolver: EntityResolver,
    raw_text: str,
    expected_id: str,
) -> None:
    result = resolver.resolve(raw_text, EntityKind.CLAIM)

    assert result.status == EntityResolveStatus.RESOLVED
    assert result.best_id == expected_id


@pytest.mark.parametrize(
    ("raw_text", "kind"),
    [
        ("张三", EntityKind.CHARACTER),
        ("不存在的钥匙", EntityKind.CLUE),
        ("火箭发射器", EntityKind.HOTSPOT),
        ("月球基地", EntityKind.HOTSPOT),
        ("猫是凶手", EntityKind.CHARACTER),
    ],
)
def test_entity_resolver_does_not_fuzzy_unknown_entities(
    resolver: EntityResolver,
    raw_text: str,
    kind: EntityKind,
) -> None:
    result = resolver.resolve(raw_text, kind)

    assert result.status == EntityResolveStatus.UNKNOWN
    assert result.best_id is None
