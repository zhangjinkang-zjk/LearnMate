"""学习概览「活跃度」单元测试

测试目标：backend/src/service/study/service.py
覆盖范围：
- _summarize_learning_activity 的归日、去重、两个窗口（7 天 / 30 天）
- last_active_date 的日期格式，以及"出了窗口就是 None"的确切含义
- get_stats 真的把 learning_events 与答题记录并起来算，并且不再依赖恒为 0 的学习时长

背景：学习概览原来用 summary.total_study_seconds 回答"最近学过没有"，而 StudySession 的
唯一写入方是 StudyService.heartbeat，前端**从来没调用过** /study/heartbeat，所以那个数
恒为 0、active_days 也跟着恒为 0。改成数 learning_events（它的写入方是真实在跑的：
assessment / node_quiz / resource_read / classroom_chat / chat）。
"""
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.service.study.service import (
    StudyService,
    _ACTIVITY_WINDOW_DAYS,
    _summarize_learning_activity,
)

TODAY = date(2026, 9, 30)
NOON = datetime(2026, 9, 30, 12, 0)
STUDY_MODULE = "backend.src.service.study.service"


def _days_ago(count: int) -> datetime:
    return NOON - timedelta(days=count)


# ═══════════════════════════════════════════════
#  _summarize_learning_activity
# ═══════════════════════════════════════════════

class TestSummarizeLearningActivity:
    def test_empty_input(self):
        assert _summarize_learning_activity([], today=TODAY) == {
            "active_days_7d": 0,
            "last_active_date": None,
            "window_days": _ACTIVITY_WINDOW_DAYS,
        }

    def test_ignores_none(self):
        """一条记录都没有（或取不到时间）时不该炸，也不该凭空说活跃过"""
        result = _summarize_learning_activity([None, None], today=TODAY)
        assert result["active_days_7d"] == 0
        assert result["last_active_date"] is None

    def test_same_day_counted_once(self):
        """一天做十件事只算一天"""
        result = _summarize_learning_activity([NOON - timedelta(hours=h) for h in range(10)], today=TODAY)
        assert result["active_days_7d"] == 1

    def test_seven_distinct_days(self):
        result = _summarize_learning_activity([_days_ago(i) for i in range(7)], today=TODAY)
        assert result["active_days_7d"] == 7
        assert result["last_active_date"] == "2026-09-30"

    def test_eighth_day_falls_out_of_the_week(self):
        """第 8 天前的不算「近 7 天」，但还在 30 天窗内，所以最近学习日期仍报出来"""
        result = _summarize_learning_activity([_days_ago(7)], today=TODAY)
        assert result["active_days_7d"] == 0
        assert result["last_active_date"] == "2026-09-23"

    def test_week_boundary_is_inclusive(self):
        """第 7 天前（近 7 天的第一天）算数"""
        assert _summarize_learning_activity([_days_ago(6)], today=TODAY)["active_days_7d"] == 1

    def test_window_boundary_is_inclusive(self):
        """窗口最后一天仍算，前一天的记录连日期都不报"""
        assert _summarize_learning_activity([_days_ago(_ACTIVITY_WINDOW_DAYS - 1)], today=TODAY)["last_active_date"] == "2026-09-01"

    def test_outside_window_reports_none(self):
        """None 的含义是「窗口内没有学习行为」，不是「从来没学过」——
        这让页面能说"超过 30 天没来"而不是永远显示最后那个陈旧日期。"""
        result = _summarize_learning_activity([_days_ago(_ACTIVITY_WINDOW_DAYS)], today=TODAY)
        assert result["last_active_date"] is None
        assert result["active_days_7d"] == 0

    def test_last_active_is_the_maximum_not_the_first(self):
        """输入不保证有序（两个来源直接拼起来），取的是最晚那天"""
        stamps = [_days_ago(10), _days_ago(2), _days_ago(6)]
        assert _summarize_learning_activity(stamps, today=TODAY)["last_active_date"] == "2026-09-28"

    def test_union_of_two_sources_dedupes(self):
        """同一天既答题又读资料，只算一天"""
        same_day = datetime(2026, 9, 30, 9, 0)
        assert _summarize_learning_activity([same_day, same_day], today=TODAY)["active_days_7d"] == 1

    def test_naive_timestamps_are_read_as_utc(self):
        """naive 时间按 UTC 归日：UTC+8 的 9/30 凌晨 1 点，在 UTC 上是 9/29"""
        tz8 = timezone(timedelta(hours=8))
        stamp = datetime(2026, 9, 30, 1, 0, tzinfo=tz8)
        assert _summarize_learning_activity([stamp], today=TODAY)["last_active_date"] == "2026-09-29"

    def test_last_active_date_is_a_plain_date_string(self):
        """回的是日期不是时间戳：库里存 naive 时间，序列化成时间戳会在浏览器里按本地时区
        解析、整体偏一个时区。日期没有这个陷阱。"""
        value = _summarize_learning_activity([NOON], today=TODAY)["last_active_date"]
        assert value == "2026-09-30"
        assert "T" not in value and "+" not in value and "Z" not in value


