# -*- coding: utf-8 -*-
"""长期记忆 KV 的"按查询加权"：加权加在了被截断的集合上，等于没加。

`retrieve_kvs` 原来是：

    .order_by("-confidence", "-updated_at").limit(top_k).all()   # ← 先在 SQL 里切出 12 条
    ...
    if s and s.lower() in q: boost = 1                            # ← 再在这 12 条里重排

顺序反了。高相关但置信度中等的记忆**永远进不了候选**，所以"命中 query 的排前面"只在
最可信的那 12 条内部生效 —— 换句话说是"给最可信的 12 条换个顺序"，而不是"按查询挑"。

下面第一条测试用 `top_k=1` 把它变成可观察的行为差异：候选池是 1 条时，boost 无论怎么算
都只能返回那 1 条；候选池放开之后，相关的那条才上得来。
"""

import pytest

from backend.src.service.memory import retrieval


class _FakeKv:
    def __init__(self, key, value, confidence, subjects=None, scope="user", source_group_id=0):
        self.key = key
        self.value = value
        self.confidence = confidence
        self.subjects = subjects
        self.scope = scope
        self.source_group_id = source_group_id


class _KvQuery:
    """按真实 SQL 的语义来：order_by 排序、limit **真的截断**。

    limit 必须真的截断 —— 假实现如果不截断，上面那个"候选池只有 1 条"的场景就构造不出来，
    这条回归也就永远绿着。
    """

    def __init__(self, rows):
        self._rows = list(rows)
        self.limit_arg = None

    def order_by(self, *fields):
        self._rows.sort(key=lambda row: -row.confidence)
        return self

    def limit(self, count):
        self.limit_arg = count
        self._rows = self._rows[:count]
        return self

    async def all(self):
        return list(self._rows)


def _patch_kv(monkeypatch, rows):
    query = _KvQuery(rows)

    class _FakeMemoryKV:
        @staticmethod
        def filter(*args, **kwargs):
            return query

    monkeypatch.setattr(retrieval, "MemoryKV", _FakeMemoryKV)
    return query


@pytest.mark.asyncio
async def test_a_relevant_memory_beats_a_more_confident_irrelevant_one(monkeypatch):
    """核心回归：命中 query 的那条要排前面，哪怕它置信度更低。"""
    _patch_kv(monkeypatch, [
        _FakeKv("学习节奏", "偏好晚上学", 0.95, subjects=["作息"]),
        _FakeKv("公差标注", "习惯先查基准", 0.31, subjects=["机械制图"]),
    ])

    result = await retrieval.retrieve_kvs(1, 2, query="机械制图的公差怎么查", top_k=1)

    assert result == ["公差标注：习惯先查基准"], (
        "高相关低置信的那条被候选池挡在外面了 —— 加权又加在了截断之后"
    )


@pytest.mark.asyncio
async def test_the_candidate_pool_is_not_sliced_to_top_k(monkeypatch):
    """候选池不能是 top_k：那正是上面那条失效的原因。"""
    query = _patch_kv(monkeypatch, [_FakeKv("甲", "x", 0.5)])

    await retrieval.retrieve_kvs(1, 2, query="甲", top_k=3)

    assert query.limit_arg == retrieval._KV_CANDIDATE_CEILING
    assert query.limit_arg > 3


@pytest.mark.asyncio
async def test_without_a_query_the_confidence_order_is_kept(monkeypatch):
    """没有 query（或 query 不命中任何 subjects）时，就是"最可信的排前面"，别改坏。"""
    _patch_kv(monkeypatch, [
        _FakeKv("低", "x", 0.2, subjects=["甲"]),
        _FakeKv("高", "x", 0.9, subjects=["乙"]),
    ])

    assert await retrieval.retrieve_kvs(1, 2, query="", top_k=2) == ["高：x", "低：x"]
    assert await retrieval.retrieve_kvs(1, 2, query="完全不相干的问法", top_k=2) == ["高：x", "低：x"]


@pytest.mark.asyncio
async def test_top_k_still_caps_the_output(monkeypatch):
    """加权只改顺序，不改条数 —— 放开候选池不等于把召回量放大。"""
    _patch_kv(monkeypatch, [
        _FakeKv("一", "x", 0.9, subjects=["甲"]),
        _FakeKv("二", "x", 0.8, subjects=["甲"]),
        _FakeKv("三", "x", 0.7, subjects=["甲"]),
    ])

    assert len(await retrieval.retrieve_kvs(1, 2, query="甲", top_k=2)) == 2
