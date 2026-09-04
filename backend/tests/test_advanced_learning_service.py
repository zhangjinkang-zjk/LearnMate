"""Pure task-contract tests for advanced learning."""

from backend.src.service.advanced.service import build_advanced_task, classify_goal


def _path(weak_points=None):
    return {
        "path_id": 12,
        "goal": "多智能体协同决策",
        "current_node_id": 2,
        "nodes": [
            {"id": 1, "title": "智能体基础", "status": "completed"},
            {
                "id": 2,
                "title": "协同冲突处理",
                "status": "in_progress",
                "knowledge_tags": ["职责划分"],
                "resources": [{"id": 8, "title": "协同案例", "resource_type": "document"}],
            },
        ],
        "diagnosis": {"weak_points": weak_points or []},
    }


def test_classify_goal_supports_existing_onboarding_options():
    assert classify_goal("完成一个可验证的项目") == "project"
    assert classify_goal("准备相关岗位就业") == "job"
    assert classify_goal("转入新的技术方向") == "transition"
    assert classify_goal("建立系统化知识基础") == "foundation"
    assert classify_goal("为实验室部署一套问答系统") == "custom"


def test_task_recommendation_uses_goal_progress_and_weak_point():
    profile = {
        "identity": "应届毕业生",
        "direction": "多智能体协同决策",
        "goal": "准备相关岗位就业",
    }
    task = build_advanced_task(profile, _path([{"tag": "职责划分", "accuracy": 0.4}]))

    assert task["mode"] == "job"
    assert task["title"] == "完成一次协同冲突处理岗位情境任务"
    assert "应届毕业生" in task["recommendation"]
    assert "已完成 1 个路径节点" in task["recommendation"]
    assert "掌握度约为 40%" in task["recommendation"]
    assert task["workspace"] == {"path_id": 12, "node_id": 2}
    assert task["resources"][0]["id"] == 8
