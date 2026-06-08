from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.runtime.action_router import ActionRouter, ActionRouteStatus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


def test_router_trace_does_not_store_raw_player_text() -> None:
    router = ActionRouter(CaseLoader().load(CASE_DIR))
    raw_text = "我问江医生关于空胶囊的事情"

    result = router.route(raw_text)
    trace = result.trace.to_safe_dict()

    assert "raw_text" not in trace
    assert raw_text not in str(trace)
    assert trace["raw_text_hash"].startswith("sha256:")
    assert trace["raw_text_length"] == len(raw_text)
    assert trace["recognized_action"] == "ask_about"
    assert trace["target_candidates"] == ["jiang_yanhui"]
    assert trace["subject_candidates"] == ["empty_capsules"]
    assert trace["confidence"] > 0.0
    assert trace["resolver_strategy"] == "alias_exact"
    assert trace["director_precheck_result"] is None


def test_router_trace_hash_is_stable_and_input_sensitive() -> None:
    router = ActionRouter(CaseLoader().load(CASE_DIR))

    first = router.route("我问江医生关于空胶囊的事情").trace.to_safe_dict()
    second = router.route("我问江医生关于空胶囊的事情").trace.to_safe_dict()
    different = router.route("我问江医生关于药盒的事情").trace.to_safe_dict()

    assert first["raw_text_hash"] == second["raw_text_hash"]
    assert first["raw_text_hash"] != different["raw_text_hash"]


def test_router_trace_exists_for_clarification() -> None:
    router = ActionRouter(CaseLoader().load(CASE_DIR))

    result = router.route("我问医生那个东西")
    trace = result.trace.to_safe_dict()

    assert result.status == ActionRouteStatus.NEEDS_CLARIFICATION
    assert trace["recognized_action"] is None
    assert trace["target_candidates"] == ["jiang_yanhui", "shen_zhaoye"]
    assert trace["subject_candidates"] == []
    assert trace["reason"] == "ambiguous_route"
    assert "我问医生那个东西" not in str(trace)


def test_router_trace_exists_for_unknown() -> None:
    router = ActionRouter(CaseLoader().load(CASE_DIR))

    result = router.route("我检查火箭发射器")
    trace = result.trace.to_safe_dict()

    assert result.status == ActionRouteStatus.UNKNOWN
    assert trace["recognized_action"] is None
    assert trace["target_candidates"] == []
    assert trace["subject_candidates"] == []
    assert trace["reason"] == "unknown_hotspot"
    assert "火箭发射器" not in str(trace)


def test_router_trace_can_record_director_precheck_summary_without_raw_text() -> None:
    router = ActionRouter(CaseLoader().load(CASE_DIR))
    result = router.route("我问江医生关于空胶囊的事情")
    traced = result.with_director_precheck("blocked:subject_not_discovered")

    trace = traced.trace.to_safe_dict()

    assert trace["director_precheck_result"] == "blocked:subject_not_discovered"
    assert "我问江医生关于空胶囊的事情" not in str(trace)
