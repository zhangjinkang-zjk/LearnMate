# -*- coding: utf-8 -*-
"""APScheduler 定时任务调度器（AsyncIO 模式）"""

import asyncio
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from backend.src.utils.constants import STATIC_DIR, CLEANUP_AGE_SECONDS

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_last_agent_fire: dict[int, float] = {}  # (user_id, agent_id) → 上次执行时间戳，防重复触发
_malformed_cron_warned: set[int] = set()  # 已经报过"cron 解析不了"的 agent，避免每分钟刷日志

# 用户自建智能体的 cron 走**手写匹配器**（下面几个函数），不是 APScheduler。
# 所以 APScheduler 那个 `timezone="Asia/Shanghai"` 管不到它们，墙上时间得自己换。
_SCHEDULE_TIMEZONE = "Asia/Shanghai"


def _shanghai_now(moment: datetime | None = None) -> datetime:
    """当前时刻的上海墙上时间（**带时区**）。

    这里原来写的是 `datetime.now(tz.utc).replace(tzinfo=None)` —— `replace` 只撕掉时区
    标记、不做换算，于是那个变量名虽然叫 now_shanghai，值其实是 UTC 的墙上时间：用户把
    智能体的 cron 设成 `0 9 * * *`（想早上 9 点），实际在北京时间 **17 点** 触发。
    """
    return (moment or datetime.now(timezone.utc)).astimezone(ZoneInfo(_SCHEDULE_TIMEZONE))


def _cleanup_old_files():
    """删除 static 目录下超过 1 天的生成文件（音频缓存、视频、演示、PPT）"""
    now = time.time()
    dirs = [
        STATIC_DIR / "audio" / "_cache",
        STATIC_DIR / "videos",
        STATIC_DIR / "presentations",
        STATIC_DIR / "ppt",
    ]
    cleaned = 0
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            try:
                if f.is_file() and now - f.stat().st_mtime > CLEANUP_AGE_SECONDS:
                    f.unlink()
                    cleaned += 1
            except OSError:
                logger.debug("已忽略异常 backend/src/utils/scheduler.py:33", exc_info=True)
        if d.name != "_cache" and d.parent.name == "audio":
            continue
    audio_dir = STATIC_DIR / "audio"
    if audio_dir.is_dir():
        for sub in audio_dir.iterdir():
            if sub.is_dir() and sub.name != "_cache":
                try:
                    if not any(sub.iterdir()):
                        sub.rmdir()
                except OSError:
                    logger.debug("已忽略异常 backend/src/utils/scheduler.py:46", exc_info=True)
    if cleaned:
        logger.info("清理过期文件 %d 个", cleaned)


def _cron_field_matches(field: str, current: int) -> bool:
    """单个 cron 字段匹配，支持 `*`、`a`、`a-b`、`*/n`、`a-b/n`，逗号分隔任意组合。

    两个原来会静默失效的写法：

    - `a-b/n`（如 `5-10/2`）走的是 `int("5-10")` → ValueError。原来的外层把它吞成"不匹配"，
      于是那条 cron **一次都不会触发，也没有任何日志**。
    - 逗号分隔里只要有一个 `*/n` 分支不命中就直接 `return False`，后面的字段再没机会看。
      现在统一成"逐个候选试，命中就返回"，不提前收摊。

    表达式写坏时**抛 ValueError**（不吞）—— 由调用方决定记账还是忽略，这个函数只管解析。
    """
    for chunk in str(field).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        base, _, step_text = chunk.partition("/")
        base = base.strip()
        step = int(step_text) if step_text.strip() else 1
        if step <= 0:
            raise ValueError(f"cron 步长必须为正数: {chunk!r}")
        if base == "*":
            if current % step == 0:
                return True
            continue
        if "-" in base:
            low_text, high_text = base.split("-", 1)
        else:
            low_text = high_text = base
        low, high = int(low_text), int(high_text)
        if low <= current <= high and (current - low) % step == 0:
            return True
    return False


