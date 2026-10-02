# -*- coding: utf-8 -*-
"""进阶学习不再有"完成 N 个节点才准进"的封锁。

以前 `get_current` 在 `completed < unlock_nodes` 时直接返回 `status="locked"`，前端据此
把整页换成一句"先完成基础学习，再进入实践"。拦的是**入口** —— 学生可能只是想拿自己的
项目来问教练，却连工作区都打不开。

封锁去掉了，但**任务卡仍然只从已完成节点出**，这条没变也不能变：任务生成的提示词第一条
就写着"任务必须建立在学习者**已经完成的节点**上，不能提前考他还没学的内容"，第 21 条
更明确禁止围绕 `current_node` 出题。一个节点都没完成时，模型手上**没有任何知识标签
可用**，硬出题只能现编 —— 而"围绕未完成节点出题"正是当初修掉的 bug（见 `_focus_node`）。

所以口径是：**页面永远能进，任务卡该没有的时候就没有。** 这一条正是最容易改坏的
（"既然解封了那就顺手给出题吧"），所以下面单独钉住"没有已完成节点时**一次都不去问生成器**"。

仓库的测试不碰数据库，这里用替身顶掉三个查询。
"""

from types import SimpleNamespace

import pytest

from backend.src.models.exam_model import KnowledgeMastery
from backend.src.models.usermodel import User
from backend.src.service.advanced import service
from backend.src.service.path.service import PathService


class _AsyncValue:
    """Tortoise 的关联字段是 await 出来的，替身也得能 await。"""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _resolve():
            return self._value

        return _resolve().__await__()


class _Query:
    def __init__(self, rows):
        self._rows = rows

    async def first(self):
        return self._rows[0] if self._rows else None

    async def all(self):
        return self._rows


def _path(completed: int, total: int = 20):
    """`PathService.get_current_path` 的真实形态（见 test_page_context 里的同名替身）。"""
    return {
        "path_id": 48,
        "stage": "基础",
        "progress": 0,
        "current_node_id": 659,
        "goal": "智能体应用开发",
        "diagnosis": {"weak_points": []},
        "nodes": [
            {
                "id": 100 + index,
                "title": f"节点 {index + 1}",
                "status": "completed" if index < completed else "locked",
                "knowledge_tags": [f"标签{index + 1}"],
            }
            for index in range(total)
        ],
    }


def _stub(monkeypatch, path, generated: list[str] | None = None):
    """顶掉 get_current 需要的三个查询，并记下生成器有没有被调用。"""
    monkeypatch.setattr(User, "filter", lambda **kwargs: _Query([SimpleNamespace(picture=_AsyncValue(None))]))
    monkeypatch.setattr(KnowledgeMastery, "filter", lambda **kwargs: _Query([]))

    async def _current_path(user_id):
        return path

    monkeypatch.setattr(PathService, "get_current_path", _current_path)

    generated = generated if generated is not None else []

    async def _snapshot(user_id, path_id, milestone, profile, current_path, mastery, force=False):
        generated.append(milestone)
        return {
            "tasks": [{"id": "path-48-node-659-case", "kind": "case", "is_recommended": True, "status": "active"}],
            "summary": "本次里程碑任务已生成。",
            "source": "agent",
            "generated_at": None,
        }

    async def _attached(user_id, path_id, tasks):
        return []

    monkeypatch.setattr(service, "_get_or_create_snapshot", _snapshot)
    monkeypatch.setattr(service, "_attach_practice_status", _attached)
    return generated


# ── 封锁没了 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_student_with_no_completed_nodes_still_opens_the_page(monkeypatch):
    """一个基础节点都没完成，也要能进页面 —— 这是这次改动本身。

    返回的是 ready 而不是"错误"：页面是好的，只是这次没有任务卡可发，前端据此落进
    「无任务」，学生照样能打开工作区跟教练聊自己的项目。
    """
    _stub(monkeypatch, _path(completed=0))

    result = await service.AdvancedLearningService.get_current(7)

    assert result["status"] == "ready"
    assert result["tasks"] == []
    assert result["task"] is None
    # 路径信息照给：前端要靠 current_node_id 当「无任务」会话的锚点
    assert result["path"]["current_node_id"] == 659
    assert result["path"]["completed_nodes"] == 0


