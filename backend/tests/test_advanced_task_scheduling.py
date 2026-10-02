# -*- coding: utf-8 -*-
"""进阶任务快照的调度：什么时候直接返回、什么时候该起一个后台生成。

这一段以前是同步跑在请求里的，于是"超时 → 兜底 → 兜底被永久缓存"三件事连在一起：
库里留下的是 09-04 一次 agent、之后 12 天全是 fallback，智能体恢复了也不会重算。
现在生成在后台跑，请求只负责读快照和决定要不要起作业 —— 决策逻辑全部在这里钉住。

这个仓库的测试不碰数据库（没有 DB fixture），所以用一个内存替身顶掉
`AdvancedTaskSnapshot`，用假函数顶掉作业注册表。
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.src.models import advanced_task_model
from backend.src.service.advanced import service, task_jobs


# ── 内存替身：只实现 _get_or_create_snapshot 真正用到的那几个方法 ──

class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.created_at = kwargs.get("created_at") or datetime.now(timezone.utc)
        self.updated_at = kwargs.get("updated_at") or self.created_at


class _Query:
    def __init__(self, model, rows):
        self._model = model
        self._rows = rows

    async def first(self):
        return self._rows[0] if self._rows else None

    def exclude(self, **kwargs):
        self._rows = [
            row for row in self._rows
            if not all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]
        return self

    async def delete(self):
        doomed = {id(row) for row in self._rows}
        self._model.rows = [row for row in self._model.rows if id(row) not in doomed]
        return len(doomed)

    async def update(self, **kwargs):
        for row in self._rows:
            row.__dict__.update(kwargs)
        return len(self._rows)


class _FakeSnapshotModel:
    rows: list = []
    created: list = []

    @classmethod
    def reset(cls):
        cls.rows = []
        cls.created = []

    @classmethod
    def filter(cls, **kwargs):
        return _Query(cls, [
            row for row in cls.rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ])

    @classmethod
    async def create(cls, **kwargs):
        row = _Row(**kwargs)
        cls.rows.append(row)
        cls.created.append(kwargs)
        return row


# ── 夹具 ──────────────────────────────────────────────

PROFILE = {"identity": "在校大学生", "direction": "数据结构与算法", "goal": "完成一个项目"}
PATH = {
    "path_id": 68,
    "goal": "数据结构与算法",
    "current_node_id": 3,
    "nodes": [
        {"id": 1, "title": "智能体基础", "status": "completed", "knowledge_tags": ["职责划分"]},
        {"id": 2, "title": "协同冲突处理", "status": "completed", "knowledge_tags": ["冲突消解"]},
        {"id": 3, "title": "多智能体调度", "status": "locked", "knowledge_tags": ["调度策略"]},
    ],
    "diagnosis": {"weak_points": []},
}

# 同一个学生，在快照生成**之后**又学完了一个节点（已完成 2 → 3）。
# 任务照的是"生成那一刻的已完成节点"出的题，进度一动手上这份就滞后了。
PROGRESSED_PATH = {
    **PATH,
    "nodes": PATH["nodes"] + [{"id": 4, "title": "工具调用", "status": "completed", "knowledge_tags": ["工具调用"]}],
}


class _Jobs:
    """假作业注册表：记录谁被起过、并且可以假装"有个作业正在跑"。"""

    def __init__(self, running=False):
        self.running = running
        self.started: list[tuple] = []
        self.producers: list = []

    def install(self, monkeypatch):
        async def ensure(user_id, path_id, milestone, producer):
            self.started.append((user_id, path_id, milestone))
            self.producers.append(producer)
            return SimpleNamespace(), True

        monkeypatch.setattr(task_jobs, "ensure_task_job", ensure)
        monkeypatch.setattr(task_jobs, "is_generating", lambda *args: self.running)
        return self


@pytest.fixture
def snapshots(monkeypatch):
    _FakeSnapshotModel.reset()
    monkeypatch.setattr(advanced_task_model, "AdvancedTaskSnapshot", _FakeSnapshotModel)
    return _FakeSnapshotModel


def _seed(**kwargs):
    defaults = dict(
        user_id=1,
        path_id=68,
        milestone=1,
        completed_nodes=2,
        current_node_id=3,
        task_json={"tasks": [{"id": "t", "kind": "case"}], "summary": "旧的"},
        source="agent",
        generation_error=None,
    )
    defaults.update(kwargs)
    row = _Row(**defaults)
    _FakeSnapshotModel.rows.append(row)
    return row


async def _load(path=None):
    return await service._get_or_create_snapshot(1, 68, 1, PROFILE, path if path is not None else PATH, [])


# ── 首次访问：立刻返回，生成放后台 ────────────────────

@pytest.mark.asyncio
async def test_first_visit_returns_a_provisional_set_and_starts_generation(snapshots, monkeypatch):
    jobs = _Jobs().install(monkeypatch)

    result = await _load()

    assert result["source"] == "pending"
    assert len(result["tasks"]) == 3, "不能返回空任务，页面得能渲染"
    assert "正在按你已完成的节点生成" in result["summary"], "文案要说清这是临时的"
    assert jobs.started == [(1, 68, 1)]
    # 锚点落在已完成的节点上，而不是那个 locked 的 current_node
    assert result["tasks"][0]["workspace"]["node_id"] == 2


@pytest.mark.asyncio
async def test_pending_row_is_served_while_its_job_is_still_running(snapshots, monkeypatch):
    _seed(source="pending", task_json={"tasks": [{"id": "t"}], "summary": service._PENDING_SUMMARY})
    jobs = _Jobs(running=True).install(monkeypatch)

    result = await _load()

    assert result["source"] == "pending"
    assert jobs.started == [], "已经在跑了，不该再起一个"


@pytest.mark.asyncio
async def test_orphaned_pending_row_restarts_generation(snapshots, monkeypatch):
    """作业注册表是进程内的：重启之后 pending 行没人接手，会永远停在"生成中"。"""
    _seed(source="pending")
    jobs = _Jobs(running=False).install(monkeypatch)

    result = await _load()

    assert result["source"] == "pending"
    assert jobs.started == [(1, 68, 1)], "陈旧 pending 必须被接手"


# ── 已生成 / 兜底 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_snapshot_is_served_without_regenerating(snapshots, monkeypatch):
    _seed(source="agent")
    jobs = _Jobs().install(monkeypatch)

    result = await _load()

    assert result["source"] == "agent"
    assert jobs.started == []
    assert snapshots.created == [], "已经有结果了不该再建行"


@pytest.mark.asyncio
async def test_fresh_fallback_is_served_without_spending_another_attempt(snapshots, monkeypatch):
    """刚失败过的兜底不该每次进页面都重打一发 —— 那会把页面变成生成请求放大器。"""
    _seed(source="fallback", updated_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    jobs = _Jobs().install(monkeypatch)

    result = await _load()

    assert result["source"] == "fallback"
    assert jobs.started == []


@pytest.mark.asyncio
async def test_stale_fallback_is_retried_instead_of_staying_frozen(snapshots, monkeypatch):
    """这条就是"12 天全是 fallback"那个 bug 的回归测试。"""
    _seed(source="fallback", updated_at=datetime.now(timezone.utc) - timedelta(seconds=600))
    jobs = _Jobs().install(monkeypatch)

    result = await _load()

    assert result["source"] == "fallback", "重试期间先给用户看现有内容"
    assert jobs.started == [(1, 68, 1)]


# ── 进度变了：agent 的结果也会过期 ────────────────────

@pytest.mark.asyncio
async def test_progress_moves_the_agent_snapshot_forward(snapshots, monkeypatch):
    """学生又学完一个节点，手上那份任务就得跟着重算。

    这条以前是不成立的：`agent` 分支无条件 `serve`，任务只在**跨过里程碑边界**（10 的
    整数倍）时才重算。0～19 又因为 `get_current` 里那句 `milestone == 0 → 1` 挤在同一个
    键上，所以实际上学生从第 1 个节点做到第 19 个节点，题目一次都不变。真实路径长度是
    11/12/16/21，三条连 20 都到不了 —— 永远等不到第二次生成。
    """
    _seed(source="agent", updated_at=datetime.now(timezone.utc) - timedelta(seconds=600))
    jobs = _Jobs().install(monkeypatch)

    result = await _load(PROGRESSED_PATH)

    assert result["tasks"] == [{"id": "t", "kind": "case"}], "重算期间先端出已有的任务，不能让页面空一下"
    assert result["source"] == "pending", "状态要如实说'正在生成'，否则前端不会轮询到新结果"
    assert jobs.started == [(1, 68, 1)]
    assert snapshots.created == [], "同一行上原地重算，不换键也不新建行"


@pytest.mark.asyncio
async def test_a_running_refresh_keeps_reporting_pending_so_the_page_keeps_polling(snapshots, monkeypatch):
    """重算跑着的时候必须**一直**报 pending。

    前端 `schedulePoll` 在 `task_source !== 'pending'` 时不轮询 —— 只在起作业的那一次报
    pending 的话，轮询在第二跳就断了，新任务要等学生下一次手动刷页面才出现，等于这个修复
    没生效。这条也是 `_mark_refresh_in_flight` 在 "serve" 那条早返回路径上的用例。
    """
    _seed(source="agent", updated_at=datetime.now(timezone.utc) - timedelta(seconds=600))
    jobs = _Jobs(running=True).install(monkeypatch)

    result = await _load(PROGRESSED_PATH)

    assert result["source"] == "pending"
    assert jobs.started == [], "已经在跑了，不该再起一个"


@pytest.mark.asyncio
async def test_a_just_refreshed_snapshot_is_not_refreshed_again(snapshots, monkeypatch):
    """刚算过的（或者刚算失败的）不该马上再算一遍。

    这不是保守，是必需的：重算失败时 `_run_agent_generation` 会保住原有的 agent 结果，
    `completed_nodes` 仍然对不上进度，"进度变了"这个条件会一直为真 —— 而重算在跑的那段
    时间前端每 3 秒轮询一次。没有冷却，一次失败就变成每 3 秒一发、永远不停。
    """
    _seed(source="agent", updated_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    jobs = _Jobs().install(monkeypatch)

    result = await _load(PROGRESSED_PATH)

    assert jobs.started == [], "冷却期内不重算"
    # 被冷却挡下来的时候**不能**报 pending：什么都没在生成，而那个徽标不会自己消失。
    assert result["source"] == "agent"


@pytest.mark.asyncio
async def test_a_failed_refresh_does_not_become_a_request_amplifier(snapshots, monkeypatch):
    """失败的重算也必须把冷却重新起算 —— 靠的是作业体把 `updated_at` 推到现在。

    上面那条量的是"刚生成完"，这条走完整条失败链路：起作业 → 作业失败 → 再进页面。
    要求第二次进来是 `serve`。`_run_agent_generation` 里那个显式的 `updated_at` 就是
    为这件事写的（`QuerySet.update()` 不触发 `auto_now`，不写的话年龄永远不涨）。
    """
    row = _seed(source="agent", updated_at=datetime.now(timezone.utc) - timedelta(seconds=600))
    jobs = _Jobs().install(monkeypatch)

    await _load(PROGRESSED_PATH)
    assert jobs.started == [(1, 68, 1)]

    async def fake_generate(*args, **kwargs):
        return {"tasks": [{"id": "fallback"}], "summary": "临时入口", "source": "fallback", "error": "智能体暂时不可用"}

    monkeypatch.setattr(service, "generate_agent_task_set", fake_generate)
    await jobs.producers[0]()

    assert row.source == "agent", "失败不该把已有的 agent 结果换成兜底"
    assert row.completed_nodes == 2, "失败了就没写回进度，条件仍然成立 —— 正因如此才需要冷却"

    jobs.started.clear()
    result = await _load(PROGRESSED_PATH)

    assert result["source"] == "agent"
    assert jobs.started == [], "失败之后紧接着的轮询必须被冷却挡住"


# ── 后台作业体 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_producer_writes_the_agent_result_back_into_the_row(snapshots, monkeypatch):
    row = _seed(source="pending")

    async def fake_generate(user_id, profile, path, mastery_records, milestone, fallback_tasks):
        assert fallback_tasks, "作业要拿到确定性兜底集，_normalise_agent_tasks 依赖它做契约校验"
        return {"tasks": [{"id": "new", "kind": "project"}], "summary": "已按需生成", "source": "agent", "error": None}

    monkeypatch.setattr(service, "generate_agent_task_set", fake_generate)

    await service._run_agent_generation(1, 68, 1, PROFILE, PATH, [], [{"id": "fallback"}])

    assert row.source == "agent"
    assert row.generation_error is None
    assert row.task_json["tasks"][0]["id"] == "new"
    assert row.completed_nodes == 2


@pytest.mark.asyncio
async def test_producer_records_a_failure_without_wiping_the_served_tasks(snapshots, monkeypatch):
    row = _seed(source="pending")

    async def fake_generate(*args, **kwargs):
        return {"tasks": [{"id": "fallback"}], "summary": "临时入口", "source": "fallback", "error": "智能体暂时不可用"}

    monkeypatch.setattr(service, "generate_agent_task_set", fake_generate)

    await service._run_agent_generation(1, 68, 1, PROFILE, PATH, [], [{"id": "fallback"}])

    assert row.source == "fallback"
    assert row.generation_error == "智能体暂时不可用"
    assert row.task_json["tasks"], "失败也要留下可渲染的任务"


@pytest.mark.asyncio
async def test_generation_status_marks_a_pending_snapshot_as_partial(snapshots, monkeypatch):
    """前端靠 generation_status 决定要不要继续轮询。"""
    _seed(source="pending")
    _Jobs(running=True).install(monkeypatch)

    result = await _load()

    assert result["source"] == "pending"


# ── 注册表本身 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_runs_one_job_per_milestone_and_holds_a_strong_reference(monkeypatch):
    """asyncio 只保留任务的弱引用：不拿住的话作业可能在跑完前被 GC。"""
    task_jobs._TASK_JOBS._jobs.clear()
    release = asyncio.Event()

    async def producer():
        await release.wait()

    job, created = await task_jobs.ensure_task_job(1, 68, 1, producer)
    again, created_again = await task_jobs.ensure_task_job(1, 68, 1, producer)

    assert created is True
    assert created_again is False, "同一个里程碑不能起两个作业"
    assert again is job
    assert job.task is not None and not job.task.done()
    assert task_jobs.is_generating(1, 68, 1) is True

    release.set()
    await job.task
    assert task_jobs.is_generating(1, 68, 1) is False
    assert task_jobs.get_job(1, 68, 1).state == task_jobs.STATE_READY

    task_jobs._TASK_JOBS._jobs.clear()


@pytest.mark.asyncio
async def test_registry_keeps_a_finished_job_queryable_and_then_prunes_it(monkeypatch):
    task_jobs._TASK_JOBS._jobs.clear()

    async def producer():
        return None

    job, _ = await task_jobs.ensure_task_job(2, 68, 1, producer)
    await job.task

    assert task_jobs.get_job(2, 68, 1) is not None, "终态要留着，否则调用方只看到「从没生成过」"

    # 假装过期很久
    job.finished_at = job.finished_at - task_jobs._TASK_JOBS._ttl - 1
    task_jobs._TASK_JOBS._prune_locked()

    assert task_jobs.get_job(2, 68, 1) is None
    task_jobs._TASK_JOBS._jobs.clear()


@pytest.mark.asyncio
async def test_registry_isolates_milestones():
    task_jobs._TASK_JOBS._jobs.clear()
    release = asyncio.Event()

    async def producer():
        await release.wait()

    first, _ = await task_jobs.ensure_task_job(1, 68, 1, producer)
    second, _ = await task_jobs.ensure_task_job(1, 68, 2, producer)

    assert first is not second
    assert task_jobs.is_generating(1, 68, 1) and task_jobs.is_generating(1, 68, 2)

    release.set()
    await asyncio.gather(first.task, second.task)
    task_jobs._TASK_JOBS._jobs.clear()
