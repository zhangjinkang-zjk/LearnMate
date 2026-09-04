# -*- coding: utf-8 -*-
"""Regression tests for learning-path resource cache isolation."""

import json
from types import SimpleNamespace

import pytest

from backend.src.service.path import helpers
from backend.src.service.resource import service as resource_service


class FakeQuery:
    def __init__(self, *, records=None, first_value=None, update_callback=None):
        self.records = list(records or [])
        self.first_value = first_value
        self.update_callback = update_callback

    def order_by(self, *_args):
        return self

    async def all(self):
        return self.records

    async def first(self):
        return self.first_value

    async def update(self, **fields):
        if self.update_callback:
            self.update_callback(fields)
        return 1


def _teaching_context(topic: str = "文档切分") -> dict:
    return {
        "subject": "检索增强生成",
        "current": {
            "topic": topic,
            "key_points": ["语义边界", "窗口重叠"],
            "teaching_spec": {
                "key_points": ["语义边界", "窗口重叠"],
            },
        },
    }


@pytest.mark.asyncio
async def test_invalid_bound_document_is_unbound_without_deleting_record(monkeypatch):
    progress = SimpleNamespace(
        id=41,
        resource_ids=json.dumps([101, 202]),
        node_status="in_progress",
    )
    invalid_document = SimpleNamespace(
        id=101,
        user_id=7,
        topic="文档切分",
        resource_type="document",
        content="# 旧文档\n\n内容不完整",
    )
    valid_mindmap = SimpleNamespace(
        id=202,
        user_id=7,
        topic="文档切分",
        resource_type="mindmap",
        content="文档切分\n  语义边界",
    )
    resource_queries = []
    binding_updates = []
    validation_calls = []

    def filter_resources(**filters):
        resource_queries.append(filters)
        if "topic" in filters:
            raise AssertionError("路径资源不应回退到全局 topic 缓存")
        return FakeQuery(records=[invalid_document, valid_mindmap])

    def filter_progress(**filters):
        return FakeQuery(update_callback=lambda fields: binding_updates.append((filters, fields)))

    def fake_validate(content, context):
        validation_calls.append((content, context))
        return ["文档有效内容不足 900 字符"]

    monkeypatch.setattr(helpers.GeneratedResource, "filter", filter_resources)
    monkeypatch.setattr(helpers.UserPathProgress, "filter", filter_progress)
    monkeypatch.setattr(helpers, "validate_document_chapter", fake_validate)

    existing, missing = await helpers.get_bound_node_resources(
        progress,
        7,
        ["document", "mindmap"],
        topic="文档切分",
        teaching_context=_teaching_context(),
    )

    assert [record.id for record in existing] == [202]
    assert missing == ["document"]
    assert len(validation_calls) == 1
    assert resource_queries == [{"id__in": [101, 202], "user_id": 7}]
    assert binding_updates == [
        ({"id": 41, "user_id": 7}, {"resource_ids": "[202]"}),
    ]
    assert progress.resource_ids == "[202]"
    assert invalid_document.content == "# 旧文档\n\n内容不完整"


@pytest.mark.asyncio
async def test_bound_resources_are_topic_scoped_and_never_use_global_fallback(monkeypatch):
    progress = SimpleNamespace(
        id=42,
        resource_ids=json.dumps([303]),
        node_status="in_progress",
    )
    wrong_topic_mindmap = SimpleNamespace(
        id=303,
        user_id=7,
        topic="另一个路径中的同名节点",
        resource_type="mindmap",
        content="其他路径内容",
    )
    resource_queries = []

    def filter_resources(**filters):
        resource_queries.append(filters)
        if "topic" in filters:
            raise AssertionError("同名主题全局资源不能跨路径复用")
        return FakeQuery(records=[wrong_topic_mindmap])

    binding_updates = []
    monkeypatch.setattr(helpers.GeneratedResource, "filter", filter_resources)
    monkeypatch.setattr(
        helpers.UserPathProgress,
        "filter",
        lambda **filters: FakeQuery(update_callback=lambda fields: binding_updates.append(fields)),
    )

    existing, missing = await helpers.get_bound_node_resources(
        progress,
        7,
        ["mindmap"],
        topic="文档切分",
        teaching_context=_teaching_context(),
    )

    assert existing == []
    assert missing == ["mindmap"]
    assert resource_queries == [{"id__in": [303], "user_id": 7}]
    assert binding_updates == [{"resource_ids": "[]"}]
    assert progress.resource_ids == "[]"


