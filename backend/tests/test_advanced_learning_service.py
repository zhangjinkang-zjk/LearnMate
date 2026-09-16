"""Pure task-contract tests for advanced learning.

纯函数风格：不碰数据库、不碰 LLM。快照的读写与后台作业的调度在
`test_advanced_task_scheduling.py` 里用假对象覆盖。
"""

from backend.src.service.advanced.service import (
    ADVANCED_FALLBACK_RETRY_SECONDS,
    _compact_tag_list,
    _describe_failure,
    _find_focus,
    _focus_node,
    _normalise_agent_tasks,
    _redact,
    _snapshot_action,
    advanced_milestone,
    build_advanced_task,
    build_advanced_tasks,
    classify_goal,
    completed_node_count,
    completed_scope,
    completed_scope_tags,
)


def _path(weak_points=None):
    """真实形态的路径：已完成节点带知识标签，current_node_id 指向的还没解锁。

    这不是编的 —— 实测 user 1 就是"10 个节点已完成、锚点节点 status=locked"。
    以前 `_focus_node` 取的是那个 locked 节点，于是任务围绕一个没学过的东西生成。
    """
    return {
        "path_id": 12,
        "goal": "多智能体协同决策",
        "current_node_id": 3,
        "nodes": [
            {
                "id": 1,
                "title": "智能体基础",
                "status": "completed",
                "knowledge_tags": ["职责划分", "协同角色"],
            },
            {
                "id": 2,
                "title": "协同冲突处理",
                "status": "completed",
                "knowledge_tags": ["冲突消解", "投票机制"],
                "resources": [{"id": 8, "title": "协同案例", "resource_type": "document"}],
            },
            {
                "id": 3,
                "title": "多智能体调度",
                "status": "locked",
                "knowledge_tags": ["调度策略"],
            },
        ],
        "diagnosis": {"weak_points": weak_points or []},
    }


def _fresh_path():
    """一个节点都没完成：进阶任务刚解锁、还没有"已完成范围"时的形态。"""
    return {
        "path_id": 12,
        "goal": "多智能体协同决策",
        "current_node_id": 3,
        "nodes": [
            {
                "id": 3,
                "title": "多智能体调度",
                "status": "in_progress",
                "knowledge_tags": ["调度策略"],
            },
        ],
        "diagnosis": {"weak_points": []},
    }


# ── 生成依据：已完成节点 ──────────────────────────────

def test_completed_scope_lists_only_completed_nodes_in_path_order():
    scope = completed_scope(_path())

    assert [item["title"] for item in scope] == ["智能体基础", "协同冲突处理"]
    assert scope[0]["knowledge_tags"] == ["职责划分", "协同角色"]
    assert "多智能体调度" not in [item["title"] for item in scope]


def test_focus_node_is_the_latest_completed_one_not_the_locked_current_one():
    path = _path()

    assert _focus_node(path)["id"] == 2, "锚点必须是最近完成的节点"
    assert _focus_node(path)["status"] == "completed"
    # 那个 locked 的节点仍然是 current_node_id 指向的，只是不再当锚点
    assert path["current_node_id"] == 3


def test_focus_node_falls_back_to_current_when_nothing_is_completed():
    assert _focus_node(_fresh_path())["id"] == 3


def test_completed_scope_tags_dedupes_and_keeps_order():
    tags = completed_scope_tags(_path())

    assert tags == ["职责划分", "协同角色", "冲突消解", "投票机制"]
    assert completed_scope_tags(_fresh_path()) == []


# ── 重点知识点 ────────────────────────────────────────

def test_find_focus_ignores_tags_outside_the_completed_scope():
    """范围外的标签不该被选中 —— 那正是"重点能力"落在没学过的内容上的原因。"""
    focus, weak = _find_focus(
        ["冲突消解", "投票机制"],
        {"weak_points": [{"tag": "没学过的能力", "accuracy": 0.1}]},
        [{"tag": "冲突消解", "accuracy": 0.4, "attempts": 3}],
        "兜底",
    )

    assert focus == "冲突消解"
    assert weak["accuracy"] == 0.4


def test_find_focus_prefers_the_anchor_node_tags_when_there_is_no_mastery_evidence():
    """完全没有掌握度记录时，代表标签要取锚点节点的，不是整条路径的第一个。

    实测踩过：取 `tags[0]` 会得到"课程目标与知识地图概览"——整条路径最早的内容，
    跟当前进度完全脱节。
    """
    focus, weak = _find_focus(
        ["课程目标与知识地图概览", "编排复盘"],
        {"weak_points": []},
        [],
        "兜底",
        prefer=["编排复盘"],
    )

    assert focus == "编排复盘"
    assert weak is None


def test_find_focus_falls_back_to_global_weak_point_only_without_any_tags():
    focus, _ = _find_focus([], {"weak_points": [{"tag": "全局弱点", "accuracy": 0.2}]}, [], "兜底")

    assert focus == "全局弱点"


