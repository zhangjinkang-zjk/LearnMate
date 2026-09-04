from backend.src.service.path.difficulty import (
    clamp_difficulty_score,
    derive_difficulty_score,
    normalize_relative_difficulty,
)
from backend.src.service.resource.matching import build_resource_difficulty_match
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


def test_resource_difficulty_match_uses_bound_node_difficulty_and_user_level():
    points = build_resource_difficulty_match(
        [
            {
                "id": 11,
                "title": "基础概念",
                "order_index": 1,
                "difficulty_score": 1.0,
                "resources": [{"id": 101, "title": "概念讲义", "resource_type": "document"}],
            },
            {
                "id": 12,
                "title": "综合练习",
                "order_index": 2,
                "difficulty_score": 4.0,
                "resources": [{"id": 102, "title": "迁移练习", "resource_type": "exercise"}],
            },
        ],
        user_level=25,
    )

    assert [point["resource_id"] for point in points] == [101, 102]
    assert points[0]["difficulty_score"] < points[1]["difficulty_score"]
    assert points[0]["user_level"] == 25
    assert points[0]["status"] == "well_matched"
    assert points[1]["status"] == "too_hard"


def test_resource_difficulty_match_is_unknown_without_user_level_and_deduplicates_resources():
    points = build_resource_difficulty_match(
        [
            {"order_index": 1, "resources": [{"resource_id": 7, "title": "同一资源"}]},
            {"order_index": 2, "resources": [{"resource_id": 7, "title": "重复绑定"}]},
        ],
        user_level=None,
    )

    assert len(points) == 1
    assert points[0]["status"] == "unknown"
    assert points[0]["match_score"] is None
