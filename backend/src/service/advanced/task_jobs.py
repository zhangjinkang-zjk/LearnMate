"""进阶学习里的后台作业注册表（任务生成 / 实践评分）。

**为什么要有这个**：智能体生成一次要在 40~120 秒量级，原来它是**同步跑在
`GET /learning/advanced/current` 里面**的（`asyncio.wait_for(..., timeout=40)`）。结果是
两件事同时发生：请求阻塞到超时，然后页面退到确定性兜底；而兜底快照按
`(user, path, milestone)` 永久缓存，于是**一次超时被冻成这个里程碑的永久结果**——
实测库里 09-04 那次 source=agent，之后 12 天全是 fallback，智能体恢复了也没用。

所以生成搬到后台：请求立刻返回确定性任务（`source="pending"`），作业跑完把结果写回，
前端下一次轮询就接上。实践评分（`practice_service.run_grading`）遇到的是同一个问题：
实测一次判分要 57.6 秒，而前端 httpClient 的超时只有 15 秒，同步判分必然超时。

结构照抄 `service/path/path_video_jobs.py`（同样只需要"单飞 + 可查状态"）：
dataclass 持强引用 + `asyncio.Lock` 包住 check-and-create + 终态保留 TTL。

**不要用裸 `asyncio.ensure_future`**（`service/resource/tasks.py` 就是这么写的）：
asyncio 只保留任务的弱引用，不拿住的话作业可能在跑完前被 GC。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Hashable

logger = logging.getLogger(__name__)

# (user_id, path_id, milestone)
AdvancedTaskKey = tuple[int, int, int]
# (user_id, session_key)
PracticeGradingKey = tuple[int, str]

STATE_RUNNING = "generating"
STATE_READY = "ready"
STATE_FAILED = "failed"

# 终态保留时长：够调用方在一次轮询间隔里读到失败原因，又不至于让注册表一直涨。
_TERMINAL_TTL_SECONDS = 600
_MAX_JOBS = 128


@dataclass
class Job:
    key: Hashable
    producer: Callable[[], Awaitable[None]]
    label: str = "作业"
    state: str = STATE_RUNNING
    error: str = ""
    # 强引用。asyncio 只保留任务的弱引用，不拿住的话作业可能在跑完前被 GC。
    task: asyncio.Task | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None


class JobRegistry:
    """单飞 + 可查状态的作业注册表。同一把 key 上永远只有一个生产者在跑。"""

    def __init__(self, name: str, *, ttl_seconds: int = _TERMINAL_TTL_SECONDS, max_jobs: int = _MAX_JOBS) -> None:
        self._name = name
        self._ttl = ttl_seconds
        self._max = max_jobs
        self._jobs: dict[Hashable, Job] = {}
        # check-and-create 必须在锁内，否则两个并发请求会各起一个生产者。
        self._guard = asyncio.Lock()

    def is_running(self, key: Hashable) -> bool:
        """这把 key 上是否有作业正在跑。

        调用方靠它区分"跑着呢，等着"和"注册表里什么都没有（比如进程重启过），
        那就是陈旧状态，该重新起一个"。
        """
        job = self._jobs.get(key)
        return job is not None and job.state == STATE_RUNNING

    def get(self, key: Hashable) -> Job | None:
        return self._jobs.get(key)

    def _prune_locked(self) -> None:
        """只清"已结束且过了 TTL"的作业，以及超上限时最老的已结束作业。调用方须持锁。"""
        now = time.monotonic()
        for key, job in list(self._jobs.items()):
            if job.state != STATE_RUNNING and job.finished_at is not None:
                if now - job.finished_at > self._ttl:
                    self._jobs.pop(key, None)
        while len(self._jobs) > self._max:
            finished = [key for key, job in self._jobs.items() if job.state != STATE_RUNNING]
            if not finished:
                break
            self._jobs.pop(min(finished, key=lambda key: self._jobs[key].started_at), None)

    async def _drive(self, job: Job) -> None:
        try:
            await job.producer()
            job.state = STATE_READY
        except asyncio.CancelledError:
            job.state = STATE_FAILED
            job.error = "作业被取消"
            raise
        except Exception as exc:
            job.state = STATE_FAILED
            job.error = str(exc)[:300] or exc.__class__.__name__
            logger.exception("%s失败 key=%s", self._name, job.key)
        finally:
            job.finished_at = time.monotonic()

    def _log_finished(self, key: Hashable, task: asyncio.Task) -> None:
        """记录异常；终态留给 _prune_locked 按 TTL 回收，这里不摘除。"""
        if task.cancelled():
            logger.warning("%s被取消 key=%s", self._name, key)
            return
        error = task.exception()
        if error is not None:
            logger.error("%s异常结束 key=%s", self._name, key, exc_info=error)

    async def ensure(self, key: Hashable, producer: Callable[[], Awaitable[None]]) -> tuple[Job, bool]:
        """同一把 key 已有作业在跑就返回它，否则新建一个。返回 (job, 本次是否新建)。

        producer 由调用方注入，本模块不反向依赖具体 service，避免循环导入。
        """
        async with self._guard:
            self._prune_locked()
            existing = self._jobs.get(key)
            if existing is not None and existing.state == STATE_RUNNING:
                return existing, False

            job = Job(key=key, producer=producer, label=self._name)
            self._jobs[key] = job
            task = asyncio.create_task(self._drive(job))
            job.task = task
            task.add_done_callback(lambda done: self._log_finished(key, done))
            logger.info("%s已启动 key=%s", self._name, key)
            return job, True


_TASK_JOBS = JobRegistry("进阶任务生成作业")
_GRADING_JOBS = JobRegistry("实践评分作业")


def _task_key(user_id: int, path_id: int, milestone: int) -> AdvancedTaskKey:
    return (int(user_id), int(path_id), int(milestone))


def is_generating(user_id: int, path_id: int, milestone: int) -> bool:
    return _TASK_JOBS.is_running(_task_key(user_id, path_id, milestone))


def get_job(user_id: int, path_id: int, milestone: int) -> Job | None:
    return _TASK_JOBS.get(_task_key(user_id, path_id, milestone))


async def ensure_task_job(
    user_id: int,
    path_id: int,
    milestone: int,
    producer: Callable[[], Awaitable[None]],
) -> tuple[Job, bool]:
    return await _TASK_JOBS.ensure(_task_key(user_id, path_id, milestone), producer)


def _grading_key(user_id: int, session_key: str) -> PracticeGradingKey:
    return (int(user_id), str(session_key))


def is_grading(user_id: int, session_key: str) -> bool:
    """这次实践会话的评分作业是否在跑。

    `get_session` 靠它区分"还在评分"和"评分作业没了（进程重启过）"—— 后者要拿确定性
    评分补一份，否则用户永远停在"正在评价你的方案"。
    """
    return _GRADING_JOBS.is_running(_grading_key(user_id, session_key))


def get_grading_job(user_id: int, session_key: str) -> Job | None:
    return _GRADING_JOBS.get(_grading_key(user_id, session_key))


async def ensure_grading_job(
    user_id: int,
    session_key: str,
    producer: Callable[[], Awaitable[None]],
) -> tuple[Job, bool]:
    return await _GRADING_JOBS.ensure(_grading_key(user_id, session_key), producer)
