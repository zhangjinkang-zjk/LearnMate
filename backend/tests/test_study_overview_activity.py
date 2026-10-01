"""学习概览「活跃度」单元测试

测试目标：backend/src/service/study/service.py
覆盖范围：
- _summarize_learning_activity 的归日、去重、本周窗口（周一为第一天）与 30 天查询边界
- last_active_date 的日期格式，以及"出了窗口就是 None"的确切含义
- get_stats 真的把 learning_events 与答题记录并起来算，并且不再依赖恒为 0 的学习时长

背景：学习概览原来用 summary.total_study_seconds 回答"最近学过没有"，而 StudySession 的
唯一写入方是 StudyService.heartbeat，前端**从来没调用过** /study/heartbeat，所以那个数
恒为 0、active_days 也跟着恒为 0。改成数 learning_events（它的写入方是真实在跑的：
assessment / node_quiz / resource_read / classroom_chat / chat）。
"""
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.service.study.service import (
    StudyService,
    _ACTIVITY_WINDOW_DAYS,
    _metadata_duration,
    _read_seconds_in_week,
    _summarize_learning_activity,
    _summarize_week_trend,
    _summarize_week_work,
    _TREND_WEEKS,
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
        result = _summarize_learning_activity([], today=TODAY)
        assert {k: v for k, v in result.items() if k != "weekly_days"} == {
            "active_days_this_week": 0,
            "week_start_date": "2026-09-28",
            "last_active_date": None,
            "window_days": _ACTIVITY_WINDOW_DAYS,
        }
        # 一个人都没来过的账号，七格照样给全 —— 页面要画的是日历，"哪天没来"正是它要说的事。
        assert len(result["weekly_days"]) == 7
        assert all(day["active"] is False for day in result["weekly_days"])

    def test_ignores_none(self):
        """一条记录都没有（或取不到时间）时不该炸，也不该凭空说活跃过"""
        result = _summarize_learning_activity([None, None], today=TODAY)
        assert result["active_days_this_week"] == 0
        assert result["last_active_date"] is None

    def test_same_day_counted_once(self):
        """一天做十件事只算一天"""
        result = _summarize_learning_activity([NOON - timedelta(hours=h) for h in range(10)], today=TODAY)
        assert result["active_days_this_week"] == 1

    def test_counts_the_calendar_week_not_a_rolling_seven_days(self):
        """核心回归：TODAY 是 2026-09-30 周三，本周从 09-28 周一算起。

        这个人这 7 天**天天都来过**。滚动窗口会报 7；日历周只报 3（周一、周二、周三）。
        报的就是这 3 —— 学生按"这周"记自己的账，不按"往前数七天"。
        """
        result = _summarize_learning_activity([_days_ago(i) for i in range(7)], today=TODAY)

        assert result["active_days_this_week"] == 3
        assert result["week_start_date"] == "2026-09-28"

    def test_the_week_starts_on_monday(self):
        """边界落在周一：本周一算数，上周日不算。"""
        monday = _summarize_learning_activity([_days_ago(2)], today=TODAY)
        sunday = _summarize_learning_activity([_days_ago(3)], today=TODAY)

        assert monday["active_days_this_week"] == 1
        assert sunday["active_days_this_week"] == 0
        # 上周日那次学习仍然要报出来 —— 只是不算进"本周"
        assert sunday["last_active_date"] == "2026-09-27"

    def test_a_monday_today_counts_only_itself(self):
        """周一当天：本周就是 1 天（昨天是上周日，不算）。"""
        result = _summarize_learning_activity(
            [datetime(2026, 9, 28, 12, 0), datetime(2026, 9, 27, 12, 0)],
            today=date(2026, 9, 28),
        )

        assert result["active_days_this_week"] == 1
        assert result["week_start_date"] == "2026-09-28"

    def test_future_dates_do_not_inflate_the_week(self):
        """时钟偏移混进来的未来日期不能把本周天数算超。"""
        result = _summarize_learning_activity([NOON + timedelta(days=1)], today=TODAY)

        assert result["active_days_this_week"] == 0

    def test_a_day_in_a_previous_week_is_not_counted(self):
        """上周四来过的，本周报 0，但最近学习日期仍是那天（还在 30 天窗内）"""
        result = _summarize_learning_activity([_days_ago(6)], today=TODAY)
        assert result["active_days_this_week"] == 0
        assert result["last_active_date"] == "2026-09-24"

    def test_window_boundary_is_inclusive(self):
        """窗口最后一天仍算，前一天的记录连日期都不报"""
        assert _summarize_learning_activity([_days_ago(_ACTIVITY_WINDOW_DAYS - 1)], today=TODAY)["last_active_date"] == "2026-09-01"

    def test_outside_window_reports_none(self):
        """None 的含义是「窗口内没有学习行为」，不是「从来没学过」——
        这让页面能说"超过 30 天没来"而不是永远显示最后那个陈旧日期。"""
        result = _summarize_learning_activity([_days_ago(_ACTIVITY_WINDOW_DAYS)], today=TODAY)
        assert result["last_active_date"] is None
        assert result["active_days_this_week"] == 0

    def test_last_active_is_the_maximum_not_the_first(self):
        """输入不保证有序（两个来源直接拼起来），取的是最晚那天"""
        stamps = [_days_ago(10), _days_ago(2), _days_ago(6)]
        assert _summarize_learning_activity(stamps, today=TODAY)["last_active_date"] == "2026-09-28"

    def test_union_of_two_sources_dedupes(self):
        """同一天既答题又读资料，只算一天"""
        same_day = datetime(2026, 9, 30, 9, 0)
        assert _summarize_learning_activity([same_day, same_day], today=TODAY)["active_days_this_week"] == 1

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
#  _read_seconds_in_week / _metadata_duration
# ═══════════════════════════════════════════════

class TestReadSecondsInWeek:
    def _event(self, when, seconds=None, event_type="resource_read"):
        meta = None if seconds is None else json.dumps({"resource_id": 1, "duration_seconds": seconds})
        return (when, event_type, meta)

    def test_empty(self):
        assert _read_seconds_in_week([], today=TODAY) == 0

    def test_adds_up_increments_within_the_week(self):
        """前端每 30 秒上报一次**增量**，所以这里要加，不能取最后一次的值。"""
        events = [self._event(_days_ago(i), 1800) for i in range(3)]

        assert _read_seconds_in_week(events, today=TODAY) == 5400

    def test_days_from_a_previous_week_are_not_counted(self):
        """上周四读的那 40 分钟不算进本周。"""
        week = self._event(_days_ago(2), 1800)
        last_week = self._event(_days_ago(6), 2400)

        assert _read_seconds_in_week([week, last_week], today=TODAY) == 1800

    def test_future_events_are_not_counted(self):
        assert _read_seconds_in_week([self._event(NOON + timedelta(days=1), 600)], today=TODAY) == 0

    def test_only_resource_read_events_carry_time(self):
        """测验 / 课堂 / 对话都不记时 —— 它们身上就算挂了 duration_seconds 也不算数，
        否则这个数就从"读了多久"变成了一个来源不明的"学了多久"。"""
        events = [
            self._event(NOON, 600, event_type="node_quiz"),
            self._event(NOON, 900, event_type="classroom_chat"),
            self._event(NOON, 300, event_type="resource_read"),
        ]

        assert _read_seconds_in_week(events, today=TODAY) == 300

    def test_a_missing_duration_is_zero_not_an_error(self):
        assert _read_seconds_in_week([self._event(NOON)], today=TODAY) == 0

    @pytest.mark.parametrize("metadata", [
        None, "", "not json", "[]", '"文字"', '{"duration_seconds": "abc"}', '{"duration_seconds": -50}',
    ])
    def test_metadata_shapes_that_are_not_a_duration(self, metadata):
        """metadata 是 JSON **文本**列，脏数据不该让整个总览接口 500。"""
        assert _metadata_duration(metadata) == 0

    def test_metadata_accepts_a_plain_dict_too(self):
        """ORM 偶尔会把它反序列化成 dict 递过来。"""
        assert _metadata_duration({"duration_seconds": 120}) == 120

    def test_a_naive_timestamp_is_read_as_utc_here_too(self):
        """归日和数活跃天数走同一条 active_day，不能在这里另写一套本地时区。"""
        tz8 = timezone(timedelta(hours=8))
        # UTC+8 的 10-01 凌晨 1 点 = UTC 的 09-30 17 点，仍在本周（周一 09-28 起）
        stamp = datetime(2026, 10, 1, 1, 0, tzinfo=tz8)

        assert _read_seconds_in_week([self._event(stamp, 600)], today=date(2026, 10, 1)) == 600


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

    def values_list(self, *fields, flat=False):
        if len(fields) == 1:
            values = [getattr(row, fields[0], None) for row in self.rows]
        else:
            values = [tuple(getattr(row, field, None) for field in fields) for row in self.rows]
        return _Awaitable(values)


class _Row:
    """答题记录和事件都用得上几个字段，一次给全，免得 get_stats 走到一半炸在别处。

    `event_type` 默认 `resource_read`、`metadata` 默认 None —— 也就是"有这次学习行为、
    但没记时长"，读时长的那些断言各自显式传值。
    """

    def __init__(self, created_at, is_correct=None, session_id="", event_type="resource_read", metadata=None):
        self.created_at = created_at
        self.is_correct = is_correct
        self.session_id = session_id
        self.event_type = event_type
        self.metadata = metadata


class _FakeRadarService:
    async def get(self, user_id):
        return {}


async def _noop(*args, **kwargs):
    return None


async def _empty_guidance(*args, **kwargs):
    return ""


def _patch_study_deps(monkeypatch, *, event_times=(), exam_times=(), event_rows=None):
    """把 get_stats 摸到的 ORM 与外部服务全部换掉，只留下我们要断言的那条路径"""
    for name in ("StudySession", "KnowledgeMastery", "UserPathProgress", "LearningPath",
                 "GeneratedResource", "ResourceReadStatus", "ResourceCollection"):
        monkeypatch.setattr(f"{STUDY_MODULE}.{name}", _Rows())
    # 答题记录在 get_stats 里本来就整体读进内存，活跃度直接复用这一份
    monkeypatch.setattr(f"{STUDY_MODULE}.ExamRecord", _Rows([_Row(t) for t in exam_times]))
    # event_rows 给需要带 event_type / metadata 的用例（读时长那几条）；否则按时间戳造。
    events = _Rows(list(event_rows) if event_rows is not None else [_Row(t) for t in event_times])
    monkeypatch.setattr(f"{STUDY_MODULE}.LearningEvent", events)
    monkeypatch.setattr(f"{STUDY_MODULE}.PortraitRadarService", _FakeRadarService())
    monkeypatch.setattr(f"{STUDY_MODULE}.check_and_create_weekly_report", _noop)
    # get_stats 现在把已取到的雷达交给 _from_radar 那一支渲染，不再让 helper 自己再取一次
    monkeypatch.setattr(f"{STUDY_MODULE}.build_learning_guidance_from_radar", _empty_guidance)
    return events


class TestGetStatsActivity:
    @pytest.mark.asyncio
    async def test_active_days_comes_from_events_while_study_seconds_stays_zero(self, monkeypatch):
        """核心回归：只在 learning_events 里有活动、StudySession 一条都没有（= 心跳从没被调用
        过的真实情况），活跃度必须仍然数得出来，而学习时长如实报 0。"""
        now = datetime.now(timezone.utc).date()
        noon = datetime.combine(now, time(12, 0))
        # 「今天」和「7 天前」这两笔都是**与星期几无关**的：今天必然落在本周，
        # 7 天前必然落在上一个自然周。用「今天往前数 3 天」会随运行日是周几而变
        # （周一跑就是 1 天），是条会间歇性变红的测试。
        _patch_study_deps(
            monkeypatch,
            event_times=[noon, noon - timedelta(days=7)],
            exam_times=[],
        )

        result = await StudyService.get_stats(1)

        assert result["activity"]["active_days_this_week"] == 1
        assert result["activity"]["last_active_date"] == str(now)
        assert result["study_time"]["total_seconds"] == 0
        assert result["study_time"]["active_days"] == 0

    @pytest.mark.asyncio
    async def test_exam_records_are_unioned_in(self, monkeypatch):
        """并集不是替换：只在答题记录里有活动（learning_events 空）的用户也得算数"""
        now = datetime.now(timezone.utc).date()
        _patch_study_deps(
            monkeypatch,
            event_times=[],
            exam_times=[datetime.combine(now, time(12, 0))],
        )

        result = await StudyService.get_stats(1)

        assert result["activity"]["active_days_this_week"] == 1

    @pytest.mark.asyncio
    async def test_read_seconds_are_alive_where_total_study_seconds_is_dead(self, monkeypatch):
        """核心回归：本周读了 45 分钟，而"学习总时长"仍然是 0。

        这两个数**同时**出现在这一页上，必须是同一个数的两个来源各自如实：
        `read_seconds_this_week` 从带时间戳的阅读增量加出来是真的；
        `summary.total_study_seconds` 恒为 0 也是真的（那条链路没人接）。页面据此说
        "读了 45 分钟"，而不去说"学习了 0 小时"。
        """
        now = datetime.now(timezone.utc).date()
        noon = datetime.combine(now, time(12, 0))

        def read(seconds, *, when=None, event_type="resource_read"):
            return _Row(when or noon, event_type=event_type,
                        metadata=json.dumps({"resource_id": 1, "duration_seconds": seconds}))

        _patch_study_deps(monkeypatch, event_rows=[
            read(1800),
            read(900),
            # 上周读的 100 分钟不算进本周
            read(6000, when=noon - timedelta(days=7)),
            # 测验即使带着时长也不能算进"阅读"
            read(3000, event_type="node_quiz"),
        ])

        result = await StudyService.get_stats(1)

        assert result["activity"]["read_seconds_this_week"] == 2700
        assert result["study_time"]["total_seconds"] == 0

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

        # `week_start_date` 对新人**也**是有的 —— 就算一天没来过，本周的起点也客观存在，
        # 页面要据此说「本周还没来过」。日界用的是 get_stats 传进去的 UTC 当天。
        today = datetime.now(timezone.utc).date()
        week_start = today - timedelta(days=today.weekday())
        assert {k: v for k, v in result["activity"].items() if k not in ("weekly_days", "week_trend")} == {
            "active_days_this_week": 0,
            "read_seconds_this_week": 0,
            "questions_this_week": 0,
            "quizzes_passed_this_week": 0,
            "week_start_date": str(week_start),
            "last_active_date": None,
            "window_days": _ACTIVITY_WINDOW_DAYS,
        }
        assert [day["date"] for day in result["activity"]["weekly_days"]] == [
            str(week_start + timedelta(days=offset)) for offset in range(7)
        ]
        # 走势图对新人也是六根**空柱**而不是空数组：页面据此判断"还没开始学"，
        # 然后换掉整张图。给空数组的话页面分不清"没数据"和"接口没给这个字段"。
        assert [bucket["active_days"] for bucket in result["activity"]["week_trend"]] == [0] * _TREND_WEEKS


class _CountingRadar:
    """每次 `get` 都记账，并始终返回同一份 dict —— 复用与否能靠对象身份看出来。"""

    def __init__(self):
        self.calls = 0
        self.payload = {
            "radar_id": 1,
            "dimensions": [
                {"key": "memory", "label": "记忆", "score": 30, "desc": ""},
                {"key": "analysis", "label": "分析", "score": 45, "desc": ""},
            ],
            "updated_at": "2026-09-30 00:00:00",
        }

    async def get(self, user_id):
        self.calls += 1
        return self.payload


class TestStatsRadarIsComputedOnce:
    @pytest.mark.asyncio
    async def test_one_stats_request_computes_the_radar_once(self, monkeypatch):
        """弱项维度和学习指导必须共用同一份雷达。

        雷达没有缓存分支，每次都是六维全量重算 + 落库。这里原来是两次：`build_learning_guidance`
        内部又取了一次；而 `/study/overview` 除了调 `get_stats` 还要自己再取一次 —— 打开一次
        学习概览就是三次全量重算。
        """
        _patch_study_deps(monkeypatch, event_times=[], exam_times=[])
        radar = _CountingRadar()
        monkeypatch.setattr(f"{STUDY_MODULE}.PortraitRadarService", radar)
        seen: list = []

        async def fake_guidance(user_id, radar_data):
            seen.append(radar_data)
            return ""

        monkeypatch.setattr(f"{STUDY_MODULE}.build_learning_guidance_from_radar", fake_guidance)

        result = await StudyService.get_stats(1)

        assert radar.calls == 1, f"一次 get_stats 算了 {radar.calls} 次雷达"
        assert seen == [radar.payload], "学习指导拿到的不是上面已经算好的那份（只能是又算了一遍）"
        # 顺带确认弱项维度那条支路真的跑了 —— 否则上面两行可能是"整块都没执行"
        radar_tags = [p["tag"] for p in result["weak_points"] if p["source"] == "radar"]
        assert radar_tags == ["记忆(简单题)", "分析(多选题)"]


# ── 这一组的两个工厂 ──
# `_summarize_week_work` 收的是 get_stats 里那两张表在内存中的形状：答题记录是对象
# （要看 `.created_at` / `.is_correct`），事件是 `(created_at, event_type, metadata)` 三元组。

def _record(when, judged=True):
    """`is_correct` 为 None = 还没判分（简答题），不算进"答了 N 题"。"""
    return _Row(when, is_correct=True if judged else None)


def _event(event_type, payload=None, raw="__from_payload__"):
    metadata = json.dumps(payload, ensure_ascii=False) if raw == "__from_payload__" else raw
    return (NOON, event_type, metadata)


# ═══════════════════════════════════════════════
# 本周七格（学习概览页脚那条日历）
# ═══════════════════════════════════════════════

class TestWeeklyDays:
    """`weekly_days` 是给页面画「周一→周日」那排格子用的。

    **七格一起给，不给"活跃的那几天"** —— 缺掉的那几天正是这一项要说的信息。这一条
    是它和 `active_days_this_week`（只出一个数）的区别所在，也是它存在的理由。
    """

    def test_all_seven_days_start_on_monday(self):
        days = _summarize_learning_activity([], today=TODAY)["weekly_days"]

        assert [d["date"] for d in days] == [
            "2026-09-28", "2026-09-29", "2026-09-30",
            "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
        ]

    def test_only_today_is_flagged_as_today(self):
        days = _summarize_learning_activity([], today=TODAY)["weekly_days"]

        assert [d["date"] for d in days if d["is_today"]] == [str(TODAY)]

    def test_a_gap_in_the_middle_is_visible(self):
        """来了一天、隔一天、又来一天 —— 中间那个洞必须画得出来。

        这正是「本周来了 2 天」说不出口的那件事：那 2 天是不是连着的。
        """
        days = _summarize_learning_activity(
            [_days_ago(2), _days_ago(0)], today=TODAY,
        )["weekly_days"]
        active = {d["date"]: d["active"] for d in days}

        assert active["2026-09-28"] is True
        assert active["2026-09-29"] is False
        assert active["2026-09-30"] is True

    def test_days_after_today_are_not_active(self):
        """后半周还没到，格子照画，但一定是未激活的 —— 不能因为时钟偏移把明天点亮。"""
        days = _summarize_learning_activity(
            [datetime(2026, 10, 2, 9, 0)], today=TODAY,
        )["weekly_days"]

        assert {d["date"]: d["active"] for d in days}["2026-10-02"] is False

    def test_last_week_does_not_leak_into_this_week(self):
        """上周日（9-27）不属于本周 —— 它连格子都不该有，更不能点亮。"""
        days = _summarize_learning_activity([_days_ago(3)], today=TODAY)["weekly_days"]

        assert all(d["active"] is False for d in days)
        assert "2026-09-27" not in [d["date"] for d in days]


# ═══════════════════════════════════════════════
# 本周做了多少：答题数 / 通过的节点测验数
# ═══════════════════════════════════════════════

class TestWeekWork:
    """`_summarize_week_work` 用的两张表在 `get_stats` 里早就整个读进内存了，
    所以它一个额外查询都不发 —— 这一组是纯函数测试，不碰数据库。
    """

    def test_counts_only_judged_answers(self):
        judged = [_record(_days_ago(1)), _record(_days_ago(2))]
        unjudged = [_record(_days_ago(1), judged=False)]

        result = _summarize_week_work(judged + unjudged, [], today=TODAY)

        # 简答题没判分时 `is_correct` 是 None，算进去会和正确率的分母对不上。
        assert result["questions_this_week"] == 2

    def test_ignores_answers_from_last_week(self):
        result = _summarize_week_work([_record(_days_ago(8))], [], today=TODAY)
        assert result["questions_this_week"] == 0

    def test_counts_only_node_quizzes_that_passed(self):
        events = [
            _event("node_quiz", payload={"passed": True}),
            _event("node_quiz", payload={"passed": False}),
            # 交卷不是"过了一关"，不参与
            _event("assessment", payload={"passed": True}),
            _event("resource_read", payload={"duration_seconds": 600}),
        ]

        assert _summarize_week_work([], events, today=TODAY)["quizzes_passed_this_week"] == 1

    def test_broken_metadata_does_not_count_and_does_not_raise(self):
        events = [
            _event("node_quiz", raw="{不是 JSON"),
            _event("node_quiz", raw=None),
            _event("node_quiz", raw='"一个字符串"'),
        ]

        assert _summarize_week_work([], events, today=TODAY)["quizzes_passed_this_week"] == 0

    def test_nothing_this_week_is_zero_not_an_error(self):
        assert _summarize_week_work([], [], today=TODAY) == {
            "questions_this_week": 0,
            "quizzes_passed_this_week": 0,
        }


# ═══════════════════════════════════════════════
# 每周学习天数（学习概览页脚那张走势图）
# ═══════════════════════════════════════════════

class TestWeekTrend:
    """`week_trend` 是给页面画柱状图用的：每周有几天在学习，从早到晚排队。

    它数**天数**而不是记录数，也不是"答了几题"：只读资料、只在课堂上提问的人，
    用答题量画出来是一片空白，那是在说他没学。口径必须和 `active_days_this_week`
    完全一致 —— 图上最右边那根柱子就是那一排七格里点亮的格数。
    """

    def test_six_buckets_oldest_first_each_a_monday(self):
        result = _summarize_week_trend([], today=TODAY)

        assert len(result) == _TREND_WEEKS == 6
        assert [bucket["active_days"] for bucket in result] == [0] * 6
        starts = [bucket["week_start"] for bucket in result]
        assert starts == sorted(starts), "横轴必须从早到晚，否则柱子的左右会反"
        assert all(date.fromisoformat(value).weekday() == 0 for value in starts)
        # TODAY = 2026-09-30 是周三，本周一 = 09-28
        assert starts[-1] == "2026-09-28"

    def test_same_day_many_records_counts_once(self):
        """一天里做十件事仍然只算"这一天来过"，不是十个活跃日"""
        result = _summarize_week_trend([NOON, NOON, NOON, _days_ago(0)], today=TODAY)

        assert result[-1]["active_days"] == 1

    def test_each_week_lands_in_its_own_bucket(self):
        result = _summarize_week_trend([_days_ago(0), _days_ago(7), _days_ago(14)], today=TODAY)

        assert [bucket["active_days"] for bucket in result] == [0, 0, 0, 1, 1, 1]

    def test_a_week_with_nothing_keeps_its_slot(self):
        """没来的那几周给 0 而不是跳过 —— 缺桶会让横轴撒谎，相邻两根柱子看着挨着，
        中间其实隔了好几周。"""
        result = _summarize_week_trend([_days_ago(0), _days_ago(28)], today=TODAY)

        assert [bucket["active_days"] for bucket in result] == [0, 1, 0, 0, 0, 1]

    def test_two_days_in_one_week_count_twice(self):
        result = _summarize_week_trend([_days_ago(0), _days_ago(1)], today=TODAY)

        # 09-29（周二）和 09-30（周三）都在 09-28 那一周
        assert result[-1]["active_days"] == 2

    def test_the_oldest_bucket_boundary(self):
        """最早那根柱子是 08-24 那一周：落在它里面算，落在它前面那周不算"""
        inside = _summarize_week_trend([datetime(2026, 8, 24, 9, 0)], today=TODAY)
        before = _summarize_week_trend([datetime(2026, 8, 23, 9, 0)], today=TODAY)

        assert inside[0]["active_days"] == 1
        assert before[0]["active_days"] == 0
        assert sum(bucket["active_days"] for bucket in before) == 0

    def test_future_timestamps_are_ignored(self):
        """时钟偏移混进来的未来日期不画进柱子（也不许把本周那根顶到 8 天）"""
        result = _summarize_week_trend([_days_ago(0), NOON + timedelta(days=3)], today=TODAY)

        assert result[-1]["active_days"] == 1

    def test_none_is_safe(self):
        result = _summarize_week_trend([None, None], today=TODAY)

        assert all(bucket["active_days"] == 0 for bucket in result)

    def test_agrees_with_the_week_strip(self):
        """右边那根柱子 == 上面那排七格里点亮的格数。两处对同一周给不出不同的答案。"""
        stamps = [_days_ago(0), _days_ago(1), _days_ago(2), _days_ago(9), NOON + timedelta(days=2)]

        strip = _summarize_learning_activity(stamps, today=TODAY)
        trend = _summarize_week_trend(stamps, today=TODAY)

        assert trend[-1]["active_days"] == strip["active_days_this_week"] == 3
        assert sum(1 for day in strip["weekly_days"] if day["active"]) == 3
