# -*- coding: utf-8 -*-
"""概览主行动卡的那份元信息（`recommendation.target`）。

概览页原来只拿到一个「当前节点标题」——学生看得见"学什么"，看不见"点下去要花什么代价"。
节点本身在 `get_current_path` 里已经把知识点、资料数、任务进度都算好了，这里只是把它压成
主行动卡要的七个字段。

**一个数都不新算**，所以测试重点全在"缺数据时别编"：
- 没有 `knowledge_tags` / 不是 list → 0（不是 `len(str)`，那会把一个字符串数成字数）；
- 没有 `garden_progress` → 0，且不抛异常；
- 负数 / 脏值 → 0。
"""

import pytest

from backend.src.service.study.service import (
    _build_focus_target,
    _build_path_summaries,
    _build_recommendation_reason,
    _node_knowledge_tags,
    _non_negative_int,
)


def _node(**overrides):
    node = {
        "id": 102,
        "title": "召回结果排查",
        "action_label": "开始学习",
        "knowledge_tags": ["向量检索", "召回评估", "重排"],
        "garden_progress": {
            "resource_total": 4,
            "resource_completed": 2,
            "quiz_total": 1,
            "quiz_answered": 0,
            "completed_tasks": 2,
            "total_tasks": 5,
        },
    }
    node.update(overrides)
    return node


def test_a_full_node_maps_to_the_card_metadata():
    target = _build_focus_target(_node())

    assert target == {
        "id": 102,
        "title": "召回结果排查",
        "action_label": "开始学习",
        "knowledge_points": 3,
        "knowledge_tags": ["向量检索", "召回评估", "重排"],
        "resources": 4,
        "resources_done": 2,
        "quiz_total": 1,
        "quiz_answered": 0,
        "time_spent_seconds": 0,
    }


def test_the_derived_task_counters_are_not_republished():
    """`garden_progress.completed_tasks` / `total_tasks` 是**派生计数**：
    `total = 资料数 + (有测验 ? 1 : 0)`，`completed = 已读资料数 + (测验全答完 ? 1 : 0)`。
    曾经把它透出成 `tasks_done` / `tasks_total`，概览页照着渲染出「任务 2 / 5 个」这一行 ——
    而那个数只是上面两行的和，学生找不到"任务"是什么。已删除，这里钉住别再回来。
    （`garden_progress` 那对字段本身没动，`StudyGarden` / `TreeReviewScene` 还在用。）"""
    target = _build_focus_target(_node())

    assert "tasks_done" not in target
    assert "tasks_total" not in target


@pytest.mark.parametrize("node", [None, {}, {"id": 1}, {"title": "   "}, "不是字典"])
def test_without_a_usable_node_there_is_no_target(node):
    """没有当前节点时给 None —— 页面据此不画主行动卡，而不是画一张空卡。"""
    assert _build_focus_target(node) is None


def test_missing_progress_counts_as_zero_and_does_not_raise():
    target = _build_focus_target({"id": 7, "title": "文档切分"})

    assert target["resources"] == 0
    assert target["resources_done"] == 0
    assert target["quiz_total"] == 0
    assert target["quiz_answered"] == 0


@pytest.mark.parametrize("progress", [None, [], "4", 4])
def test_a_progress_value_of_the_wrong_type_is_ignored(progress):
    """`garden_progress` 只在它是 dict 时才算数 —— 别在字符串上 .get()。"""
    target = _build_focus_target(_node(garden_progress=progress))

    assert target["resources"] == 0
    assert target["quiz_total"] == 0


def test_a_string_of_tags_is_not_counted_by_its_length():
    """`knowledge_tags` 是字符串时给 0，不是 `len("向量检索")` == 4。

    `json.loads` 失败或数据库里存了裸串时会出现这种形状 —— 按长度数出来的
    "4 个知识点"是凭空多出来的。
    """
    target = _build_focus_target(_node(knowledge_tags="向量检索"))

    assert target["knowledge_points"] == 0


def test_the_tag_names_ride_along_with_the_count():
    """卡片上要写的是「这一章讲什么」，所以标签名本身必须带出来，不只是个数。"""
    target = _build_focus_target(_node())

    assert target["knowledge_tags"] == ["向量检索", "召回评估", "重排"]
    assert target["knowledge_points"] == len(target["knowledge_tags"])


