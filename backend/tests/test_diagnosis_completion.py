# -*- coding: utf-8 -*-
"""Regression tests for finishing the onboarding ability diagnosis.

``e1d895f4`` added ``asyncio.create_task(...)`` to the last-answer branch of
``answer()`` without adding ``import asyncio``.  Every call that answered the
final question therefore raised ``NameError``, so the diagnosis could never be
completed: the stream reported "诊断服务暂时不可用" instead of ``finished``.
"""

import asyncio
from types import SimpleNamespace

import pytest

from backend.src.service.diagnosis import service as diagnosis_service


class _AsyncValue:
    """Stands in for a Tortoise foreign key, which is awaited: ``await user.picture``."""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _get():
            return self._value

        return _get().__await__()


class FakeQuery:
    def __init__(self, *, first_value=None, records=None):
        self.first_value = first_value
        self.records = list(records or [])

    def order_by(self, *_args):
        return self

    def prefetch_related(self, *_args):
        return self

    async def first(self):
        return self.first_value

    async def all(self):
        return self.records


class FakeRecord:
    """ExamRecord 形态：题干挂在 question 外键上。"""

    def __init__(self, question_id, is_correct=None, content="题干", user_answer=""):
        self.question_id = question_id
        self.is_correct = is_correct
        self.question = SimpleNamespace(content=content)
        self.user_answer = user_answer


class FakeQuestion:
    """ExamQuestion 形态：``_safe_question`` 直接读它的字段。"""

    def __init__(self, question_id, content):
        self.id = question_id
        self.content = content
        self.question_type = "short_answer"
        self.options = None
        self.difficulty = "medium"
        self.knowledge_tags = None


def _picture():
    return SimpleNamespace(traits='{"onboarding": {"direction": "数据分析", "goal": "就业"}}')


@pytest.mark.asyncio
async def test_answering_the_last_question_finishes_without_nameerror(monkeypatch):
    """The finish branch ran ``asyncio.create_task`` against an unimported module."""
    pending = FakeRecord(1)                                   # 本题未作答
    # max_steps 用满，answer() 才会走收尾分支。
    answered = [FakeRecord(i, is_correct=True) for i in (1, 2, 3)]
    scheduled = []

    def filter_records(**filters):
        if "question_id" in filters:
            return FakeQuery(first_value=pending)
        return FakeQuery(records=answered)

    async def fake_submit(*_args, **_kwargs):
        return {"session_summary": {"percentage": 66.7, "correct_count": 2}}

    async def fake_generate_paths(user_id, direction, goal):
        scheduled.append((user_id, direction, goal))

    async def fake_init_db():
        return None

    monkeypatch.setattr(diagnosis_service, "init_db", fake_init_db)
    monkeypatch.setattr(diagnosis_service.ExamRecord, "filter", filter_records)
    monkeypatch.setattr(diagnosis_service, "_submit_open_answer", fake_submit)
    monkeypatch.setattr(diagnosis_service, "_generate_paths_after_diagnosis", fake_generate_paths)
    monkeypatch.setattr(
        diagnosis_service,
        "parse_traits",
        lambda _raw: {"onboarding": {"direction": "数据分析", "goal": "就业"}},
    )
    monkeypatch.setattr(
        diagnosis_service.User,
        "filter",
        lambda **_filters: FakeQuery(first_value=SimpleNamespace(picture=_AsyncValue(_picture()))),
    )

    result = await diagnosis_service.answer(9, "sess-1", 1, "我的回答", None, max_steps=3)
    await asyncio.sleep(0)   # 让 create_task 排出的任务真正跑一次

    assert result["finished"] is True
    assert result["result"]["percentage"] == 66.7
    # 任务真的被排进去了 —— 这正是当初抛 NameError 的那一行。
    assert scheduled == [(9, "数据分析", "就业")]


@pytest.mark.asyncio
async def test_answering_a_non_final_question_still_returns_the_next_one(monkeypatch):
    """The finish branch must not swallow the normal per-question return path."""
    pending = FakeRecord(1)
    answered = [FakeRecord(1, is_correct=True)]
    created = {}

    def filter_records(**filters):
        if "question_id" in filters:
            return FakeQuery(first_value=pending)
        return FakeQuery(records=answered)

    async def fake_submit(*_args, **_kwargs):
        return {"session_summary": {"percentage": 100.0, "correct_count": 1}}

    async def fake_create_question(user_id, session_id, payload):
        created["called"] = True
        return FakeQuestion(3, "下一题")

    async def fake_init_db():
        return None

    async def fake_generate_question(*_args, **_kwargs):
        return {"content": "下一题", "reference_answer": "答案"}

    monkeypatch.setattr(diagnosis_service, "init_db", fake_init_db)
    monkeypatch.setattr(diagnosis_service.ExamRecord, "filter", filter_records)
    monkeypatch.setattr(diagnosis_service, "_submit_open_answer", fake_submit)
    monkeypatch.setattr(diagnosis_service, "_create_question", fake_create_question)
    monkeypatch.setattr(diagnosis_service, "_generate_question", fake_generate_question)
    monkeypatch.setattr(diagnosis_service, "parse_traits", lambda _raw: {"onboarding": {}})
    monkeypatch.setattr(
        diagnosis_service.User,
        "filter",
        lambda **_filters: FakeQuery(first_value=SimpleNamespace(picture=_AsyncValue(_picture()))),
    )

    result = await diagnosis_service.answer(9, "sess-1", 1, "我的回答", None, max_steps=3)

    assert result["finished"] is False
    assert result["question"]["content"] == "下一题"
    assert created.get("called") is True