# ── 任务契约 ──────────────────────────────────────────

def test_classify_goal_supports_existing_onboarding_options():
    assert classify_goal("完成一个可验证的项目") == "project"
    assert classify_goal("准备相关岗位就业") == "job"
    assert classify_goal("转入新的技术方向") == "transition"
    assert classify_goal("建立系统化知识基础") == "foundation"
    assert classify_goal("为实验室部署一套问答系统") == "custom"


def test_task_recommendation_uses_completed_node_and_weak_point():
    profile = {
        "identity": "应届毕业生",
        "direction": "多智能体协同决策",
        "goal": "准备相关岗位就业",
    }
    task = build_advanced_task(profile, _path([{"tag": "冲突消解", "accuracy": 0.4}]))

    assert task["mode"] == "job"
    assert task["title"] == "完成一次协同冲突处理岗位情境任务"
    assert "应届毕业生" in task["recommendation"]
    assert "已完成 2 个路径节点" in task["recommendation"]
    assert "掌握度约为 40%" in task["recommendation"]
    # 工作区挂在锚点节点上：练习会话是靠它去取章节内容的
    assert task["workspace"] == {"path_id": 12, "node_id": 2}
    assert task["resources"][0]["id"] == 8
    # 「推荐依据」卡片读的就是这几个字段，不能空
    assert task["context"]["node_title"] == "协同冲突处理"
    assert task["context"]["node_status_label"] == "已完成"
    assert task["context"]["completed_scope_label"] == "已完成 2 / 3 个节点"
    assert "你已经完成 2 个基础节点" in task["context"]["reason"]


def test_completed_anchor_is_described_in_the_past_tense():
    """锚点是已完成节点，措辞不能还是"你正在学习 X"。"""
    task = build_advanced_task({"goal": "完成一个项目"}, _path())

    assert "你已经完成“协同冲突处理”这个节点" in task["scenario"]
    assert "你正在学习" not in task["scenario"]


def test_incomplete_path_still_uses_the_present_tense_copy():
    task = build_advanced_task({"goal": "完成一个项目"}, _fresh_path())

    assert "你正在学习“多智能体调度”" in task["scenario"]
    assert task["context"]["completed_scope_label"] == "尚无已完成节点"


def test_advanced_tasks_keep_distinct_practice_entry_points():
    profile = {"identity": "工程师", "direction": "多智能体协同决策", "goal": "完成一个项目"}
    tasks = build_advanced_tasks(profile, _path())

    assert [task["kind"] for task in tasks] == ["transfer", "case", "project"]
    assert all(task["workspace"] == {"path_id": 12, "node_id": 2} for task in tasks)


def test_project_task_synthesizes_the_whole_completed_scope():
    """project 的卖点是"综合"，标题和交付物必须真的点名多个已完成标签。"""
    profile = {"identity": "工程师", "direction": "多智能体协同决策", "goal": "完成一个项目"}
    tasks = build_advanced_tasks(profile, _path())
    project = next(task for task in tasks if task["kind"] == "project")

    assert "职责划分" in project["title"]
    assert "冲突消解" in project["title"], "必须跨节点，不能只围着最近一个节点"
    assert "你已经完成 2 个节点" in project["scenario"]
    assert "职责划分" in project["deliverables"][0]["label"]
    assert len(project["title"]) <= 42, "标题要能塞进卡片，别堆成一长串标签"


def test_project_task_falls_back_to_a_single_topic_without_completed_nodes():
    profile = {"identity": "工程师", "goal": "完成一个项目"}
    tasks = build_advanced_tasks(profile, _fresh_path())
    project = next(task for task in tasks if task["kind"] == "project")

    assert project["title"] == "围绕“多智能体调度”完成一段项目交付"


def test_completed_scope_unlocks_project_as_the_recommended_entry():
    """锚点变成"已完成的节点"之后的连带效果：有节点完成就会推荐 project。

    这是有意为之（10 个节点学完就该做项目了），不是副作用 —— 所以钉在这里，
    改判据的时候必须是有意识的。
    """
    profile = {"identity": "工程师", "goal": "完成一个项目"}
    tasks = build_advanced_tasks(profile, _path())

    recommended = next(task for task in tasks if task["is_recommended"])
    assert recommended["kind"] == "project"
    assert recommended["status"] == "active"


def test_low_evidence_learner_still_gets_case_first():
    """一个节点都没完成时不能直接推 project —— 原来的保守门槛要保住。"""
    profile = {"identity": "工程师", "goal": "完成一个项目"}
    tasks = build_advanced_tasks(profile, _fresh_path())

    recommended = next(task for task in tasks if task["is_recommended"])
    assert recommended["kind"] == "case"


