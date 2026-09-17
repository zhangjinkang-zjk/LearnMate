from backend.src.service.study.service import (
    _build_reviewable_weak_points,
    _index_reviewable_nodes_by_tag,
)


def test_overview_weak_points_only_include_reviewable_mastery_records():
    nodes = [
        {
            "id": 12,
            "title": "查询意图与问答任务类型识别",
            "status": "completed",
            "knowledge_tags": ["查询意图", "问答任务"],
        },
        {
            "id": 13,
            "title": "未解锁章节",
            "status": "locked",
            "knowledge_tags": ["后续知识点"],
        },
    ]

    points = [
        {"tag": "查询意图", "accuracy": 0.25, "total_attempts": 4, "source": "mastery"},
        {"tag": "记忆(简单题)", "accuracy": 0, "total_attempts": 0, "source": "radar"},
        {"tag": "后续知识点", "accuracy": 0.1, "total_attempts": 2, "source": "mastery"},
    ]

    result = _build_reviewable_weak_points(
        points,
        path_id=79,
        reviewable_nodes_by_tag=_index_reviewable_nodes_by_tag(nodes),
    )

    assert result == [{
        "tag": "查询意图",
        "accuracy": 25,
        "level": "",
        "attempts": 4,
        "source": "mastery",
        "path_id": 79,
        "node_id": 12,
        "node_title": "查询意图与问答任务类型识别",
    }]
