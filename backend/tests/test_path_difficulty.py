from backend.src.service.path.difficulty import (
    clamp_difficulty_score,
    derive_difficulty_score,
    normalize_relative_difficulty,
)
from backend.src.service.study.service import _build_path_difficulty_trend


def test_clamp_difficulty_score_keeps_relative_baseline_and_rejects_invalid_values():
    assert clamp_difficulty_score("1.35") == 1.35
    assert clamp_difficulty_score(0.8) is None
    assert clamp_difficulty_score("bad", 1.0) == 1.0


def test_derived_difficulty_grows_with_cognitive_and_prerequisite_complexity():
    basic = derive_difficulty_score(
        order_index=1,
        total_nodes=4,
        cognitive_level="记忆",
        module="概念奠基",
        key_points_count=2,
        prerequisite_count=0,
    )
    advanced = derive_difficulty_score(
        order_index=4,
        total_nodes=4,
        cognitive_level="分析",
        module="综合迁移",
        key_points_count=4,
        prerequisite_count=2,
    )
    assert basic >= 1.0
    assert advanced > basic


def test_relative_difficulty_maps_path_order_without_using_progress_state():
    assert normalize_relative_difficulty([1.0, 1.5, 2.5]) == [20, 43, 90]
    assert normalize_relative_difficulty([1.0, 1.0]) == [50, 50]


def test_overview_trend_keeps_first_node_as_baseline_and_exposes_status_separately():
    trend = _build_path_difficulty_trend([
        {"id": 11, "title": "概念", "order_index": 1, "status": "completed", "difficulty_score": 3.0},
        {"id": 12, "title": "案例", "order_index": 2, "status": "unlocked", "difficulty_score": 2.0},
    ])
    assert trend[0]["difficulty_score"] == 1.0
    assert trend[0]["relative_difficulty"] < trend[1]["relative_difficulty"]
    assert trend[0]["status"] == "completed"