def test_compact_tag_list_stays_within_the_budget():
    tags = ["课程目标与知识地图概览", "LangChain编排部署模块划分", "学习路径先修关系"]

    compact = _compact_tag_list(tags, "兜底")

    assert len(compact) <= 34
    assert compact == "课程目标与知识地图概览、LangChain编排部署模块划分"
    assert _compact_tag_list([], "兜底") == "兜底"
    # 单个标签就超预算时也要给出来，不能返回空
    assert _compact_tag_list(["超" * 50], "兜底") == "超" * 50


def test_advanced_tasks_unlock_only_after_ten_completed_nodes():
    assert advanced_milestone(0) == 0
    assert advanced_milestone(9) == 0
    assert advanced_milestone(10) == 1
    assert advanced_milestone(19) == 1
    assert advanced_milestone(20) == 2

    completed, total = completed_node_count({"nodes": [{"status": "completed"}, {"status": "in_progress"}]})
    assert (completed, total) == (1, 2)


def test_agent_cannot_bypass_server_owned_progression_gate():
    profile = {"identity": "学生", "direction": "多智能体协同决策", "goal": "完成一个项目"}
    # 用"一个节点都没完成"的路径：服务端选 case，智能体要 project 也不给
    fallback = build_advanced_tasks(profile, _fresh_path())
    normalised = _normalise_agent_tasks(
        {
            "recommended_kind": "project",
            "tasks": [{"kind": "case"}, {"kind": "transfer"}, {"kind": "project"}],
        },
        fallback,
    )

    assert normalised is not None
    tasks, _ = normalised
    assert next(task for task in tasks if task["is_recommended"])["kind"] == "case"


def test_agent_text_cannot_replace_the_server_owned_scope_context():
    """智能体只覆盖文案，锚点/范围这些服务端字段要原样保留。"""
    profile = {"identity": "学生", "goal": "完成一个项目"}
    fallback = build_advanced_tasks(profile, _path())
    normalised = _normalise_agent_tasks(
        {
            "tasks": [{"kind": "case"}, {"kind": "transfer"}, {"kind": "project"}],
        },
        fallback,
    )

    assert normalised is not None
    tasks, _ = normalised
    for task in tasks:
        assert task["context"]["completed_scope_label"] == "已完成 2 / 3 个节点"
        assert task["workspace"] == {"path_id": 12, "node_id": 2}


# ── 快照调度决策 ──────────────────────────────────────

def test_snapshot_action_serves_a_finished_agent_snapshot():
    assert _snapshot_action("agent", job_running=False, age_seconds=0) == "serve"
    assert _snapshot_action("agent", job_running=True, age_seconds=0) == "serve"


def test_snapshot_action_waits_while_a_job_is_running():
    assert _snapshot_action("pending", job_running=True, age_seconds=0) == "serve"


def test_snapshot_action_restarts_an_orphaned_pending_row():
    """作业注册表是进程内的：重启后 pending 行没人接手，页面会永远停在"生成中"。"""
    assert _snapshot_action("pending", job_running=False, age_seconds=1) == "generate"


def test_snapshot_action_only_retries_a_fallback_row_after_the_cooldown():
    assert _snapshot_action("fallback", job_running=False, age_seconds=10) == "serve"
    assert _snapshot_action("fallback", job_running=False, age_seconds=ADVANCED_FALLBACK_RETRY_SECONDS) == "generate"
    # 年龄未知（没有时间戳）时按"够旧了"处理，宁可重试也别把兜底冻住
    assert _snapshot_action("fallback", job_running=False, age_seconds=float("inf")) == "generate"


def test_snapshot_action_generates_when_there_is_no_row_at_all():
    assert _snapshot_action(None, job_running=False, age_seconds=float("inf")) == "generate"


# ── 失败留痕 ──────────────────────────────────────────

def test_failure_detail_keeps_the_cause_but_strips_credentials():
    """只记异常类型正是这次排查卡住的原因；但原始消息里可能带 key，必须脱敏。"""
    assert _describe_failure(TimeoutError()) == "TimeoutError"

    detail = _describe_failure(RuntimeError("401 invalid api_key=sk-abcdef123456 Bearer eyJhbGciOiJIUzI1NiJ9xx"))
    assert detail.startswith("RuntimeError: ")
    assert "sk-abcdef123456" not in detail
    assert "eyJhbGciOiJIUzI1NiJ9xx" not in detail
    assert "401 invalid" in detail, "非凭据部分要留着，否则还是查不出来"


def test_failure_detail_is_truncated_so_one_bad_response_cannot_flood_the_log():
    detail = _describe_failure(RuntimeError("错" * 500))

    assert len(detail) <= len("RuntimeError: ") + 160


def test_redact_leaves_ordinary_text_alone():
    assert _redact("文档包含省略或待补充占位语") == "文档包含省略或待补充占位语"
    assert _redact(None) == ""
