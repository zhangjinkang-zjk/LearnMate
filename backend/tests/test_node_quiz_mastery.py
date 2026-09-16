# -*- coding: utf-8 -*-
"""Regression tests for knowledge-mastery tracking on the path quiz flow.

The path node quiz used to write only ``ExamRecord``.  ``submit_node_quiz``
then calls ``update_portrait_from_mastery()``, which reads ``KnowledgeMastery``
and returns early when it is empty — so the mastery table only ever held what
the one-off diagnostic quiz had written, and the portrait never moved after a
node quiz no matter how the learner answered.
"""

from types import SimpleNamespace

import pytest

from backend.src.service.exam import service as exam_service
from backend.src.service.path import service as path_service


class FakeMastery:
    def __init__(self, tag: str):
        self.knowledge_tag = tag
        self.total_attempts = 0
        self.correct_count = 0
        self.mastery_level = "beginner"
        self.last_practiced_at = None
        self.saved = 0

    async def save(self):
        self.saved += 1


class FakeRecord:
    """Stands in for an ``ExamRecord`` with its ``question`` prefetched."""

    def __init__(self, question_id, question, user_id=9):
        self.question_id = question_id
        self.question = question
        self.user_id = user_id
        self.user_answer = None
        self.is_correct = None
        self.score = None
        self.saved_fields = []

    async def save(self, update_fields=None):
        self.saved_fields.append(list(update_fields or []))


def _question(tags, question_type="single_choice", answer="A"):
    return SimpleNamespace(
        question_type=question_type,
        answer=answer,
        knowledge_tags=tags,
    )


def _fake_store(monkeypatch, store=None):
    """Route ``KnowledgeMastery.get_or_create`` to an in-memory dict."""
    store = {} if store is None else store
    calls = []

    async def fake_get_or_create(user_id, knowledge_tag, defaults=None):
        calls.append((user_id, knowledge_tag))
        mastery = store.setdefault(knowledge_tag, FakeMastery(knowledge_tag))
        return mastery, True

    monkeypatch.setattr(exam_service.KnowledgeMastery, "get_or_create", fake_get_or_create)
    return store, calls


@pytest.mark.asyncio
async def test_node_quiz_submission_updates_knowledge_mastery(monkeypatch):
    """The gap itself: answering a node quiz must move the mastery rows."""
    store, calls = _fake_store(monkeypatch)
    records = [
        FakeRecord(1, _question('["极限定义"]')),
        FakeRecord(2, _question('["极限定义", "左右极限"]')),
    ]

    await path_service.PathService._apply_quiz_submission(
        records,
        {"1": "A", "2": "B"},
    )

    assert calls == [(9, "极限定义"), (9, "极限定义"), (9, "左右极限")]
    assert store["极限定义"].total_attempts == 2
    assert store["极限定义"].correct_count == 1
    assert store["极限定义"].mastery_level == "learning"
    assert store["左右极限"].total_attempts == 1
    assert store["左右极限"].correct_count == 0
    assert store["左右极限"].mastery_level == "beginner"


@pytest.mark.asyncio
async def test_node_quiz_grades_records_before_touching_mastery(monkeypatch):
    """Mastery must follow the graded result, not a stale ``is_correct``."""
    store, _ = _fake_store(monkeypatch)
    record = FakeRecord(1, _question('["导数"]'))
    assert record.is_correct is None

    await path_service.PathService._apply_quiz_submission([record], {"1": "A"})

    assert record.is_correct is True
    assert record.score == 1.0
    assert record.saved_fields == [["user_answer", "is_correct", "score"]]
    assert store["导数"].correct_count == 1


@pytest.mark.asyncio
async def test_untagged_questions_never_write_a_mastery_row(monkeypatch):
    """An empty tag list must not create a row keyed on an empty string."""
    store, calls = _fake_store(monkeypatch)
    records = [
        FakeRecord(1, _question(None)),
        FakeRecord(2, _question("[]")),
        FakeRecord(3, None),
    ]

    await path_service.PathService._apply_quiz_submission(records, {"1": "A", "2": "A"})

    assert calls == []
    assert store == {}


@pytest.mark.parametrize(
    "tags,expected",
    [
        (None, []),
        ("", []),
        ("[]", []),
        ('["  极限  ", "", "  ", 42]', ["极限", "42"]),
        ('{"not": "a list"}', []),
        ("not json at all", []),
        ("A" * 200, []),
    ],
)
def test_question_tags_normalizes_database_values(tags, expected):
    assert exam_service._question_tags(tags) == expected


def test_question_tags_caps_the_tag_count():
    """One question cannot fan out into an unbounded number of rows."""
    raw = "[" + ",".join(f'"tag{i}"' for i in range(20)) + "]"
    assert exam_service._question_tags(raw) == [f"tag{i}" for i in range(12)]


def test_question_tags_truncates_to_the_column_width():
    raw = '["' + "长" * 200 + '"]'
    tags = exam_service._question_tags(raw)
    assert len(tags) == 1
    assert len(tags[0]) == 128


@pytest.mark.parametrize(
    "correct_count,total_attempts,is_correct,expected_level",
    [
        (0, 0, True, "mastered"),
        (9, 10, True, "mastered"),
        (7, 9, True, "proficient"),
        (6, 9, True, "proficient"),
        (4, 10, True, "learning"),
        (3, 9, True, "learning"),
        (2, 9, True, "beginner"),
        (0, 0, False, "beginner"),
        (2, 9, False, "beginner"),
    ],
)
@pytest.mark.asyncio
async def test_mastery_level_follows_running_accuracy(
    monkeypatch, correct_count, total_attempts, is_correct, expected_level
):
    seeded = FakeMastery("极限定义")
    seeded.correct_count = correct_count
    seeded.total_attempts = total_attempts
    store, _ = _fake_store(monkeypatch, {"极限定义": seeded})

    tags = await exam_service.update_knowledge_mastery(9, '["极限定义"]', is_correct)

    assert tags == ["极限定义"]
    assert store["极限定义"].total_attempts == total_attempts + 1
    assert store["极限定义"].correct_count == correct_count + (1 if is_correct else 0)
    assert store["极限定义"].mastery_level == expected_level
    assert store["极限定义"].saved == 1
