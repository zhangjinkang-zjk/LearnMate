# -*- coding: utf-8 -*-
"""Learning-path write authorization and terminal SSE error tests."""

import json
from types import SimpleNamespace

import pytest

from backend.src.service.path import service as path_service


class FakeQuery:
    def __init__(self, first_value=None, *, update_callback=None, all_value=None, count_value=0):
        self.first_value = first_value
        self.update_callback = update_callback
        self.all_value = all_value or []
        self.count_value = count_value

    def order_by(self, *args):
        return self

    async def first(self):
        return self.first_value

    async def update(self, **fields):
        if self.update_callback:
            self.update_callback(fields)
        return 1

    async def all(self):
        return self.all_value

    async def count(self):
        return self.count_value


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "add", "delete"])
async def test_cross_user_path_writes_are_rejected_without_node_lookup(monkeypatch, operation):
    stored_path = SimpleNamespace(id=17, user_id=7)
    path_filters = []

    def filter_path(**filters):
        path_filters.append(filters)
        result = stored_path if filters.get("user_id") == stored_path.user_id else None
        return FakeQuery(result)

    def unexpected_node_lookup(**filters):
        raise AssertionError(f"unauthorized request reached node lookup: {filters}")

    monkeypatch.setattr(path_service.LearningPath, "filter", filter_path)
    monkeypatch.setattr(path_service.PathNode, "filter", unexpected_node_lookup)

    with pytest.raises(ValueError, match="^路径不存在$"):
        if operation == "update":
            await path_service.PathService.update_node(17, 31, 99, topic="越权修改")
        elif operation == "add":
            await path_service.PathService.add_node(17, "越权新增", 99)
        else:
            await path_service.PathService.delete_node(17, 31, 99)

    assert path_filters == [{"id": 17, "user_id": 99}]


@pytest.mark.asyncio
async def test_scope_update_rebuilds_teaching_spec_and_unbinds_stale_resources(monkeypatch):
    stored_path = SimpleNamespace(id=17, user_id=7)
    node_updates = []
    progress_updates = []
    node = SimpleNamespace(
        id=31,
        topic="旧主题",
        knowledge_tags=json.dumps(["旧知识点"], ensure_ascii=False),
        resource_types=json.dumps(["document", "mindmap"]),
        quiz_config=json.dumps({"count": 5, "threshold": 0.7}),
        teaching_spec=json.dumps(
            {
                "module": "旧模块",
                "cognitive_level": "应用",
                "learning_goal": "掌握旧主题",
                "key_points": ["旧知识点"],
                "micro_example": "旧示例",
            },
            ensure_ascii=False,
        ),
        order_index=2,
    )

    async def refresh_node():
        for fields in node_updates:
            for key, value in fields.items():
                setattr(node, key, value)

    node.refresh_from_db = refresh_node

    monkeypatch.setattr(
        path_service.LearningPath,
        "filter",
        lambda **filters: FakeQuery(stored_path),
    )
    monkeypatch.setattr(
        path_service.PathNode,
        "filter",
        lambda **filters: FakeQuery(
            node,
            update_callback=lambda fields: node_updates.append(fields),
        ),
    )
    monkeypatch.setattr(
        path_service.UserPathProgress,
        "filter",
        lambda **filters: FakeQuery(
            update_callback=lambda fields: progress_updates.append(fields),
        ),
    )

    result = await path_service.PathService.update_node(
        17,
        31,
        7,
        topic="新主题",
        knowledge_tags=["新知识点", "实践验证"],
    )

    stored_spec = json.loads(node_updates[0]["teaching_spec"])
    assert stored_spec["learning_goal"] == "能够解释并应用「新主题」的核心知识"
    assert stored_spec["key_points"] == ["新知识点", "实践验证"]
    assert "旧主题" not in json.dumps(stored_spec, ensure_ascii=False)
    assert progress_updates == [
        {
            "resource_ids": None,
            "narration_status": "",
            "quiz_session_id": None,
        }
    ]
    assert result["topic"] == "新主题"
    assert result["teaching_spec"] == stored_spec


