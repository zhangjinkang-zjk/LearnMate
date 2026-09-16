"""把节点资源生成从 HTTP 请求栈上摘下来，做成可挂载 / 可脱离的后台作业。

**为什么需要这层。** 生成原来直接在 SSE 生成器里 `await`，而 Starlette 在客户端断开
（切页面 → 前端 `AbortController.abort()`）时会取消承载它的任务，于是生成被掐断；
更糟的是掐断时 `except Exception` 抓不住 `CancelledError`（它是 `BaseException`），
所以"把已生成资源的 id 回写绑定到节点"那一步会被跳过，留下已落库但未绑定的孤儿资源，
下次进这一章就被判定为缺失、整批重新生成。

**这层的做法。** 生成交给一个独立的后台任务（强引用存在 `_JOBS` 里），HTTP 请求只做订阅者：
断开只掉一个订阅者，生成不受影响；再次进入会挂到同一个作业上，不新建。作业的每个事件
扇出给所有订阅者，迟到的订阅者从 `backlog` 补历史。

**刻意不依赖 Redis。** 作业注册表本来就是进程内的，跨进程挂载无从谈起；而 Redis 不可用时
`replay_sse` 返回 `[]`，引入它只增加复杂度。历史回放由进程内的 `backlog` 提供，
而"重启后还剩什么"由调用方自己增量持久化（见 `PathService._bind_node_resources`）。

本模块是通用的，不知道"资源"是什么：生产者协程由调用方通过 `producer_factory` 传入。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.src.utils.constants import SSE_POLL_TIMEOUT

logger = logging.getLogger(__name__)

# 作业身份。约定 key[0] 必须是 user_id —— 并发闸门按用户分。
JobKey = tuple

# 迟到订阅者的进程内回放窗口。超出就只丢最老的，终端事件永远在最后一条。
_BACKLOG_LIMIT = 200

# 订阅者在这段时间内没收到事件就发一次 keepalive。前端已忽略未知事件类型。
_KEEPALIVE_SECONDS = SSE_POLL_TIMEOUT

_JOBS: dict[JobKey, "NodeResourceJob"] = {}
_JOBS_GUARD = asyncio.Lock()
_USER_SEMAPHORES: dict[int, asyncio.Semaphore] = {}


def format_sse(data: dict) -> str:
    """把一个事件序列化成 SSE 帧。线上格式与改造前逐字一致。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _is_terminal(event: dict) -> bool:
    """成功事件只有 `type: "done"`，错误事件才带 `done: True` —— 两者都要认。

    不能靠给事件补一个 `done` 字段来统一：前端按事件类型分发，线上格式必须逐字保持。
    """
    return event.get("type") == "done" or bool(event.get("done"))


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw.strip()))
    except (TypeError, ValueError):
        return default


def _max_concurrent_per_user() -> int:
    # 改造前切章节会 abort 掉上一个，天然只有约一个在跑；改造后连点五章就会有五个作业，
    # 每个 mindmap 还会各起一个线程池。这道闸门是为此加的。
    return _env_int("NODE_RESOURCE_MAX_CONCURRENT_PER_USER", 2)


def _user_semaphore(user_id: int) -> asyncio.Semaphore:
    sem = _USER_SEMAPHORES.get(user_id)
    if sem is None:
        sem = asyncio.Semaphore(_max_concurrent_per_user())
        _USER_SEMAPHORES[user_id] = sem
    return sem


@dataclass
class NodeResourceJob:
    key: JobKey
    task: asyncio.Task | None = None
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    # (seq, event) —— seq 只用于回放与实时两条路去重，不进线上载荷。
    backlog: list[tuple[int, dict]] = field(default_factory=list)
    seq: int = 0
    finished: bool = False
    terminal_sent: bool = False

    def publish(self, event: dict) -> None:
        self.seq += 1
        item = (self.seq, event)
        self.backlog.append(item)
        if len(self.backlog) > _BACKLOG_LIMIT:
            del self.backlog[: len(self.backlog) - _BACKLOG_LIMIT]
        for queue in list(self.subscribers):
            queue.put_nowait(item)

    def publish_terminal(self, event: dict) -> None:
        """发布终端事件并记下"已经发过"，保证每个作业恰好有一个。"""
        if self.terminal_sent:
            return
        self.terminal_sent = True
        self.publish(event)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)


def active_job_count() -> int:
    """仅用于测试与诊断。"""
    return len(_JOBS)


def _forget(key: JobKey, job: NodeResourceJob, task: asyncio.Task) -> None:
    if _JOBS.get(key) is job:
        _JOBS.pop(key, None)
    # 先发布终端事件再置 finished（生产者里做的），所以订阅者看到 finished 时
    # 队列里一定已经有终端事件。
    job.finished = True
    if task.cancelled():
        logger.warning("节点资源作业被取消 key=%s", key)
        return
    exc = task.exception()
    if exc is not None:
        logger.error("节点资源作业异常结束 key=%s", key, exc_info=exc)


async def _drive(job: NodeResourceJob, producer: Callable[["NodeResourceJob"], Awaitable[None]]) -> None:
    user_id = job.key[0]
    semaphore = _user_semaphore(user_id)
    if semaphore.locked():
        job.publish({"type": "status", "source": "learning_path", "msg": "前面还有生成任务，已为你排队…"})
    async with semaphore:
        await producer(job)


async def ensure_job(
    key: JobKey,
    producer_factory: Callable[["NodeResourceJob"], Awaitable[None]],
) -> NodeResourceJob:
    """已经有同一个 key 的作业在跑就返回它（挂载），否则新建一个（生产者常驻）。

    `check-and-create` 必须在锁里，否则两个并发请求会各自建一个作业。
    """
    async with _JOBS_GUARD:
        existing = _JOBS.get(key)
        if existing is not None and not existing.finished:
            return existing
        job = NodeResourceJob(key=key)
        _JOBS[key] = job
        task = asyncio.create_task(_drive(job, producer_factory))
        job.task = task
        task.add_done_callback(lambda done: _forget(key, job, done))
        return job


async def stream_job(job: NodeResourceJob):
    """订阅一个作业并把它的事件流出去。断开时只退订，不影响作业本身。"""
    queue = job.subscribe()
    last_seq = 0
    try:
        # 迟到订阅者先补历史：可能包含"排队中"和已经产出的资源。
        for seq, event in list(job.backlog):
            if seq <= last_seq:
                continue
            last_seq = seq
            yield format_sse(event)
            if _is_terminal(event):
                return

        while True:
            # 作业已结束且队列已排空 —— 兜底，正常情况已经在上面的终端分支返回了。
            if job.finished and queue.empty():
                return
            try:
                seq, event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                yield format_sse({"type": "keepalive"})
                continue
            if seq <= last_seq:
                continue
            last_seq = seq
            yield format_sse(event)
            if _is_terminal(event):
                return
    finally:
        job.unsubscribe(queue)


__all__ = [
    "JobKey",
    "NodeResourceJob",
    "active_job_count",
    "ensure_job",
    "format_sse",
    "stream_job",
]