@pytest.mark.parametrize("value", [None, "向量检索", 3, {"a": 1}])
def test_a_non_list_of_tags_yields_no_names_and_no_count(value):
    """`knowledge_tags` 不是数组时，名字和计数**一起**归零 —— 不能名字空着、计数还在。"""
    target = _build_focus_target(_node(knowledge_tags=value))

    assert target["knowledge_tags"] == []
    assert target["knowledge_points"] == 0


def test_blank_tags_are_dropped_instead_of_becoming_empty_chips():
    """空白标签会在卡片上渲染成一枚空的小圆角块 —— 直接丢掉。"""
    tags = _node_knowledge_tags({"knowledge_tags": ["向量检索", "  ", "", None, "重排"]})

    assert tags == ["向量检索", "重排"]


def test_the_action_label_has_a_default():
    """节点没给 action_label 时用「开始学习」，按钮上不会出现 None。"""
    target = _build_focus_target(_node(action_label=""))

    assert target["action_label"] == "开始学习"


@pytest.mark.parametrize(
    "value,expected",
    [(3, 3), ("4", 4), (None, 0), ("", 0), (-2, 0), ("abc", 0), (2.9, 2)],
)
def test_non_negative_int_never_produces_a_negative_or_a_crash(value, expected):
    assert _non_negative_int(value) == expected


# ── 「为什么是它」 ────────────────────────────────────────────────
# 实测（learner_llm_agent，2026-10-01）：这个账号已经学完 11/13 个节点，但 `blind_spots`
# 是空的（没有能路由到当前路径章节的薄弱标签），于是页面上的「为什么是它」写的是
# 「完成一次学习节点后，系统才能给出更精确的下一步判断」—— 和同一屏上的
# 「已完成 11 / 共 13 个节点」直接打架。下面这几条钉的就是这个洞。

def test_a_weak_point_covered_by_this_node_is_the_strongest_evidence():
    reason = _build_recommendation_reason(
        "向量检索", 44, "召回结果排查",
        completed_nodes=3, total_nodes=8, node_tags=["向量检索", "召回结果排查"],
    )

    assert "向量检索" in reason
    assert "44%" in reason


def test_a_weak_point_from_another_chapter_does_not_hijack_the_reason():
    """**核心回归：理由说去 A、按钮带你去 B。**

    `target_id` 永远是 `current_node`（路径上的下一站），和薄弱点在哪个章节没关系。
    所以那句"先补强 X"只有 X 确实属于这一站时才成立；不属于就老实讲路径进度 ——
    薄弱点自己还有右下角「这章有 N 个知识点该复习」那条带 `node_id` 的入口。
    """
    reason = _build_recommendation_reason(
        "向量检索", 44, "召回结果排查",
        completed_nodes=11, total_nodes=13, node_tags=["提示词工程"],
    )

    assert reason == "路径上已完成 11 / 13 个节点，这是下一个待学节点。"
    assert "向量检索" not in reason


def test_the_node_tag_match_ignores_case_and_spacing():
    """匹配走 `_knowledge_tag_key`，和 `blind_spots` 那套路由规则同一份 —— 不能各写一套。"""
    reason = _build_recommendation_reason(
        " Vector   Search ", 30, "召回结果排查",
        completed_nodes=1, total_nodes=4, node_tags=["vector search"],
    )

    assert "先补强" in reason


def test_a_weak_point_without_an_accuracy_does_not_print_none():
    """没有正确率时也不能写出「正确率约 0%」或「None%」—— 那是把缺失说成一个数。"""
    reason = _build_recommendation_reason(
        "向量检索", None, "召回结果排查",
        completed_nodes=0, total_nodes=0, node_tags=["向量检索"],
    )

    assert "向量检索" in reason
    assert "%" not in reason


def test_progress_is_the_reason_when_there_is_no_weak_point():
    """核心回归：没有薄弱点、但有当前节点时，理由说的是"它是路径上的下一个"。"""
    reason = _build_recommendation_reason("", None, "召回结果排查", completed_nodes=11, total_nodes=13)

    assert reason == "路径上已完成 11 / 13 个节点，这是下一个待学节点。"
    assert "才能给出更精确的下一步判断" not in reason


def test_without_totals_it_still_says_it_is_the_next_node():
    reason = _build_recommendation_reason("", None, "召回结果排查", completed_nodes=0, total_nodes=0)

    assert "下一个待学节点" in reason
    assert "0 / 0" not in reason


def test_only_when_there_is_nothing_at_all_does_it_admit_it_cannot_tell():
    """没有薄弱点、也没有当前节点（路径学完 / 还没生成）时，才用"数据不足"那句。"""
    assert _build_recommendation_reason("", None, "", completed_nodes=13, total_nodes=13) == (
        "完成一次学习节点后，系统才能给出更精确的下一步判断。"
    )