@pytest.mark.asyncio
async def test_explicit_teaching_spec_is_preserved_during_scope_update(monkeypatch):
    stored_path = SimpleNamespace(id=17, user_id=7)
    node_updates = []
    node = SimpleNamespace(
        id=31,
        topic="旧主题",
        knowledge_tags="[]",
        resource_types='["document"]',
        quiz_config='{"count": 5, "threshold": 0.7}',
        teaching_spec=None,
        order_index=2,
    )

    async def refresh_node():
        for fields in node_updates:
            for key, value in fields.items():
                setattr(node, key, value)

    node.refresh_from_db = refresh_node
    monkeypatch.setattr(path_service.LearningPath, "filter", lambda **filters: FakeQuery(stored_path))
    monkeypatch.setattr(
        path_service.PathNode,
        "filter",
        lambda **filters: FakeQuery(node, update_callback=lambda fields: node_updates.append(fields)),
    )
    monkeypatch.setattr(path_service.UserPathProgress, "filter", lambda **filters: FakeQuery())
    explicit_spec = {
        "module": "工程实践",
        "cognitive_level": "创造",
        "learning_goal": "独立完成新主题项目",
        "key_points": ["新知识点"],
        "micro_example": "实现一个最小项目",
    }

    result = await path_service.PathService.update_node(
        17,
        31,
        7,
        topic="新主题",
        teaching_spec=explicit_spec,
    )

    assert json.loads(node_updates[0]["teaching_spec"]) == explicit_spec
    assert result["teaching_spec"] == explicit_spec


class FakeLock:
    def locked(self):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def parse_sse_event(event: str) -> dict:
    return json.loads(event.removeprefix("data:").strip())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_detail"),
    [
        (
            RuntimeError("401 invalid api_key=secret-model-provider-detail"),
            "本章学习材料生成失败，请重试",
        ),
        (
            RuntimeError("完整文档未通过质量检查：文档有效内容不足 900 字符"),
            "完整文档未通过质量检查：文档有效内容不足 900 字符",
        ),
    ],
)
async def test_resource_stream_emits_terminal_safe_error(monkeypatch, failure, expected_detail):
    node = SimpleNamespace(id=31, topic="文档切分")
    progress = SimpleNamespace(id=41)
    saved_resource_ids = []

    async def get_lock(*args):
        return FakeLock()

    async def get_resources(*args):
        return [], ["document"]

    async def get_context(*args):
        return {"subject": "RAG"}

    async def save_resource_ids(progress_record, resource_ids):
        saved_resource_ids.append(list(resource_ids))

    async def failing_stream(**kwargs):
        if False:
            yield ""
        raise failure

    monkeypatch.setattr(path_service.PathNode, "filter", lambda **filters: FakeQuery(node))
    monkeypatch.setattr(path_service.UserPathProgress, "filter", lambda **filters: FakeQuery(progress))
    monkeypatch.setattr(path_service, "get_node_generation_lock", get_lock)
    monkeypatch.setattr(path_service, "get_bound_node_resources", get_resources)
    monkeypatch.setattr(path_service, "build_node_teaching_context", get_context)
    monkeypatch.setattr(path_service, "update_progress_resource_ids", save_resource_ids)
    monkeypatch.setattr(path_service.ResourceService, "generate_stream", failing_stream)

    events = [
        parse_sse_event(event)
        async for event in path_service.PathService.generate_node_resources_stream(17, 31, 7)
    ]

    assert events[-1] == {
        "type": "error",
        "source": "learning_path",
        "path_id": 17,
        "node_id": 31,
        "detail": expected_detail,
        "done": True,
    }
    assert not any(event.get("type") == "done" for event in events)
    assert saved_resource_ids == [[]]
    assert "secret-model-provider-detail" not in events[-1]["detail"]
