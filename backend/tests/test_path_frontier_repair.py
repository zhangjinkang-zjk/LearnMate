# -*- coding: utf-8 -*-
"""路径死锁：还有 locked 节点，却一个可学节点都没有。

这个状态用户是**真的走不动**：基础讲解没有当前节点可进，学习总览的"下一步"是空的
（而且以前会直接 500 —— `.get("next_action", {})` 的默认值对显式 None 不生效），
也没有任何接口能救回来：`unlock_next_node` 只在交卷时调用，交卷又要求节点已解锁。

来源是 `regenerate_path`：承接已完成 topic 用的是批量
`.update(node_status="completed")`，不解锁后面的节点；而新路径的 node 1 创建时本来是
`unlocked`，如果它的 topic 恰好也已完成就会被这次承接覆盖成 `completed`。

这里钉住"哪个节点该被补解锁"这条规则，以及自愈时只写状态、不预生成资料。
"""

from types import SimpleNamespace
import inspect

import pytest

from backend.src.service.path import helpers


class FakeQuery:
    """只实现 reconcile_unlocked_frontier 用到的那一个方法。"""

    def __init__(self, updates):
        self._updates = updates

    def filter(self, **kwargs):
        self._updates.append(kwargs)
        return self

    async def update(self, **fields):
        self._updates[-1] = {**self._updates[-1], **fields}
        return 1


def _install(monkeypatch):
    updates: list[dict] = []
    monkeypatch.setattr(helpers, "UserPathProgress", SimpleNamespace(filter=lambda **kw: FakeQuery(updates).filter(**kw)))
    return updates


def _record(node_id: int, status: str, order: int, *, path_id: int = 68, user_id: int = 1):
    node = SimpleNamespace(order_index=order)
    return SimpleNamespace(
        id=node_id * 10,
        node_id=node_id,
        node_status=status,
        node=node,
        quiz_passed=status == "completed",
        completed_at=None,
        path_id=path_id,
        user_id=user_id,
    )


def _dead_end() -> list:
    """10 个学完、8 个还锁着、一个可学的都没有 —— 库里 path 68 就是这个形状。"""
    return [
        *(_record(i, "completed", i) for i in range(1, 11)),
        *(_record(i, "locked", i) for i in range(11, 19)),
    ]


# ── 规则本身 ──────────────────────────────────────────

def test_a_healthy_path_needs_no_repair():
    records = [_record(1, "completed", 1), _record(2, "unlocked", 2), _record(3, "locked", 3)]

    assert helpers.frontier_node_id(records) is None


def test_in_progress_counts_as_studyable():
    records = [_record(1, "completed", 1), _record(2, "in_progress", 2), _record(3, "locked", 3)]

    assert helpers.frontier_node_id(records) is None


def test_a_dead_end_unlocks_the_lowest_order_unfinished_node():
    assert helpers.frontier_node_id(_dead_end()) == 11


def test_a_fully_completed_path_needs_no_repair():
    records = [_record(i, "completed", i) for i in range(1, 19)]

    assert helpers.frontier_node_id(records) is None


def test_an_empty_path_needs_no_repair():
    assert helpers.frontier_node_id([]) is None
    assert helpers.frontier_node_id(None) is None


def test_the_frontier_is_the_lowest_order_not_the_first_in_the_list():
    """传进来的顺序不保证有序，得按 order_index 找，不能取列表里第一个。"""
    records = [
        _record(11, "locked", 11),
        _record(5, "completed", 5),
        _record(12, "locked", 12),
    ]

    assert helpers.frontier_node_id(records) == 11

    # 顺序信息也可以由调用方显式给出（study 那边就是这么传的）
    explicit = [
        _record(11, "locked", 11),
        _record(12, "locked", 12),
    ]
    assert helpers.frontier_node_id(explicit, {11: 12, 12: 11}) == 12


def test_a_gap_in_the_middle_is_repaired_at_the_gap_not_the_tail():
    records = [_record(1, "locked", 1), _record(2, "locked", 2), _record(3, "completed", 3)]

    assert helpers.frontier_node_id(records) == 1