def test_blank_inputs_are_not_treated_as_evidence():
    """空白字符串不是证据 —— `"  "` 也要走"判断不了"那一支，不能在页面上留一行空理由。"""
    assert _build_recommendation_reason("  ", None, "   ", completed_nodes=3, total_nodes=8) == (
        "完成一次学习节点后，系统才能给出更精确的下一步判断。"
    )


# ── 右栏「我的学习方向」（每条路径一行） ────────────────────────────
# `_build_path_summaries` 要调 `PathService.get_current_path`（函数内局部 import），
# 所以补丁必须打在**源模块**上，不是打在这个模块的同名属性上。

class _FakePathService:
    def __init__(self, by_path):
        self.by_path = by_path
        self.calls = []

    async def get_current_path(self, user_id, path_id=None):
        self.calls.append(path_id)
        return self.by_path.get(path_id)


def _patch_path_service(monkeypatch, by_path):
    from backend.src.service.path import service as path_service

    fake = _FakePathService(by_path)
    monkeypatch.setattr(path_service, "PathService", fake)
    return fake


def _path_stats(*items):
    return {"paths": [
        {"path_id": pid, "subject": name, "progress": {"percentage": pct, "completed_nodes": done, "total_nodes": total}}
        for pid, name, pct, done, total in items
    ]}


def _path_node(node_id, status, title="节点"):
    return {"id": node_id, "title": title, "status": status}


def _statuses(summary):
    """右栏那一行现在给的是整份节点（id + 标题 + 状态），测试关心状态时只看状态。"""
    return [node["status"] for node in summary["nodes"]]


@pytest.mark.asyncio
async def test_the_current_path_is_not_fetched_twice(monkeypatch):
    """核心回归：当前那条复用已经取到的 `current_path`，不再多跑一次路径读。

    `get_current_path` 里面带一次状态修复（会写库），一个只读聚合接口不该为同一条路径
    跑两遍。
    """
    fake = _patch_path_service(monkeypatch, {})
    current_path = {"path_id": 106, "nodes": [_path_node(1, "completed"), _path_node(2, "in_progress")]}

    summaries = await _build_path_summaries(
        9, _path_stats((106, "大语言模型原理与微调", 85, 11, 13)), current_path=current_path,
    )

    assert fake.calls == [], f"当前路径不该被再查一次：{fake.calls}"
    assert _statuses(summaries[0]) == ["completed", "in_progress"]


@pytest.mark.asyncio
async def test_every_stop_carries_its_id_and_title(monkeypatch):
    """核心：页面上的每一站要能点进对应节点的学习界面，所以 id 必须带出来。

    原来这里给的是一串状态字符串（`node_statuses`），页面只能画出一个个彩色方块，
    点不动 —— 没有 id 就没法跳转。
    """
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9, _path_stats((106, "主干", 85, 1, 3)),
        current_path={"path_id": 106, "nodes": [
            _path_node(1, "completed", "召回结果排查"),
            _path_node(2, "in_progress", "重排策略"),
            _path_node(3, "locked", "线上灰度"),
        ]},
    )

    assert summaries[0]["nodes"] == [
        {"id": 1, "title": "召回结果排查", "status": "completed"},
        {"id": 2, "title": "重排策略", "status": "in_progress"},
        {"id": 3, "title": "线上灰度", "status": "locked"},
    ]


@pytest.mark.asyncio
async def test_a_node_without_a_status_counts_as_locked(monkeypatch):
    """状态缺失时按 locked 画 —— 不能因为字段没给就让页面出现一个能点的"可学"站点。"""
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9, _path_stats((106, "主干", 0, 0, 1)),
        current_path={"path_id": 106, "nodes": [{"id": 7, "title": "x"}]},
    )

    assert summaries[0]["nodes"][0]["status"] == "locked"


@pytest.mark.asyncio
async def test_other_paths_are_fetched_by_path_id(monkeypatch):
    fake = _patch_path_service(monkeypatch, {95: {"nodes": [_path_node(7, "locked")]}})

    summaries = await _build_path_summaries(
        9, _path_stats((106, "主干", 85, 11, 13), (95, "辅助", 43, 10, 23)),
        current_path={"path_id": 106, "nodes": [_path_node(1, "completed")]},
    )

    assert fake.calls == [95]
    by_id = {item["id"]: item for item in summaries}
    assert _statuses(by_id[95]) == ["locked"]