@pytest.mark.asyncio
async def test_no_tasks_are_invented_when_nothing_is_completed(monkeypatch):
    """**没有已完成节点时，一次都不去问生成器。**

    这条比"返回空列表"更重要：空列表可以是生成器被调用之后返回空，那就意味着已经把
    一份"没有依据"的请求发出去了。而提示词明确禁止围绕未完成节点出题 —— 与其让模型
    在两条互相矛盾的指令里挑一条，不如根本不问。
    """
    generated = _stub(monkeypatch, _path(completed=0))

    await service.AdvancedLearningService.get_current(7)

    assert generated == [], "没有已完成节点时不该调用任务生成"


@pytest.mark.asyncio
async def test_the_old_threshold_no_longer_locks_the_page(monkeypatch):
    """3 个已完成（旧门槛是 10）以前会拿到 locked，现在照样出任务。"""
    generated = _stub(monkeypatch, _path(completed=3))

    result = await service.AdvancedLearningService.get_current(7)

    assert result["status"] != "locked"
    assert result["tasks"], "已完成节点够生成依据了，就该照常发任务"
    # 0 就是第一个十节点批次。这条以前写的是 1，因为 get_current 把 0 抬成了 1 ——
    # 那个抬升会和 10～19 撞键，见下面那条用例。
    assert generated == [0], "3 个已完成属于第一批（0～9）"


@pytest.mark.asyncio
async def test_a_short_path_does_not_get_stuck_on_the_same_task_set(monkeypatch):
    """0～9 和 10～19 必须是两批任务，不能挤在同一个快照键上。

    这里原来有一句 `if milestone == 0: milestone = 1`，把"第一个十节点批次"抬成了 1；
    而 10～19 本来就返回 1 —— 于是 0～19 全落进同一个键。学生从第 1 个节点做到第 19 个
    节点，库里的行始终是同一行，拿到的始终是同一批题。四条真实路径长度是 11/12/16/21，
    其中三条连 20 都到不了，也就是这些学生**永远等不到第二次生成**。

    量的位置很关键：从 `get_current` 外面量（拿到的是真正去查库的那个键），而不是直接调
    `advanced_milestone`。折的是调用方 —— 那个函数一直老老实实返回 0，它自己的用例也一直
    是绿的（见 test_advanced_learning_service.py 的 mapping 用例），只有从这里才看得见。
    """
    at_five = _stub(monkeypatch, _path(completed=5, total=12))
    await service.AdvancedLearningService.get_current(7)

    at_twelve = _stub(monkeypatch, _path(completed=12, total=12))
    await service.AdvancedLearningService.get_current(7)

    assert at_five == [0], "0～9 个已完成属于第一批"
    assert at_twelve == [1], "同一个学生学到 10～19 个已完成时必须换一批任务"
    assert at_five != at_twelve, "两段进度必须落在不同的快照键上，否则学生拿不到新任务"


@pytest.mark.asyncio
async def test_no_path_is_still_not_ready(monkeypatch):
    """**这一条没被解封。** 会话账本按 (user, task_key, path, node) 分区，没有路径就没有
    可挂的节点，连「无任务」都开不出来 —— 所以缺路径还得说缺路径，而不是假装页面可用。"""
    _stub(monkeypatch, None)

    result = await service.AdvancedLearningService.get_current(7)

    assert result["status"] == "path_required"
    assert result["tasks"] == []


@pytest.mark.asyncio
async def test_the_milestone_payload_still_reports_progress(monkeypatch):
    """解封不等于把进度藏起来：这些数字仍然照实返回，只是不再拿来拦人。"""
    _stub(monkeypatch, _path(completed=4, total=20))

    result = await service.AdvancedLearningService.get_current(7)

    milestone = result["milestone"]
    assert milestone["completed_nodes"] == 4
    assert milestone["unlock_nodes"] == 10
    assert milestone["remaining"] == 6