def test_the_frontier_is_never_a_completed_node():
    """`regenerate_path` 靠这条不变量把 frontier 的 order 反推给 `unlock_next_node`
    （传 order-1 让它解锁 order 那个）。只要这里永远不会返回已完成节点，补解锁就
    不可能把学完的节点退回 unlocked。"""
    shapes = [
        _dead_end(),
        [_record(1, "completed", 1), _record(2, "locked", 2)],
        [_record(1, "locked", 1), _record(2, "completed", 2)],
        [_record(3, "locked", 3), _record(1, "completed", 1), _record(2, "locked", 2)],
    ]

    for records in shapes:
        target = helpers.frontier_node_id(records)
        if target is not None:
            picked = next(record for record in records if record.node_id == target)
            assert picked.node_status != "completed", f"补解锁选中了已完成的节点 {target}"


# ── 自愈动作 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_repair_writes_only_the_frontier_status(monkeypatch):
    updates = _install(monkeypatch)

    repaired = await helpers.reconcile_unlocked_frontier(_dead_end())

    assert repaired == [11]
    assert updates == [{"user_id": 1, "path_id": 68, "node_id": 11, "node_status": "unlocked"}], (
        "只翻状态：不预生成资料、不碰别的节点"
    )


@pytest.mark.asyncio
async def test_repair_does_not_touch_a_healthy_path(monkeypatch):
    updates = _install(monkeypatch)

    repaired = await helpers.reconcile_unlocked_frontier(
        [_record(1, "completed", 1), _record(2, "unlocked", 2)]
    )

    assert repaired == []
    assert updates == [], "健康路径不该产生任何写操作"


@pytest.mark.asyncio
async def test_repair_leaves_a_finished_path_alone(monkeypatch):
    updates = _install(monkeypatch)

    repaired = await helpers.reconcile_unlocked_frontier([_record(i, "completed", i) for i in range(1, 4)])

    assert repaired == []
    assert updates == []


@pytest.mark.asyncio
async def test_repair_returns_ids_so_the_caller_can_refresh_its_snapshot(monkeypatch):
    """get_current_path 拿这个返回值把内存里那份 records 也改掉，否则同一次请求里
    后面读到的还是旧状态（current_node_id 仍然是 None）。"""
    _install(monkeypatch)
    records = _dead_end()

    repaired = await helpers.reconcile_unlocked_frontier(records)

    assert repaired == [11]
    assert next(r for r in records if r.node_id == 11).node_status == "locked", (
        "写库和改内存是两件事，内存那份由调用方按返回的 id 更新"
    )


# ── 前沿是怎么**长出来**的：出生状态 ─────────────────────────────────────────
# 修复只兜底；正常路径的前沿必须从一开始就是连续的。这两条钉住出生规则。


def test_only_the_first_station_is_unlocked_at_birth():
    """新建路径时，只有第 1 站是 unlocked，其余全是 locked。

    以前第 2 站起还有一条附加条件 ——"没有前置节点也算可学"。前置节点由路径生成模型
    给出，它漏给一个（执行器提示词原本写的是"第一个节点的 prerequisites 为空数组"，
    而它一次只看得到**本组**四个节点，于是每一组的组首都拿到空数组），那一站出生就
    直接放行。实测 Transformer 那条 18 站的路径，前沿断成「已完成 ×10 → 未解锁 ×5 →
    可开始 ×2 → 未解锁」，页面按「第 N / M 个节点」展示，路线图却画不出来。
    """
    assert [helpers.initial_node_status(i) for i in range(6)] == [
        "unlocked", "locked", "locked", "locked", "locked", "locked",
    ]


def test_initial_status_takes_only_a_position():
    """它只能看位置，看不到 `prerequisites` —— 签名本身就是那条约束的守卫。

    出生条件一旦重新变回"看前置决定"，散开的前沿就会跟着回来：`prerequisites` 是路径
    生成模型给的自由文本，不是可以信赖的门禁依据。
    """
    assert list(inspect.signature(helpers.initial_node_status).parameters) == ["position"]