@pytest.mark.asyncio
async def test_current_path_first_then_by_progress(monkeypatch):
    """右栏从上往下就是阅读顺序：当前那条永远第一个，其余按完成度降序。"""
    _patch_path_service(monkeypatch, {
        95: {"nodes": [_path_node(7, "unlocked")]},
        102: {"nodes": [_path_node(8, "unlocked")]},
    })

    summaries = await _build_path_summaries(
        9,
        _path_stats((95, "低的", 43, 10, 23), (102, "高的", 83, 10, 12), (106, "当前", 85, 11, 13)),
        current_path={"path_id": 106, "nodes": [_path_node(1, "completed")]},
    )

    assert [item["id"] for item in summaries] == [106, 102, 95]


@pytest.mark.asyncio
async def test_current_node_is_the_first_unlocked_or_in_progress(monkeypatch):
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9, _path_stats((106, "主干", 85, 11, 13)),
        current_path={"path_id": 106, "nodes": [
            _path_node(1, "completed"), _path_node(2, "completed"),
            _path_node(12, "in_progress", "智能体开发框架与MCP协议入门"), _path_node(13, "locked"),
        ]},
    )

    assert summaries[0]["current_node"] == {
        "id": 12, "title": "智能体开发框架与MCP协议入门", "status": "in_progress",
    }


@pytest.mark.asyncio
async def test_a_finished_path_has_no_current_path_node(monkeypatch):
    """全部完成的路径没有"当前节点" —— 给 None，不是硬塞最后一个节点。"""
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9, _path_stats((106, "主干", 100, 13, 13)),
        current_path={"path_id": 106, "nodes": [_path_node(1, "completed"), _path_node(2, "completed")]},
    )

    assert summaries[0]["current_node"] is None


@pytest.mark.asyncio
async def test_a_missing_status_defaults_to_locked(monkeypatch):
    """状态缺失时按 locked 画 —— 不能因为字段没给就让轨道上出现一个"可学"的假点。"""
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9, _path_stats((106, "主干", 0, 0, 2)),
        current_path={"path_id": 106, "nodes": [{"id": 1, "title": "x"}]},
    )

    assert _statuses(summaries[0]) == ["locked"]


@pytest.mark.asyncio
async def test_entries_without_a_name_or_id_are_skipped(monkeypatch):
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9, {"paths": [
            {"path_id": None, "subject": "无 id", "progress": {}},
            {"path_id": 5, "subject": "  ", "progress": {}},
            {"path_id": 6, "subject": "有用", "progress": {"percentage": 10, "completed_nodes": 1, "total_nodes": 9}},
        ]},
        current_path=None,
    )

    assert [item["id"] for item in summaries] == [6]


@pytest.mark.asyncio
async def test_total_nodes_falls_back_to_the_node_count(monkeypatch):
    """`progress.total_nodes` 缺了就数节点 —— 不能显示成 0/0。"""
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9, {"paths": [{"path_id": 6, "subject": "有用", "progress": {"percentage": 0}}]},
        current_path={"path_id": 6, "nodes": [_path_node(1, "unlocked"), _path_node(2, "locked"), _path_node(3, "locked")]},
    )

    assert summaries[0]["total_nodes"] == 3


# ── 「上次学到哪天」 ────────────────────────────────────────────────
# 取的是 `user_path_progress` 的 started_at / completed_at，不是 learning_events.path_id
# （那个字段是稀疏的：resource_read 压根不传 path_id，assessment 显式传 None）。
# 这里钉住两件事：传进来的日期原样落到对应那一行；没打开过的路径是 None，不是"今天"。


@pytest.mark.asyncio
async def test_each_path_carries_the_day_it_was_last_touched(monkeypatch):
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9,
        _path_stats((106, "甲", 85, 11, 13), (107, "乙", 40, 2, 5)),
        current_path={"path_id": 106, "nodes": [_path_node(1, "completed")]},
        last_active={106: "2026-09-29"},
    )

    assert [s["last_active_date"] for s in summaries] == ["2026-09-29", None]


@pytest.mark.asyncio
async def test_a_path_that_was_never_opened_has_no_last_active_date(monkeypatch):
    """**不能退回"今天"或空字符串** —— 页面据此显示"还没开始过"，两者都会被它读成来过。"""
    _patch_path_service(monkeypatch, {})

    summaries = await _build_path_summaries(
        9,
        _path_stats((106, "甲", 0, 0, 13)),
        current_path={"path_id": 106, "nodes": [_path_node(1, "unlocked")]},
    )

    assert summaries[0]["last_active_date"] is None
