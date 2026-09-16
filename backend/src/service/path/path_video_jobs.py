"""路径级视频生成作业注册表。

与 `node_resource_jobs` 的区别：这里只需要"单飞 + 可查状态"，不需要 SSE 事件流，
所以用轻量状态机而不是 NodeResourceJob。

**终态作业不立即摘除**：生成失败时 DB 里不会留下记录，如果注册表也把作业清掉，
调用方只能看到"从来没有生成过"，会不断重新发起生成。所以终态要保留一段 TTL 供查询。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

PathVideoKey = tuple[int, int]  # (user_id, path_id)

STATE_RUNNING = "generating"
STATE_READY = "ready"
STATE_FAILED = "failed"

# 终态保留时长：够调用方在轮询间隔里读到失败原因，又不至于让注册表一直涨。
_TERMINAL_TTL_SECONDS = 600
_MAX_JOBS = 256


@dataclass
class PathVideoJob:
    key: PathVideoKey
    producer: Callable[[], Awaitable[dict]]
    state: str = STATE_RUNNING
    error: str = ""
    # 强引用。asyncio 只保留任务的弱引用，不拿住的话作业可能在跑完前被 GC。
    task: asyncio.Task | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None


_JOBS: dict[PathVideoKey, PathVideoJob] = {}
# check-and-create 必须在锁内，否则两个并发请求会各起一个生产者。
_JOBS_GUARD = asyncio.Lock()


def _make_key(user_id: int, path_id: int) -> PathVideoKey:
    return (int(user_id), int(path_id))


def get_path_video_job(user_id: int, path_id: int) -> PathVideoJob | None:
    """查询某个路径上是否有作业及其状态；没有则返回 None。"""
    return _JOBS.get(_make_key(user_id, path_id))


def _prune_locked() -> None:
    """只清"已结束且过了 TTL"的作业，以及超出上限时最老的已结束作业。调用方须持锁。"""
    now = time.monotonic()
    for key, job in list(_JOBS.items()):
        if job.state != STATE_RUNNING and job.finished_at is not None:
            if now - job.finished_at > _TERMINAL_TTL_SECONDS:
                _JOBS.pop(key, None)
    while len(_JOBS) > _MAX_JOBS:
        finished = [key for key, job in _JOBS.items() if job.state != STATE_RUNNING]
        if not finished:
            break
        _JOBS.pop(min(finished, key=lambda key: _JOBS[key].started_at), None)


async def _drive(job: PathVideoJob) -> None:
    try:
        await job.producer()
        job.state = STATE_READY
    except asyncio.CancelledError:
        job.state = STATE_FAILED
        job.error = "生成任务被取消"
        raise
    except Exception as exc:
        job.state = STATE_FAILED
        job.error = str(exc)[:300] or exc.__class__.__name__
        logger.exception("路径视频后台生成失败 key=%s", job.key)
    finally:
        job.finished_at = time.monotonic()


def _log_finished(key: PathVideoKey, task: asyncio.Task) -> None:
    """记录异常；终态留给 _prune_locked 按 TTL 回收，这里不摘除。"""
    if task.cancelled():
        logger.warning("路径视频作业被取消 key=%s", key)
        return
    error = task.exception()
    if error is not None:
        logger.error("路径视频作业异常结束 key=%s", key, exc_info=error)


async def ensure_path_video_job(
    user_id: int,
    path_id: int,
    producer: Callable[[], Awaitable[dict]],
) -> tuple[PathVideoJob, bool]:
    """同一个 key 已有作业在跑就返回它，否则新建一个。返回 (job, 本次是否新建)。

    producer 由调用方注入，本模块不反向依赖 PathService，避免循环导入。
    """
    key = _make_key(user_id, path_id)
    async with _JOBS_GUARD:
        _prune_locked()
        existing = _JOBS.get(key)
        if existing is not None and existing.state == STATE_RUNNING:
            return existing, False

        job = PathVideoJob(key=key, producer=producer)
        _JOBS[key] = job
        task = asyncio.create_task(_drive(job))
        job.task = task
        task.add_done_callback(lambda done: _log_finished(key, done))
        logger.info("路径视频作业已启动 path_id=%s user_id=%s", path_id, user_id)
        return job, True