def _cron_matches(cron_expr: str, now_minute: int, now_hour: int,
                  now_dom: int, now_month: int, now_dow: int) -> bool:
    """简易 cron 五字段匹配（minute hour dom month dow）。

    只支持 `*`、数字、区间、步长和逗号，没有 L/#/W 这类扩展，也没有名字（`MON`、`JAN`）。
    表达式解析不了时抛 ValueError，由调用方记账。
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron 必须是五字段，收到 {len(parts)} 个: {cron_expr!r}")

    if not _cron_field_matches(parts[0], now_minute):
        return False
    if not _cron_field_matches(parts[1], now_hour):
        return False
    if not _cron_field_matches(parts[3], now_month):
        return False

    # dom 与 dow **同时**被限定时是"或"：标准 cron 里 `0 9 1 * 1` 表示"每月 1 号**或**每周一"。
    # 原来五个字段一起丢进 all()，等于要求两个都满足 —— 那类表达式一次都不会触发。
    dom_field, dow_field = parts[2].strip(), parts[4].strip()
    dom_ok = _cron_field_matches(dom_field, now_dom)
    dow_ok = _cron_field_matches(dow_field, now_dow)
    if dom_field == "*":
        return dow_ok if dow_field != "*" else True
    if dow_field == "*":
        return dom_ok
    return dom_ok or dow_ok


async def _execute_scheduled_agents():
    """每分钟扫描 UserAgent 表，执行匹配当前时间的定时任务"""
    now_shanghai = _shanghai_now()
    minute, hour, dom, month, dow = (
        now_shanghai.minute, now_shanghai.hour, now_shanghai.day,
        now_shanghai.month, (now_shanghai.weekday() + 1) % 7,  # 0=周日→6
    )

    try:
        from backend.src.models.user_agent_model import UserAgent
        from backend.src.ai_core.llm_config import llm

        agents = await UserAgent.filter(enabled=True).exclude(schedule__isnull=True).all()
        if not agents:
            return

        for agent in agents:
            try:
                sched = json.loads(agent.schedule or "{}")
            except (json.JSONDecodeError, TypeError):
                continue

            cron_expr = sched.get("cron", "").strip()
            prompt = sched.get("prompt", "").strip()
            if not cron_expr or not prompt:
                continue

            try:
                matched = _cron_matches(cron_expr, minute, hour, dom, month, dow)
            except ValueError:
                # 表达式写坏了 = 这个智能体永远不会触发。原来它静默返回 False，用户那边只是
                # "到点没动静"，日志里什么都没有。这里报一次（同一个 agent 只报一次，不限流
                # 的话每分钟一条）。
                if agent.id not in _malformed_cron_warned:
                    _malformed_cron_warned.add(agent.id)
                    logger.warning(
                        "智能体 cron 表达式无法解析，永远不会触发 agent_id=%s cron=%r",
                        agent.id, cron_expr,
                    )
                continue
            if not matched:
                continue

            # 防重复：同一智能体每分钟最多执行一次
            key = agent.id
            last_fire = _last_agent_fire.get(key, 0)
            if time.monotonic() - last_fire < 59:
                continue
            _last_agent_fire[key] = time.monotonic()

            logger.info("智能体定时触发 agent_id=%d name=%s user_id=%d cron=%s",
                        agent.id, agent.name, agent.user_id, cron_expr)

            # 构建 system prompt（用户自定义 persona 或默认）
            system = agent.persona or "你是 LearnMate，一个 AI 学习导师。"
            full_prompt = f"{system}\n\n当前时间：{now_shanghai.isoformat()}\n\n{prompt}"

            try:
                response = await asyncio.wait_for(llm.ainvoke(full_prompt), timeout=60)
                result_text = str(response.content)[:500]
            except asyncio.TimeoutError:
                result_text = "智能体定时任务执行超时"
            except Exception:
                logger.exception("智能体定时执行 LLM 失败 agent_id=%d", agent.id)
                continue

            # 写入通知记录，前端轮询或 SSE 推送时可见
            try:
                from backend.src.models.notification_model import Notification
                await Notification.create(
                    target_user_id=agent.user_id,
                    title=f"[{agent.name}] 定时推送",
                    content=result_text or f"定时任务「{prompt[:30]}...」已执行",
                    type="system",
                )
            except Exception:
                logger.debug("智能体通知写入失败 agent_id=%d", agent.id, exc_info=True)

    except Exception:
        logger.exception("智能体定时扫描异常")


def get_scheduler() -> AsyncIOScheduler:
    """获取全局调度器（懒初始化）"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            timezone="Asia/Shanghai",
            job_defaults={"coalesce": True, "max_instances": 1},
        )
    return _scheduler


def start():
    sched = get_scheduler()

    from backend.src.service.notification.service import (
        generate_weekly_report_and_ai_tip,
    )

    # 每天凌晨 3 点清理超过 1 天的静态文件
    sched.add_job(
        _cleanup_old_files,
        trigger="cron",
        hour=3,
        minute=13,
        id="cleanup_old_files",
        name="清理过期静态文件",
        replace_existing=True,
    )

    # 每周一 9:00 生成周报 + AI 建议
    sched.add_job(
        generate_weekly_report_and_ai_tip,
        trigger="cron",
        day_of_week="mon",
        hour=9,
        minute=7,
        id="weekly_report_and_ai_tip",
        name="周报与AI建议",
        replace_existing=True,
    )

    # 每分钟扫描用户自建智能体的定时任务
    sched.add_job(
        _execute_scheduled_agents,
        trigger="cron",
        minute="*",
        id="user_agent_schedule",
        name="用户智能体定时触发",
        replace_existing=True,
    )

    sched.start()
    logger.info("定时任务已启动：清理过期文件（每日3:13）+ 周报（周一9:07）+ 智能体定时（每分钟）")


def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("定时任务已停止")
