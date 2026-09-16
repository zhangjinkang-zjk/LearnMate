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
        content="# 旧文档\n\n待补充",
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

    def fake_validate(content):
        validation_calls.append(content)
        return ["文档包含省略或待补充占位语"]

    monkeypatch.setattr(helpers.GeneratedResource, "filter", filter_resources)
    monkeypatch.setattr(helpers.UserPathProgress, "filter", filter_progress)
    monkeypatch.setattr(helpers, "validate_document_safety", fake_validate)

    existing, missing = await helpers.get_bound_node_resources(
        progress,
        7,
        ["document", "mindmap"],
        topic="文档切分",
        teaching_context=_teaching_context(),
    )

    assert [record.id for record in existing] == [202]
    assert missing == ["document"]
    assert validation_calls == ["# 旧文档\n\n待补充"]
    assert resource_queries == [{"id__in": [101, 202], "user_id": 7}]
    assert binding_updates == [
        ({"id": 41, "user_id": 7}, {"resource_ids": "[202]"}),
    ]
    assert progress.resource_ids == "[202]"
    assert invalid_document.content == "# 旧文档\n\n待补充"


@pytest.mark.asyncio
async def test_short_but_sound_document_is_reused_instead_of_regenerated(monkeypatch):
    """复用校验只拦坏内容。

    曾经这里用的是整章质量目标（≥900 字、≥3 个小节），于是一份"短但完好"的成稿
    每次进章节都被解绑、再整章重新生成一遍；生成侧又修不动这些目标，就成了死循环。
    """
    progress = SimpleNamespace(
        id=43,
        resource_ids=json.dumps([505]),
        node_status="in_progress",
    )
    short_document = SimpleNamespace(
        id=505,
        user_id=7,
        topic="文档切分",
        resource_type="document",
        content="# 文档切分\n\n## 语义边界\n\n短，但内容本身是完好的。",
    )
    binding_updates = []

    def filter_resources(**filters):
        return FakeQuery(records=[short_document])

    def filter_progress(**filters):
        return FakeQuery(update_callback=lambda fields: binding_updates.append((filters, fields)))

    monkeypatch.setattr(helpers.GeneratedResource, "filter", filter_resources)
    monkeypatch.setattr(helpers.UserPathProgress, "filter", filter_progress)

    existing, missing = await helpers.get_bound_node_resources(
        progress,
        7,
        ["document"],
        topic="文档切分",
        teaching_context=_teaching_context(),
    )

    assert [record.id for record in existing] == [505]
    assert missing == []
    assert binding_updates == [], "完好的成稿不该被解绑"


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


_CHAPTER_PARAGRAPH = (
    "文档切分决定了检索时每个片段能承载多少语义信息，块大小过大时会混入多个主题，"
    "块大小过小时又会丢掉上下文。实践中通常先按语义边界切分，再通过窗口重叠把相邻"
    "片段的衔接部分补回来，使跨越边界的问题仍然能够被召回。判断切分是否合适，"
    "要看召回结果里是否同时出现完整语义和足够的上下文线索。"
)


def _paraphrased_chapter() -> str:
    """A structurally valid chapter that never writes the key point verbatim."""
    sections = [
        f"## {title}\n\n{_CHAPTER_PARAGRAPH * 3}"
        for title in ("切分粒度", "窗口重叠", "召回验证")
    ]
    return "# 文档切分策略：块大小与重叠调优\n\n" + "\n\n".join(sections)


@pytest.mark.asyncio
async def test_bound_document_with_paraphrased_key_points_stays_bound(monkeypatch):
    """Regression: a wording mismatch must not unbind an otherwise valid document.

    The generating prompt carries the same key points, so re-running generation
    reproduces the same wording.  Unbinding on coverage made every visit to the
    chapter regenerate the whole document forever.  Uses the real validator.
    """
    chapter = _paraphrased_chapter()
    assert "文档切分" in chapter and "块重叠" not in chapter

    progress = SimpleNamespace(
        id=51,
        resource_ids=json.dumps([601]),
        node_status="in_progress",
    )
    bound_document = SimpleNamespace(
        id=601,
        user_id=7,
        topic="文档切分策略：块大小与重叠调优",
        resource_type="document",
        content=chapter,
    )
    binding_updates = []

    monkeypatch.setattr(
        helpers.GeneratedResource,
        "filter",
        lambda **filters: FakeQuery(records=[bound_document]),
    )

    def filter_progress(**filters):
        return FakeQuery(update_callback=lambda fields: binding_updates.append(fields))

    monkeypatch.setattr(helpers.UserPathProgress, "filter", filter_progress)

    # 683 在真实库里的形态：单条 key point 直接来自 knowledge_tags。
    teaching_context = {
        "current": {
            "topic": "文档切分策略：块大小与重叠调优",
            "teaching_spec": {"key_points": ["文档切分与块重叠"]},
        },
    }

    existing, missing = await helpers.get_bound_node_resources(
        progress,
        7,
        ["document"],
        topic="文档切分策略：块大小与重叠调优",
        teaching_context=teaching_context,
    )

    assert [record.id for record in existing] == [601]
    assert missing == []
    assert binding_updates == []
    assert progress.resource_ids == json.dumps([601])


async def _async_value(value):
    return value