@pytest.mark.asyncio
async def test_teaching_context_disables_global_cache_for_generate_and_save(monkeypatch):
    cache_queries = []
    graph_calls = []

    class FakeGraph:
        async def ainvoke(self, state):
            graph_calls.append(state)
            return {
                "generated_resources": {"document": "new path chapter"},
                "review_passed": True,
                "retry_count": 0,
                "file_urls": {},
            }

    async def fake_make_state(*_args, **kwargs):
        return {
            "topic": "文档切分",
            "resource_types": kwargs.get("resource_types", ["document"]),
            "generated_resources": {},
        }

    async def fake_save_resources(*_args, **_kwargs):
        return [{
            "resource_id": 404,
            "topic": "文档切分",
            "resource_type": "document",
            "content": "new path chapter",
        }]

    monkeypatch.setattr(resource_service, "resource_graph", FakeGraph())
    monkeypatch.setattr(resource_service, "_make_state", fake_make_state)
    monkeypatch.setattr(resource_service, "_save_resources", fake_save_resources)
    monkeypatch.setattr(
        resource_service,
        "_ensure_generation_chat_group_id",
        lambda *_args, **_kwargs: _async_value(0),
    )

    def unexpected_global_lookup(**filters):
        cache_queries.append(filters)
        raise AssertionError("teaching_context 下不应查询全局资源缓存")

    monkeypatch.setattr(resource_service.GeneratedResource, "filter", unexpected_global_lookup)

    result = await resource_service.ResourceService.generate_and_save(
        topic="文档切分",
        user_id=7,
        resource_types=["document"],
        teaching_context=_teaching_context(),
    )

    assert result[0]["resource_id"] == 404
    assert graph_calls
    assert cache_queries == []


@pytest.mark.asyncio
async def test_teaching_context_disables_global_cache_for_stream(monkeypatch):
    cache_queries = []
    graph_calls = []

    class FakeGraph:
        async def astream(self, state, stream_mode):
            graph_calls.append((state, stream_mode))
            yield "values", {"generated_resources": {}, "review_passed": True, "retry_count": 0}

    class FakeUserQuery:
        async def first(self):
            return SimpleNamespace(id=7)

    async def fake_make_state(*_args, **_kwargs):
        return {"topic": "文档切分", "generated_resources": {}}

    async def fake_group_id(*_args, **_kwargs):
        return 0

    def unexpected_global_lookup(**filters):
        cache_queries.append(filters)
        raise AssertionError("teaching_context 下不应查询全局资源缓存")

    monkeypatch.setattr(resource_service, "resource_graph", FakeGraph())
    monkeypatch.setattr(resource_service, "_make_state", fake_make_state)
    monkeypatch.setattr(resource_service, "_ensure_generation_chat_group_id", fake_group_id)
    monkeypatch.setattr(resource_service.User, "filter", lambda **_filters: FakeUserQuery())
    monkeypatch.setattr(resource_service.GeneratedResource, "filter", unexpected_global_lookup)

    events = [
        event
        async for event in resource_service.ResourceService.generate_stream(
            topic="文档切分",
            user_id=7,
            resource_types=["mindmap"],
            teaching_context=_teaching_context(),
        )
    ]

    assert graph_calls
    assert cache_queries == []
    assert events[-1] == "data: [DONE]\n\n"


async def _async_value(value):
    return value
