"""Authorization regression tests for resource study status writes."""

from __future__ import annotations

import pytest

from backend.src.service.study import service as study_service


class FakeQuerySet:
    def __init__(self, record=None):
        self.record = record

    async def first(self):
        return self.record


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["mark_read", "mark_unread"])
async def test_resource_status_write_requires_read_access(monkeypatch, method_name):
    captured = {}

    def filter_resource(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeQuerySet(None)

    monkeypatch.setattr(study_service.GeneratedResource, "filter", filter_resource)

    method = getattr(study_service.StudyService, method_name)
    with pytest.raises(ValueError, match="资源不存在"):
        await method(user_id=7, resource_id=99)

    identity_filter, visibility_filter = captured["args"]
    assert identity_filter.filters == {"id": 99}
    assert visibility_filter.join_type == "OR"
    assert {tuple(item.filters.items()) for item in visibility_filter.children} == {
        (("user_id", 7),),
        (("visibility", "public"),),
    }
    assert captured["kwargs"] == {}
