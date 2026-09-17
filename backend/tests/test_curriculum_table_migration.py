# -*- coding: utf-8 -*-
"""课程缓存表从「专业×年级」改成「按方向」之后，存量库要能自己跟上。

`generate_schemas()` 只建缺失的**表**，不会改已存在的表：结构变了但没人跑迁移时，
方向拆解一查就撞 MySQL 1054 `Unknown column 'direction'`，把
`/path/generate-from-direction` 直接打成 500（真实发生过一次）。

这里钉三件事：结构过期时重建、本来就是新结构时不动、**其他异常时绝不删表**。
最后一条是重点 —— 一个连不上库的抖动不该变成 DROP TABLE。
"""

import pytest

from backend.src.utils import database


class _FakeConnection:
    """只认「第一条 SQL 会不会抛」这件事，并记下所有执行过的语句。"""

    def __init__(self, first_error: str | None = None, drop_error: str | None = None):
        self.first_error = first_error
        self.drop_error = drop_error
        self.executed: list[str] = []
        self._first = True

    async def execute_query(self, sql: str):
        self.executed.append(sql)
        if self._first:
            self._first = False
            if self.first_error:
                raise Exception(self.first_error)
            return
        if self.drop_error and "DROP" in sql:
            raise Exception(self.drop_error)

    @property
    def dropped(self) -> bool:
        return any("DROP TABLE" in sql for sql in self.executed)


class _FakeTortoise:
    def __init__(self, conn):
        self._conn = conn
        self.schema_runs = 0

    def get_connection(self, name: str):
        return self._conn

    async def generate_schemas(self, *args, **kwargs):
        self.schema_runs += 1


def _patch(monkeypatch, conn):
    fake = _FakeTortoise(conn)
    monkeypatch.setattr(database, "Tortoise", fake)
    return fake


@pytest.mark.asyncio
async def test_a_stale_table_is_rebuilt(monkeypatch):
    """旧结构（缺 direction 列）→ 丢表重建，然后按新模型建回来。"""
    conn = _FakeConnection(first_error='(1054, "Unknown column \'direction\' in \'field list\'")')
    fake = _patch(monkeypatch, conn)

    await database._ensure_curriculum_by_direction_table()

    assert conn.dropped, "旧结构的表没有被重建，方向拆解会一直 500"
    assert fake.schema_runs == 1, "删完没有按新模型把表建回来"


@pytest.mark.asyncio
async def test_a_current_table_is_left_alone(monkeypatch):
    """已经是新结构 → 一句话都不动（这是每次启动都会走的那条路）。"""
    conn = _FakeConnection()
    fake = _patch(monkeypatch, conn)

    await database._ensure_curriculum_by_direction_table()

    assert not conn.dropped
    assert fake.schema_runs == 0
    assert conn.executed == ["SELECT direction FROM curriculum_courses LIMIT 1"]


@pytest.mark.asyncio
async def test_a_missing_table_is_left_to_generate_schemas(monkeypatch):
    """新库（表还不存在）不归这里管：generate_schemas 会按模型建，别多此一举。"""
    conn = _FakeConnection(first_error="(1146, \"Table 'learnmate.curriculum_courses' doesn't exist\")")
    fake = _patch(monkeypatch, conn)

    await database._ensure_curriculum_by_direction_table()

    assert not conn.dropped
    assert fake.schema_runs == 0


@pytest.mark.asyncio
async def test_an_unrelated_failure_never_drops_the_table(monkeypatch):
    """连不上库、权限不够…… 都不该变成 DROP TABLE，异常要原样抛出去。

    这是这段迁移里唯一不可逆的动作：判断放宽成"只要 SELECT 失败就重建"，一次数据库
    抖动就会把表（和里面已经缓存好的课程名）删掉。
    """
    conn = _FakeConnection(first_error="(2003, \"Can't connect to MySQL server on 'db'\")")
    fake = _patch(monkeypatch, conn)

    with pytest.raises(Exception):
        await database._ensure_curriculum_by_direction_table()

    assert not conn.dropped, "非结构问题也把表删了"
    assert fake.schema_runs == 0


@pytest.mark.asyncio
async def test_a_rebuild_failure_is_loud(monkeypatch):
    """重建失败要抛出去，不能装作没事 —— 装作没事的话 500 会推迟到用户点路径生成时才出现。"""
    conn = _FakeConnection(
        first_error='(1054, "Unknown column \'direction\' in \'field list\'")',
        drop_error="(1142, DROP command denied)",
    )
    _patch(monkeypatch, conn)

    with pytest.raises(Exception):
        await database._ensure_curriculum_by_direction_table()


def test_the_migration_is_wired_into_startup():
    """写好的迁移必须真的在 init_db 里被调用 —— 没接上等于没写。"""
    import inspect

    source = inspect.getsource(database.init_db)
    assert "_ensure_curriculum_by_direction_table()" in source
