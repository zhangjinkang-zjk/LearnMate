"""雷达图「坚持」维度单元测试

测试目标：backend/src/service/portrait/service.py
覆盖范围：
- _active_day 的时区归一
- _persistence_score 的去重、时间窗、封顶
- _compute_locked 的「坚持」取答题记录与 learning_events 的**并集**

背景（这次修的 bug）：原实现只遍历 ExamRecord，导致连续 30 天看资料 / 做节点测验 /
课堂对话但**没考试**的用户，「坚持」得分是 0。而 learning_events 表里恰好记着
resource_read / node_quiz / classroom_chat 这些事件。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.service.portrait.service import (
    PortraitRadarService,
    _active_day,
    _persistence_score,
)

PORTRAIT_MODULE = "backend.src.service.portrait.service"
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
CUTOFF = (NOW - timedelta(days=30)).date()


# ═══════════════════════════════════════════════
#  _active_day
# ═══════════════════════════════════════════════

class TestActiveDay:
    def test_aware_datetime(self):
        assert _active_day(datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)).isoformat() == "2026-09-20"

    def test_naive_treated_as_utc(self):
        assert _active_day(datetime(2026, 9, 20, 8, 0)).isoformat() == "2026-09-20"

    def test_none_is_none(self):
        assert _active_day(None) is None

    def test_utc_normalization_across_midnight(self):
        """UTC+8 的凌晨 1 点，在 UTC 上还是前一天"""
        tz8 = timezone(timedelta(hours=8))
        # 2026-09-20 01:00 +08:00 == 2026-09-19 17:00 UTC
        assert _active_day(datetime(2026, 9, 20, 1, 0, tzinfo=tz8)).isoformat() == "2026-09-19"


# ═══════════════════════════════════════════════
#  _persistence_score
# ═══════════════════════════════════════════════

class TestPersistenceScore:
    def test_empty(self):
        assert _persistence_score([], CUTOFF) == 0

    def test_ignores_none(self):
        assert _persistence_score([None, None], CUTOFF) == 0

    def test_same_day_counted_once(self):
        """一天做十件事只算一天"""
        stamps = [NOW - timedelta(hours=h) for h in range(10)]
        assert _persistence_score(stamps, CUTOFF) == round(1 / 30 * 100)

    def test_ten_distinct_days(self):
        stamps = [NOW - timedelta(days=i) for i in range(10)]
        assert _persistence_score(stamps, CUTOFF) == round(10 / 30 * 100)

    def test_thirty_distinct_days_caps_at_100(self):
        stamps = [NOW - timedelta(days=i) for i in range(40)]
        assert _persistence_score(stamps, CUTOFF) == 100

    def test_outside_window_excluded(self):
        """31 天前的不算"""
        stamps = [NOW - timedelta(days=31), NOW - timedelta(days=1)]
        assert _persistence_score(stamps, CUTOFF) == round(1 / 30 * 100)

    def test_mixed_sources_union(self):
        """两个来源的同一天不重复计"""
        answer_days = [NOW - timedelta(days=i) for i in range(5)]
        event_days = [NOW - timedelta(days=i) for i in range(5, 10)]
        assert _persistence_score(answer_days + event_days, CUTOFF) == round(10 / 30 * 100)


# ═══════════════════════════════════════════════
#  _compute_locked 的「坚持」取值来源（回归）
# ═══════════════════════════════════════════════

class _Awaitable:
    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _go():
            return self._value
        return _go().__await__()


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def prefetch_related(self, *args, **kwargs):
        return self

    async def all(self):
        return list(self._rows)

    async def first(self):
        return self._rows[0] if self._rows else None

    def values_list(self, field, flat=False):
        return _Awaitable([getattr(row, field) for row in self._rows])


class _FakeModel:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.filter_calls = []

    def filter(self, **kwargs):
        self.filter_calls.append(kwargs)
        return _FakeQuery(self.rows)


class _FakeUser:
    def __init__(self):
        self.filter = lambda **kw: _FakeQuery([object()])


class _FakeRadar:
    def __init__(self):
        self.id = 1
        self.user_id = 1
        self.updated_at = NOW
        for field in ("memory", "understanding", "application", "analysis", "breadth", "persistence"):
            setattr(self, field, 0)

    async def save(self):
        return None


class _FakeExamRecord:
    """只有 created_at —— 其余维度会拿到空列表，不影响 persistence 断言"""

    def __init__(self, created_at):
        self.created_at = created_at
        self.is_correct = True
        self.question = None


def _patch_or_models(monkeypatch, exam_records, event_times):
    """把 _compute_locked 依赖的 ORM 全部换成假实现"""
    import backend.src.models.exam_model as exam_model
    import backend.src.models.portrait_radar_model as radar_model

    learning_event = _FakeModel([type("E", (), {"created_at": t})() for t in event_times])
    monkeypatch.setattr(f"{PORTRAIT_MODULE}.LearningEvent", learning_event)
    monkeypatch.setattr(f"{PORTRAIT_MODULE}.User", _FakeUser())
    monkeypatch.setattr(exam_model, "ExamRecord", _FakeModel(exam_records))
    monkeypatch.setattr(exam_model, "KnowledgeMastery", _FakeModel([]))
    monkeypatch.setattr(radar_model, "PortraitRadar", _FakeModel([_FakeRadar()]))
    return learning_event


def _dimension(result, key):
    return next(d for d in result["dimensions"] if d["key"] == key)


class TestComputeLockedPersistence:
    @pytest.mark.asyncio
    async def test_reading_only_user_scores_above_zero(self, monkeypatch):
        """核心回归：只在 learning_events 里有活动、一场考试都没考过的用户，坚持度不该是 0"""
        days = [NOW - timedelta(days=i) for i in range(10)]
        _patch_or_models(monkeypatch, exam_records=[], event_times=days)

        result = await PortraitRadarService._compute_locked(1)

        assert _dimension(result, "persistence")["score"] == round(10 / 30 * 100)

    @pytest.mark.asyncio
    async def test_exam_only_user_still_counts(self, monkeypatch):
        """并集不是替换：只有答题记录的用户也得算数"""
        records = [_FakeExamRecord(NOW - timedelta(days=i)) for i in range(6)]
        _patch_or_models(monkeypatch, exam_records=records, event_times=[])

        result = await PortraitRadarService._compute_locked(1)

        assert _dimension(result, "persistence")["score"] == round(6 / 30 * 100)

    @pytest.mark.asyncio
    async def test_both_sources_deduped(self, monkeypatch):
        """同一天既考试又看资料，只算一天"""
        same_day = NOW - timedelta(days=1)
        records = [_FakeExamRecord(same_day)]
        _patch_or_models(monkeypatch, exam_records=records, event_times=[same_day])

        result = await PortraitRadarService._compute_locked(1)

        assert _dimension(result, "persistence")["score"] == round(1 / 30 * 100)

    @pytest.mark.asyncio
    async def test_learning_events_is_actually_queried(self, monkeypatch):
        """防止以后有人把 learning_events 这一路删掉"""
        fake = _patch_or_models(monkeypatch, exam_records=[], event_times=[NOW])

        await PortraitRadarService._compute_locked(1)

        assert fake.filter_calls, "没有查询 learning_events"
        assert fake.filter_calls[0]["user_id"] == 1
