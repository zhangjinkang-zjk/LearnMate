# -*- coding: utf-8 -*-
"""节点资源生成作业：挂载 / 脱离 / 增量绑定。

对应两条需求：
  - 切换页面不打断后台生成（订阅者断开 ≠ 作业被取消）
  - 生成请求不重复（同 key 只跑一个生产者；产出即绑定，避免孤儿资源导致重新生成）
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.src.service.path import node_resource_jobs
from backend.src.service.path import service as path_service


class FakeLock:
    def locked(self):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeQuery:
    def __init__(self, first_value=None):
        self.first_value = first_value

    async def first(self):
        return self.first_value

    async def all(self):
        return []

    def order_by(self, *_args):
        return self


def parse_sse_event(event: str) -> dict:
    return json.loads(event.removeprefix("data:").strip())


def _file_event(resource_id: int) -> str:
    payload = {
        "type": "file",
        "resource_id": resource_id,
        "resource_type": "document",
        "topic": "文档切分",
    }
    return f"data: {json.dumps(payload)}\n\n"


def _done_payload(resource_ids: list[int]) -> str:
    payload = {"done": True, "resources": [{"resource_id": rid} for rid in resource_ids]}
    return f"data: {json.dumps(payload)}\n\n"


async def _settle(predicate, attempts: int = 500) -> bool:
    """让出事件循环直到条件成立，或放弃。不依赖计时。"""
    for _ in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(0)
    return False


def _install(monkeypatch, *, node_id: int, stream, saved_resource_ids: list, stream_calls: list):
    """把生成链路整段换成假的，patch 打在 path_service 的导入点上。"""
    node = SimpleNamespace(id=node_id, topic="文档切分")
    progress = SimpleNamespace(id=node_id * 10, node_status="unlocked")

    async def get_lock(*_args):
        return FakeLock()

    async def get_resources(*_args, **_kwargs):
        return [], ["document"]

    async def get_context(*_args):
        return {"subject": "RAG"}

    async def save_resource_ids(progress_record, resource_ids):
        saved_resource_ids.append(list(resource_ids))

    async def counted_stream(**kwargs):
        stream_calls.append(kwargs.get("topic"))
        async for chunk in stream(**kwargs):
            yield chunk

    monkeypatch.setattr(path_service.PathNode, "filter", lambda **filters: FakeQuery(node))
    monkeypatch.setattr(path_service.UserPathProgress, "filter", lambda **filters: FakeQuery(progress))
    monkeypatch.setattr(path_service, "get_node_generation_lock", get_lock)
    monkeypatch.setattr(path_service, "get_bound_node_resources", get_resources)
    monkeypatch.setattr(path_service, "build_node_teaching_context", get_context)
    monkeypatch.setattr(path_service, "update_progress_resource_ids", save_resource_ids)
    monkeypatch.setattr(path_service.ResourceService, "generate_stream", counted_stream)
    return progress


@pytest.mark.asyncio
async def test_same_key_attaches_to_one_producer(monkeypatch):
    """第二个请求挂到同一个作业上，不再起第二个生产者。"""
    saved, calls = [], []
    release = asyncio.Event()

    async def stream(**_kwargs):
        yield _file_event(1)
        await release.wait()
        yield _file_event(2)
        yield _done_payload([1, 2])

    _install(monkeypatch, node_id=101, stream=stream, saved_resource_ids=saved, stream_calls=calls)

    first = path_service.PathService.generate_node_resources_stream(7, 101, 5)
    await first.__anext__()  # 生产者已启动
    second = path_service.PathService.generate_node_resources_stream(7, 101, 5)
    await second.__anext__()

    release.set()
    rest_first = [parse_sse_event(e) async for e in first]
    rest_second = [parse_sse_event(e) async for e in second]

    assert calls == ["文档切分"], "同一个 key 只应启动一个生产者"
    for rest in (rest_first, rest_second):
        # 逐字钉住线上格式：成功事件是 type == "done" 且**没有** done 字段，
        # 前端 sseClient 就是按 event.type === 'done' 判定结束的。
        assert rest[-1] == {
            "type": "done",
            "source": "learning_path",
            "path_id": 7,
            "node_id": 101,
            "resource_ids": [1, 2],
        }


@pytest.mark.asyncio
async def test_cancelled_subscriber_does_not_stop_the_job(monkeypatch):
    """切页面（取消订阅者）不会中断生成，绑定照样写完。"""
    saved, calls = [], []
    release = asyncio.Event()

    async def stream(**_kwargs):
        yield _file_event(1)
        await release.wait()
        yield _file_event(2)
        yield _done_payload([1, 2])

    _install(monkeypatch, node_id=202, stream=stream, saved_resource_ids=saved, stream_calls=calls)

    agen = path_service.PathService.generate_node_resources_stream(7, 202, 5)

    async def consume():
        return [parse_sse_event(e) async for e in agen]

    task = asyncio.create_task(consume())
    assert await _settle(lambda: len(saved) >= 1), "第一个资源应已增量绑定"

    # Starlette 断连时就是取消承载这个生成器的任务。
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    release.set()
    assert await _settle(lambda: len(saved) >= 2), "作业应能自行跑完"

    assert saved == [[1], [1, 2]], f"增量绑定应逐次增长，实际 {saved}"
    assert calls == ["文档切分"]


@pytest.mark.asyncio
async def test_binding_is_incremental_per_resource(monkeypatch):
    """每产出一个资源就绑定一次，而不是只在最后写一次。"""
    saved, calls = [], []

    async def stream(**_kwargs):
        yield _file_event(11)
        yield _file_event(12)
        yield _file_event(13)
        yield _done_payload([11, 12, 13])

    _install(monkeypatch, node_id=303, stream=stream, saved_resource_ids=saved, stream_calls=calls)

    events = [
        parse_sse_event(e)
        async for e in path_service.PathService.generate_node_resources_stream(7, 303, 5)
    ]

    assert saved == [[11], [11, 12], [11, 12, 13]], f"实际 {saved}"
    assert [e for e in events if e.get("type") == "resource"] != []
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_late_subscriber_replays_backlog_without_duplicates():
    """迟到的订阅者能补到历史，且同一条不会既从 backlog 又从实时队列收到。

    直接测作业原语（不经过生成链路），这样没有任何时序假设。
    """
    gate = asyncio.Event()

    async def producer(job):
        job.publish({"type": "resource", "resource_id": 21})
        await gate.wait()
        job.publish_terminal({"type": "done", "resource_ids": [21], "done": True})

    job = await node_resource_jobs.ensure_job((7, 404, 5), producer)

    early = node_resource_jobs.stream_job(job)
    assert parse_sse_event(await early.__anext__())["resource_id"] == 21

    late = node_resource_jobs.stream_job(job)
    assert parse_sse_event(await late.__anext__())["resource_id"] == 21, "迟到订阅者应从 backlog 补到历史"

    gate.set()
    rest_late = [parse_sse_event(e) async for e in late]
    rest_early = [parse_sse_event(e) async for e in early]

    assert [e for e in rest_late if e.get("done")], "迟到订阅者应收到终端事件"
    assert [e for e in rest_early if e.get("done")], "早到的订阅者应收到终端事件"
    # 去重：资源 21 各订阅者只收到一次。
    assert sum(1 for e in rest_late if e.get("resource_id") == 21) == 0
    assert sum(1 for e in rest_early if e.get("resource_id") == 21) == 0
    assert sum(1 for e in rest_late if e.get("done")) == 1
    assert sum(1 for e in rest_early if e.get("done")) == 1


@pytest.mark.asyncio
async def test_terminal_event_is_always_last_on_failure(monkeypatch):
    """生成抛异常时，最后一个事件仍然是终端 error。"""
    saved, calls = [], []

    async def stream(**_kwargs):
        yield _file_event(31)
        raise RuntimeError("401 invalid api_key=secret-provider-detail")

    _install(monkeypatch, node_id=505, stream=stream, saved_resource_ids=saved, stream_calls=calls)

    events = [
        parse_sse_event(e)
        async for e in path_service.PathService.generate_node_resources_stream(7, 505, 5)
    ]

    assert events[-1]["type"] == "error"
    assert events[-1]["done"] is True
    assert "secret-provider-detail" not in events[-1]["detail"]
    # 资源 31 一产出就绑上了；异常路径不会再重复写一次同样的列表。
    assert saved == [[31]], f"异常路径也要把已产出的资源绑上，实际 {saved}"


@pytest.mark.asyncio
async def test_second_request_after_completion_does_not_regenerate(monkeypatch):
    """作业结束后重新请求：绑定的资源被判定为已存在，不再产出新资源。

    这里模拟真实语义 —— 第一次生成把资源绑到了节点上，所以第二次
    get_bound_node_resources 会返回"没有缺失类型"。
    """
    saved, calls = [], []
    bound: list = []

    async def stream(**_kwargs):
        yield _file_event(41)
        yield _done_payload([41])

    node = SimpleNamespace(id=606, topic="文档切分")
    progress = SimpleNamespace(id=6060, node_status="unlocked")

    async def get_lock(*_args):
        return FakeLock()

    async def get_resources(*_args, **_kwargs):
        if bound:
            return [SimpleNamespace(id=41, resource_type="document", topic="文档切分", content="", file_url="")], []
        return [], ["document"]

    async def get_context(*_args):
        return {"subject": "RAG"}

    async def save_resource_ids(_progress, resource_ids):
        saved.append(list(resource_ids))
        bound[:] = list(resource_ids)

    async def counted_stream(**kwargs):
        calls.append(kwargs.get("topic"))
        async for chunk in stream(**kwargs):
            yield chunk

    monkeypatch.setattr(path_service.PathNode, "filter", lambda **filters: FakeQuery(node))
    monkeypatch.setattr(path_service.UserPathProgress, "filter", lambda **filters: FakeQuery(progress))
    monkeypatch.setattr(path_service, "get_node_generation_lock", get_lock)
    monkeypatch.setattr(path_service, "get_bound_node_resources", get_resources)
    monkeypatch.setattr(path_service, "build_node_teaching_context", get_context)
    monkeypatch.setattr(path_service, "update_progress_resource_ids", save_resource_ids)
    monkeypatch.setattr(path_service.ResourceService, "generate_stream", counted_stream)

    first = [parse_sse_event(e) async for e in path_service.PathService.generate_node_resources_stream(7, 606, 5)]
    assert first[-1]["type"] == "done"
    assert calls == ["文档切分"]

    second = [parse_sse_event(e) async for e in path_service.PathService.generate_node_resources_stream(7, 606, 5)]
    assert second[-1]["type"] == "done"
    assert second[-1]["resource_ids"] == [41]
    assert calls == ["文档切分"], "第二次请求不应再触发一次生成"
