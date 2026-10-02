# -*- coding: utf-8 -*-
"""用户自建智能体的定时触发：时区错 8 小时 + 两种 cron 写法静默失效。

三个缺陷叠在同一条链路上（`utils/scheduler.py`）：

1. **墙上时间用的是 UTC，不是上海。** `datetime.now(tz.utc).replace(tzinfo=None)` 里的
   `replace` 只撕掉时区标记、不做换算，变量名却叫 `now_shanghai`。用户把 cron 设成
   `0 9 * * *`（想早上 9 点收推送），实际在北京时间 17 点触发。
   注意 APScheduler 自己的 `timezone="Asia/Shanghai"` 管不到这里 —— 这条链路是手写匹配器。
2. **`a-b/n` 解析不出来。** `5-10/2` 走进 `int("5-10")` → ValueError，被外层吞成"不匹配"：
   一次都不会触发，而且日志里一个字都没有。
3. **dom 与 dow 同时被限定时该是"或"。** 标准 cron 里 `0 9 1 * 1` = 每月 1 号**或**每周一；
   原来五个字段一起进 `all()`，要求两个都满足，那类表达式永远不触发。

顺带钉住：表达式写坏时**不能拖垮整轮扫描**（`*/0` 会 ZeroDivisionError，原来那层
`except (ValueError, IndexError)` 接不住，会连带后面所有智能体一起不执行）。
"""

import pytest

from backend.src.utils import scheduler as scheduler_module
from backend.src.utils.scheduler import (
    _cron_field_matches,
    _cron_matches,
    _execute_scheduled_agents,
    _shanghai_now,
)


# ── 1. 时区 ───────────────────────────────────────────

def test_utc_midnight_becomes_shanghai_morning():
    """UTC 01:00 就是上海 09:00 —— 这正是 cron `0 9 * * *` 该触发的时刻。"""
    from datetime import datetime, timezone

    shanghai = _shanghai_now(datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc))

    assert shanghai.hour == 9
    assert shanghai.minute == 0


def test_the_returned_moment_carries_the_shanghai_offset():
    """带时区，不是"撕掉标记的裸时间" —— 后面要进提示词，模型得看得出这是哪一刻。"""
    from datetime import datetime, timezone

    shanghai = _shanghai_now(datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc))

    assert shanghai.tzinfo is not None
    assert shanghai.utcoffset().total_seconds() == 8 * 3600
    assert shanghai.isoformat().endswith("+08:00")


def test_the_old_wall_clock_reading_is_off_by_eight_hours():
    """把差 8 小时这件事本身写下来：UTC 的 9 点 ≠ 上海的 9 点。

    原来那个写法取到的就是 UTC 的 9 点（`replace(tzinfo=None)` 后 hour 仍是 9），
    而用户要的上海 9 点是 UTC 的 1 点。差的就是这 8 小时。
    """
    from datetime import datetime, timezone

    utc_nine = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)

    assert _shanghai_now(utc_nine).hour == 17
    assert utc_nine.replace(tzinfo=None).hour == 9


# ── 2/3. 字段匹配 ─────────────────────────────────────

def test_star_matches_everything():
    assert _cron_field_matches("*", 0)
    assert _cron_field_matches("*", 59)


def test_step_from_star():
    assert _cron_field_matches("*/15", 0)
    assert _cron_field_matches("*/15", 45)
    assert not _cron_field_matches("*/15", 7)


def test_range_with_step_is_parsed_not_swallowed():
    """`5-10/2` = 5、7、9。原来这一条会 ValueError → 被吞成"永不匹配"。"""
    assert [_cron_field_matches("5-10/2", m) for m in range(5, 11)] == [
        True, False, True, False, True, False,
    ]


def test_plain_range_and_single_value():
    assert _cron_field_matches("5-10", 7)
    assert not _cron_field_matches("5-10", 11)
    assert _cron_field_matches("9", 9)
    assert not _cron_field_matches("9", 10)


def test_a_missing_first_chunk_does_not_hide_a_later_match():
    """`*/5,7`：7 点也该触发。

    原来的循环在 `*/5` 这个分支不命中时直接 `return False`，逗号后面的 `7` 永远没机会。
    """
    assert _cron_field_matches("*/5,7", 7)
    assert _cron_field_matches("*/5,7", 10)
    assert not _cron_field_matches("*/5,7", 11)


def test_a_broken_field_raises_instead_of_silently_never_firing():
    """解析不了就抛 —— 由调用方决定记账，别在这里吞成一个"不匹配"。"""
    with pytest.raises(ValueError):
        _cron_field_matches("abc", 1)
    with pytest.raises(ValueError):
        _cron_field_matches("*/0", 1)


# ── 3. dom / dow 的"或" ────────────────────────────────

def _matches(expr, *, minute=0, hour=9, dom=1, month=9, dow=1):
    return _cron_matches(expr, minute, hour, dom, month, dow)


def test_every_day_when_both_day_fields_are_star():
    assert _matches("0 9 * * *", dom=15, dow=3)


def test_only_dom_restricted_follows_dom():
    assert _matches("0 9 1 * *", dom=1, dow=3)
    assert not _matches("0 9 1 * *", dom=2, dow=1)


def test_only_dow_restricted_follows_dow():
    assert _matches("0 9 * * 1", dom=1, dow=1)
    assert not _matches("0 9 * * 1", dom=1, dow=2)


