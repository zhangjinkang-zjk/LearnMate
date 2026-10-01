# -*- coding: utf-8 -*-
"""资源库列表：liked / favorited 原来是循环里的逐条 `.exists()`。

一份资源两次往返，N 份就是 2N —— 同一个函数上面几行的 `read_statuses` 早就是
`resource_id__in=[...]` 的批量做法，两个写法在同一条函数里并排躺着。

这里同时钉住"只有一次查询"和"映射对不对"：只测查询次数的话，把映射写错（比如恒 True）
也能绿；只测映射的话，退回逐条查询也能绿。
"""

from types import SimpleNamespace

import pytest

from backend.src.models import study_model
from backend.src.service.resource import library


class _FakeResource:
    def __init__(self, resource_id, resource_type="document"):
        self.id = resource_id
        self.resource_type = resource_type
        self.topic = f"主题{resource_id}"
        self.content = "正文"
        self.review_passed = True
        self.created_at = "2026-09-30 10:00:00"
        self.view_count = 0
        self.download_count = 0
        self.like_count = 0
        self.favorite_count = 0
        self.cover_url = ""
        self.visibility = "private"
        self.user_id = 9
        self.file_url = ""


class _Query:
    """记录 filter 被调了几次 —— 那就是往返次数。"""

    def __init__(self, rows):
        self._rows = rows
        self.filter_calls = 0
        self.last_kwargs = {}

    def filter(self, **kwargs):
        self.filter_calls += 1
        self.last_kwargs = kwargs
        return self

    def order_by(self, *fields):
        return self

    async def all(self):
        return list(self._rows)

    def values_list(self, field, flat=False):
        values = [getattr(row, field, None) for row in self._rows]

        async def _resolve():
            return values

        return _resolve()

    async def exists(self):
        """留着它是为了让"改回逐条查询"的写法**能跑**：否则变异出来的代码会死在
        AttributeError 上，测试照样红，但红的原因不是"查了 N 次"—— 那样这条回归
        就只是"假件少了个方法"，不是"批量被改回去了"。"""
        return bool(self._rows)


def _patch(monkeypatch, resources, read_rows=(), like_rows=(), collection_rows=()):
    """把四个模型换成假查询。

    **假 `filter` 必须真的调到 `_Query.filter()`**（而不是直接返回那个对象）：否则
    `filter_calls` 永远是 0，"查了几次"这件事就没被观测到 —— 写成 `lambda **kw: q`
    的话，逐条 `.exists()` 和批量 `resource_id__in` 在计数上长得一模一样。
    """
    resource_query = _Query(resources)
    read_query = _Query(list(read_rows))
    like_query = _Query(list(like_rows))
    collection_query = _Query(list(collection_rows))

    monkeypatch.setattr(library, "GeneratedResource", SimpleNamespace(filter=lambda **kw: resource_query.filter(**kw)))
    monkeypatch.setattr(library, "ResourceReadStatus", SimpleNamespace(filter=lambda **kw: read_query.filter(**kw)))
    monkeypatch.setattr(study_model, "ResourceLike", SimpleNamespace(filter=lambda **kw: like_query.filter(**kw)))
    monkeypatch.setattr(study_model, "ResourceCollection", SimpleNamespace(filter=lambda **kw: collection_query.filter(**kw)))
    monkeypatch.setattr(library, "external_video_metadata", lambda record: {})
    return resource_query, read_query, like_query, collection_query


@pytest.mark.asyncio
async def test_liked_and_favorited_are_one_query_each(monkeypatch):
    """核心回归：liked / favorited 各只查一次，不随资源条数增长。"""
    _, _, like_query, collection_query = _patch(
        monkeypatch,
        [_FakeResource(1), _FakeResource(2), _FakeResource(3)],
    )

    items = await library.ResourceLibraryService.list_resources(9)

    assert len(items) == 3
    assert like_query.filter_calls == 1, f"liked 查了 {like_query.filter_calls} 次"
    assert collection_query.filter_calls == 1, f"favorited 查了 {collection_query.filter_calls} 次"


@pytest.mark.asyncio
async def test_the_batch_query_is_scoped_to_this_users_resources(monkeypatch):
    """批量查询要用 resource_id__in 收口，不能退化成"查全表再在内存里挑"。"""
    _, _, like_query, collection_query = _patch(monkeypatch, [_FakeResource(1), _FakeResource(2)])

    await library.ResourceLibraryService.list_resources(9)

    assert like_query.last_kwargs["user_id"] == 9
    assert like_query.last_kwargs["resource_id__in"] == [1, 2]
    assert collection_query.last_kwargs["resource_id__in"] == [1, 2]


@pytest.mark.asyncio
async def test_the_flags_are_per_resource_not_global(monkeypatch):
    """映射必须按 id 落到各自的资源上 —— 这是"只测查询次数"测不到的那一半。"""
    _patch(
        monkeypatch,
        [_FakeResource(1), _FakeResource(2)],
        read_rows=[SimpleNamespace(resource_id=1, is_read=True)],
        like_rows=[SimpleNamespace(resource_id=2)],
        collection_rows=[SimpleNamespace(resource_id=1)],
    )

    items = {item["resource_id"]: item for item in await library.ResourceLibraryService.list_resources(9)}

    assert items[1]["liked"] is False
    assert items[1]["favorited"] is True
    assert items[1]["is_read"] is True
    assert items[2]["liked"] is True
    assert items[2]["favorited"] is False
    assert items[2]["is_read"] is False


@pytest.mark.asyncio
async def test_an_empty_library_does_not_query_the_flag_tables(monkeypatch):
    """一份资源都没有时不该拿空 `resource_id__in=[]` 去问三张表。"""
    _, _, like_query, collection_query = _patch(monkeypatch, [])

    assert await library.ResourceLibraryService.list_resources(9) == []
    assert like_query.filter_calls == 0
    assert collection_query.filter_calls == 0
