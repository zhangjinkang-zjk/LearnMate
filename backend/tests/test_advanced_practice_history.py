# -*- coding: utf-8 -*-
"""做过、但当前任务列表里已经没有它位置的实践记录。

任务 id 是 `path-{path_id}-node-{PathNode.id}-{kind}` —— **锚点节点写在 id 里**，
而锚点是"最近完成的节点"。用户完成下一个节点，锚点就换名字，快照按里程碑重建后
老会话再也挂不回任何任务上。库里实测有 `status="active"` 的会话，也就是用户还能
接着做的东西；就这么从界面上消失等于把用户的工作藏起来。

`_attach_practice_status` 因此把认领不上的单独返回，页面上以"历史实践"列出。

**不按 kind 硬套到同名任务上**：那样用户会看到自己没做过的任务标着"已完成"，
比看不到更糟。
"""

from types import SimpleNamespace

import pytest

import backend.src.models.advanced_practice_model as practice_model
from backend.src.service.advanced.service import _attach_practice_status


class _Session:
    def __init__(self, task_key, **kwargs):
        self.session_key = kwargs.get("session_key", f"key-{task_key}")
        self.task_key = task_key
        self.status = kwargs.get("status", "active")
        self.task_snapshot = kwargs.get("task_snapshot", {"title": f"做过的 {task_key}"})
        stamp = kwargs.get("updated_at")
        self.updated_at = SimpleNamespace(isoformat=lambda value=stamp: value) if stamp else None


class _Query:
    def __init__(self, sessions):
        self._sessions = sessions

    def order_by(self, *args):
        return self

    async def all(self):
        return self._sessions


def _install(monkeypatch, sessions):
    monkeypatch.setattr(
        practice_model,
        "AdvancedPracticeSession",
        SimpleNamespace(filter=lambda **kwargs: _Query(sessions)),
    )


def _task(task_id):
    return {"id": task_id, "title": f"当前任务 {task_id}"}


async def _attach(monkeypatch, sessions, tasks):
    _install(monkeypatch, sessions)
    return await _attach_practice_status(1, 48, tasks)


@pytest.mark.asyncio
async def test_a_matching_session_is_attached_to_its_task(monkeypatch):
    session = _Session("path-48-node-659", status="completed")
    tasks = [_task("path-48-node-659")]

    history = await _attach(monkeypatch, [session], tasks)

    assert tasks[0]["practice_status"] == "completed"
    assert tasks[0]["practice_status_label"] == "已完成"
    assert tasks[0]["practice_session_id"] == session.session_key
    assert history == [], "认领上了就不该再出现在历史里"


@pytest.mark.asyncio
async def test_a_session_no_task_claims_becomes_history(monkeypatch):
    session = _Session("path-48-node-650-transfer", status="completed")
    tasks = [_task("path-48-node-659-project")]

    history = await _attach(monkeypatch, [session], tasks)

    assert "practice_status" not in tasks[0], "没认领的任务不该被硬套上状态"
    assert history == [{
        "session_id": session.session_key,
        "task_key": "path-48-node-650-transfer",
        "task_title": "做过的 path-48-node-650-transfer",
        "status": "completed",
        "status_label": "已完成",
        "updated_at": None,
    }]


@pytest.mark.asyncio
async def test_an_orphan_is_not_force_matched_onto_the_same_kind_task(monkeypatch):
    """锚点换名字之后，**同一个 kind** 的老会话是最容易被硬套上去的
    （`path-48-node-650-project` → `path-48-node-659-project`）。

    套上去的后果是用户看到自己从没做过的任务标着"已完成" —— 比看不到更糟。
    所以认领只认 task_key 精确匹配。
    """
    session = _Session("path-48-node-650-project", status="completed")
    tasks = [_task("path-48-node-659-project")]

    history = await _attach(monkeypatch, [session], tasks)

    assert "practice_status" not in tasks[0], "同 kind 不等于同一个任务"
    assert [item["task_key"] for item in history] == ["path-48-node-650-project"]


@pytest.mark.asyncio
async def test_history_keeps_an_unfinished_session_visible(monkeypatch):
    """active 是用户还能接着做的 —— 它从界面上消失是最糟的一种。"""
    history = await _attach(
        monkeypatch, [_Session("path-48-node-650", status="active")], [_task("path-48-node-659")]
    )

    assert history[0]["status_label"] == "进行中"


@pytest.mark.asyncio
async def test_history_is_newest_first(monkeypatch):
    sessions = [
        _Session("old", updated_at="2026-09-01T00:00:00"),
        _Session("new", updated_at="2026-09-16T00:00:00"),
    ]

    history = await _attach(monkeypatch, sessions, [_task("path-48-node-659")])

    assert [item["task_key"] for item in history] == ["new", "old"]


@pytest.mark.asyncio
async def test_history_is_capped(monkeypatch):
    history = await _attach(
        monkeypatch, [_Session(f"t{index}") for index in range(20)], [_task("path-48-node-659")]
    )

    assert len(history) == 6


@pytest.mark.asyncio
async def test_only_the_latest_session_per_task_key_shows_up(monkeypatch):
    sessions = [
        _Session("same", session_key="latest", updated_at="2026-09-16T00:00:00"),
        _Session("same", session_key="older", updated_at="2026-09-01T00:00:00"),
    ]

    history = await _attach(monkeypatch, sessions, [_task("path-48-node-659")])

    assert [item["session_id"] for item in history] == ["latest"]


@pytest.mark.asyncio
async def test_a_task_list_that_is_empty_returns_nothing_rather_than_everything(monkeypatch):
    """没有任务可挂的时候（比如路径没就绪），不该把全部历史当成"孤儿"倒出来。"""
    history = await _attach(monkeypatch, [_Session("anything")], [])

    assert history == []


@pytest.mark.asyncio
async def test_a_session_without_a_snapshot_title_gets_a_readable_fallback(monkeypatch):
    history = await _attach(
        monkeypatch, [_Session("orphan", task_snapshot={})], [_task("path-48-node-659")]
    )

    assert history[0]["task_title"] == "之前的实践任务"