def test_both_day_fields_restricted_is_an_or():
    """`0 9 1 * 1` = 每月 1 号**或**每周一。

    这是本次修的第二处：原来五个字段一起 all()，要求两个都满足 —— 只有 1 号恰好是周一
    那天才会触发（一年一两次），用户看到的就是"这个定时任务基本不响"。
    """
    assert _matches("0 9 1 * 1", dom=1, dow=3), "1 号（不是周一）该触发"
    assert _matches("0 9 1 * 1", dom=15, dow=1), "周一（不是 1 号）该触发"
    assert not _matches("0 9 1 * 1", dom=15, dow=3)


def test_minute_and_hour_still_have_to_match():
    assert not _matches("0 9 * * *", minute=1, hour=9)
    assert not _matches("0 9 * * *", minute=0, hour=17)


def test_a_four_field_expression_is_rejected():
    with pytest.raises(ValueError):
        _cron_matches("0 9 * *", 0, 9, 1, 9, 1)


# ── 整轮扫描：坏表达式不能拖垮别人 ─────────────────────

class _Agent:
    def __init__(self, agent_id, cron):
        self.id = agent_id
        self.name = f"智能体{agent_id}"
        self.user_id = agent_id
        self.persona = ""
        self.schedule = f'{{"cron": "{cron}", "prompt": "提醒我复习"}}'


class _AgentQuery:
    def __init__(self, agents):
        self._agents = agents

    def exclude(self, **kwargs):
        return self

    async def all(self):
        return list(self._agents)


class _FakeNotification:
    created: list = []

    @classmethod
    async def create(cls, **kwargs):
        cls.created.append(kwargs)


class _FakeResp:
    content = "该复习了"


class _FakeLlm:
    calls: list = []

    @classmethod
    async def ainvoke(cls, prompt):
        cls.calls.append(prompt)
        return _FakeResp()


def _patch_scan(monkeypatch, agents, now):
    from backend.src.models import notification_model, user_agent_model
    from backend.src.ai_core import llm_config

    class _FakeUserAgent:
        @staticmethod
        def filter(**kwargs):
            return _AgentQuery(agents)

    monkeypatch.setattr(user_agent_model, "UserAgent", _FakeUserAgent)
    monkeypatch.setattr(notification_model, "Notification", _FakeNotification)
    monkeypatch.setattr(llm_config, "llm", _FakeLlm)
    monkeypatch.setattr(scheduler_module, "_shanghai_now", lambda *a, **k: now)
    monkeypatch.setattr(scheduler_module, "_last_agent_fire", {})
    monkeypatch.setattr(scheduler_module, "_malformed_cron_warned", set())
    _FakeLlm.calls.clear()
    _FakeNotification.created.clear()


@pytest.mark.asyncio
async def test_a_broken_cron_does_not_stop_the_other_agents(monkeypatch, caplog):
    """`*/0` 会让原来那层 `except (ValueError, IndexError)` 接不住（ZeroDivisionError），
    整轮扫描直接抛到最外层 —— 后面所有智能体这一分钟都不执行。"""
    from datetime import datetime

    _patch_scan(monkeypatch, [
        _Agent(1, "*/0 * * * *"),
        _Agent(2, "30 9 * * *"),
    ], datetime(2026, 9, 30, 9, 30))

    with caplog.at_level("WARNING"):
        await _execute_scheduled_agents()

    assert len(_FakeLlm.calls) == 1, "坏表达式把后面那个正常智能体也带停了"
    assert "cron 表达式无法解析" in caplog.text
    assert _FakeNotification.created[0]["title"] == "[智能体2] 定时推送"


@pytest.mark.asyncio
async def test_the_bad_expression_warning_is_logged_once_per_agent(monkeypatch, caplog):
    """扫描是每分钟一次：不记账就会每分钟刷一条同样的警告。"""
    from datetime import datetime

    _patch_scan(monkeypatch, [_Agent(1, "*/0 * * * *")], datetime(2026, 9, 30, 9, 30))

    with caplog.at_level("WARNING"):
        await _execute_scheduled_agents()
        first_round = caplog.text.count("cron 表达式无法解析")
        await _execute_scheduled_agents()
        second_round = caplog.text.count("cron 表达式无法解析")

    assert first_round == 1
    assert second_round == 1, "第二轮又报了一次"


@pytest.mark.asyncio
async def test_the_scheduled_agent_fires_at_the_shanghai_wall_clock_hour(monkeypatch):
    """端到端：UTC 01:00（= 上海 09:00）时，`0 9 * * *` 的智能体应当触发。

    这条用的是真的 `_shanghai_now`（没被 patch 掉），所以它同时守着上面那处时区换算。
    """
    from datetime import datetime, timezone
    from backend.src.models import notification_model, user_agent_model
    from backend.src.ai_core import llm_config

    class _FakeUserAgent:
        @staticmethod
        def filter(**kwargs):
            return _AgentQuery([_Agent(1, "0 9 * * *")])

    monkeypatch.setattr(user_agent_model, "UserAgent", _FakeUserAgent)
    monkeypatch.setattr(notification_model, "Notification", _FakeNotification)
    monkeypatch.setattr(llm_config, "llm", _FakeLlm)
    monkeypatch.setattr(scheduler_module, "_last_agent_fire", {})

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(scheduler_module, "datetime", _FixedDateTime)
    _FakeLlm.calls.clear()

    await _execute_scheduled_agents()

    assert len(_FakeLlm.calls) == 1, "上海 9 点没触发（时区又错回去了？）"