# ═══════════════════════════════════════════════
#  get_stats 真的接上了这一路（回归）
# ═══════════════════════════════════════════════

class _Awaitable:
    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _go():
            return self._value
        return _go().__await__()


class _Rows:
    """够用的假查询集：链式方法一律返回自己，await 得到预置的行。"""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.filter_calls = []

    def filter(self, *args, **kwargs):
        self.filter_calls.append(kwargs)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def prefetch_related(self, *args, **kwargs):
        return self

    async def all(self):
        return list(self.rows)

    async def first(self):
        return self.rows[0] if self.rows else None

    def values_list(self, field, flat=False):
        return _Awaitable([getattr(row, field, None) for row in self.rows])


class _Row:
    """答题记录和事件都只用得上这两三个字段，一次给全，免得 get_stats 走到一半炸在别处"""

    def __init__(self, created_at, is_correct=None, session_id=""):
        self.created_at = created_at
        self.is_correct = is_correct
        self.session_id = session_id


class _FakeRadarService:
    async def get(self, user_id):
        return {}


async def _noop(*args, **kwargs):
    return None


async def _empty_guidance(*args, **kwargs):
    return ""


def _patch_study_deps(monkeypatch, *, event_times, exam_times):
    """把 get_stats 摸到的 ORM 与外部服务全部换掉，只留下我们要断言的那条路径"""
    for name in ("StudySession", "KnowledgeMastery", "UserPathProgress", "LearningPath",
                 "GeneratedResource", "ResourceReadStatus", "ResourceCollection"):
        monkeypatch.setattr(f"{STUDY_MODULE}.{name}", _Rows())
    # 答题记录在 get_stats 里本来就整体读进内存，活跃度直接复用这一份
    monkeypatch.setattr(f"{STUDY_MODULE}.ExamRecord", _Rows([_Row(t) for t in exam_times]))
    events = _Rows([_Row(t) for t in event_times])
    monkeypatch.setattr(f"{STUDY_MODULE}.LearningEvent", events)
    monkeypatch.setattr(f"{STUDY_MODULE}.PortraitRadarService", _FakeRadarService())
    monkeypatch.setattr(f"{STUDY_MODULE}.check_and_create_weekly_report", _noop)
    monkeypatch.setattr(f"{STUDY_MODULE}.build_learning_guidance", _empty_guidance)
    return events


class TestGetStatsActivity:
    @pytest.mark.asyncio
    async def test_active_days_comes_from_events_while_study_seconds_stays_zero(self, monkeypatch):
        """核心回归：只在 learning_events 里有活动、StudySession 一条都没有（= 心跳从没被调用
        过的真实情况），活跃度必须仍然数得出来，而学习时长如实报 0。"""
        now = datetime.now(timezone.utc).date()
        recent = datetime.combine(now, time(12, 0))
        _patch_study_deps(
            monkeypatch,
            event_times=[recent - timedelta(days=i) for i in range(3)],
            exam_times=[],
        )

        result = await StudyService.get_stats(1)

        assert result["activity"]["active_days_7d"] == 3
        assert result["activity"]["last_active_date"] == str(now)
        assert result["study_time"]["total_seconds"] == 0
        assert result["study_time"]["active_days"] == 0

    @pytest.mark.asyncio
    async def test_exam_records_are_unioned_in(self, monkeypatch):
        """并集不是替换：只在答题记录里有活动（learning_events 空）的用户也得算数"""
        now = datetime.now(timezone.utc).date()
        recent = datetime.combine(now, time(12, 0))
        _patch_study_deps(
            monkeypatch,
            event_times=[],
            exam_times=[recent - timedelta(days=i) for i in range(2)],
        )

        result = await StudyService.get_stats(1)

        assert result["activity"]["active_days_7d"] == 2

    @pytest.mark.asyncio
    async def test_learning_events_is_actually_queried_with_the_window(self, monkeypatch):
        """防止以后有人把 learning_events 这一路删掉，或把窗口去掉变成全表扫"""
        now = datetime.now(timezone.utc).date()
        events = _patch_study_deps(
            monkeypatch,
            event_times=[datetime.combine(now, time(12, 0))],
            exam_times=[],
        )

        await StudyService.get_stats(1)

        assert events.filter_calls, "没有查询 learning_events"
        assert events.filter_calls[0]["user_id"] == 1
        assert "created_at__gte" in events.filter_calls[0]

    @pytest.mark.asyncio
    async def test_newcomer_reports_zero_without_crashing(self, monkeypatch):
        """什么都没做过的账号：全 0，不抛"""
        _patch_study_deps(monkeypatch, event_times=[], exam_times=[])

        result = await StudyService.get_stats(1)

        assert result["activity"] == {
            "active_days_7d": 0,
            "last_active_date": None,
            "window_days": _ACTIVITY_WINDOW_DAYS,
        }
