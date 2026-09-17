# -*- coding: utf-8 -*-
"""学习路径自动生成的资源必须走审核，两个入口口径要一致。

这两个入口以前都传 skip_review=True，理由是"自动生成，省点时间"。代价是学生拿到的是
没审过的版本：

  - 文档的跨章节交叉验证整段不跑。那一步不只是"报个问题"——发现前后矛盾会带反馈重修
    全文（见 resource_graph 里那段注释），跳过等于把幻觉原样留在库里。
  - 章节看板每节都停在"待审核"，而这一轮根本不会有人来审，前端也无从知道。

两个入口（流式 / 非流式）生成的是同一批节点资源，审核口径必须一致 —— 否则"从哪个
接口进来的"就决定了学生看到的是不是审过的版本。所以这里两个都钉。
"""

from types import SimpleNamespace

import pytest

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


def _install_common(monkeypatch, node_id: int = 101):
    node = SimpleNamespace(id=node_id, topic="文档切分")
    progress = SimpleNamespace(id=node_id * 10, node_status="unlocked")

    async def get_lock(*_args):
        return FakeLock()

    async def get_resources(*_args, **_kwargs):
        return [], ["document"]

    async def get_context(*_args):
        return {"subject": "RAG"}

    async def save_ids(*_args):
        return None

    monkeypatch.setattr(path_service.PathNode, "filter", lambda **f: FakeQuery(node))
    monkeypatch.setattr(path_service.UserPathProgress, "filter", lambda **f: FakeQuery(progress))
    monkeypatch.setattr(path_service.GeneratedResource, "filter", lambda **f: FakeQuery(None))
    monkeypatch.setattr(path_service, "get_node_generation_lock", get_lock)
    monkeypatch.setattr(path_service, "get_bound_node_resources", get_resources)
    monkeypatch.setattr(path_service, "build_node_teaching_context", get_context)
    monkeypatch.setattr(path_service, "update_progress_resource_ids", save_ids)
    return node, progress


@pytest.mark.asyncio
async def test_the_streaming_entry_asks_for_review(monkeypatch):
    """基础学习那条流式生成（事件推给前端看板的就是它）。"""
    _install_common(monkeypatch)
    seen: list[dict] = []

    async def fake_stream(**kwargs):
        seen.append(kwargs)
        yield 'data: {"done": true, "resources": []}\n\n'

    monkeypatch.setattr(path_service.ResourceService, "generate_stream", fake_stream)

    async for _ in path_service.PathService.generate_node_resources_stream(7, 101, 5):
        pass

    assert seen, "生成根本没被调用，这个用例什么也没验证到"
    assert not seen[0].get("skip_review"), "自动生成又绕开审核了"


@pytest.mark.asyncio
async def test_the_plain_entry_asks_for_review(monkeypatch):
    """非流式那个入口（generate_and_save）。"""
    _install_common(monkeypatch, node_id=202)
    seen: list[dict] = []

    async def fake_save(**kwargs):
        seen.append(kwargs)
        return []

    monkeypatch.setattr(path_service.ResourceService, "generate_and_save", fake_save)

    await path_service.PathService.generate_node_resources(7, 202, 5)

    assert seen, "生成根本没被调用，这个用例什么也没验证到"
    assert not seen[0].get("skip_review"), "自动生成又绕开审核了"


@pytest.mark.asyncio
async def test_both_entries_agree_about_review(monkeypatch):
    """同一批节点资源，从哪个入口生成都该是同一个审核口径。

    分开钉两次是为了让"其中一个被改回去"也能定位到具体是哪个入口；这一条管的是两
    者之间的关系 —— 只改一个就等于学生拿到的东西取决于接口。
    """
    _install_common(monkeypatch)
    stream_args, save_args = [], []

    async def fake_stream(**kwargs):
        stream_args.append(kwargs)
        yield 'data: {"done": true, "resources": []}\n\n'

    async def fake_save(**kwargs):
        save_args.append(kwargs)
        return []

    monkeypatch.setattr(path_service.ResourceService, "generate_stream", fake_stream)
    monkeypatch.setattr(path_service.ResourceService, "generate_and_save", fake_save)

    async for _ in path_service.PathService.generate_node_resources_stream(7, 101, 5):
        pass
    await path_service.PathService.generate_node_resources(7, 101, 5)

    assert stream_args and save_args, "有一个入口没被调用到"
    assert bool(stream_args[0].get("skip_review")) == bool(save_args[0].get("skip_review"))
