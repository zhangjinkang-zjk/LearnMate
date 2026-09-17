# -*- coding: utf-8 -*-
"""视频讲解轮询：作业消失时不能一直空转。

现场表现：基础讲解页点「视频讲解」一直转圈，12 分钟后才报"耗时过长"，而且没有任何原因。

查到的链条（`GET /path/107/video` 实测回 `{"status":"idle","error":""}`）：
- 视频是后台作业，作业登记在**进程内存**里（service/path/path_video_jobs.py）；
- 后端一重启，正在跑的作业就没了；失败的作业也只保留 10 分钟（`_TERMINAL_TTL_SECONDS`）；
- 这两种情况下，`get_path_video` 只能回一句 "idle"（= 从没生成过），失败原因已经查不到了；
- 而前端拿到 `generating` 之后就**只 GET 不重发**，于是一路空转到 12 分钟上限。

这份测试钉的是前端那一侧：轮询循环里必须能对"作业没了"的状态重新发起生成，且要有
重试预算和总时限，不能变成死循环。
"""

import re
from pathlib import Path

import pytest

from backend.src.service.path import service as path_service

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "pages" / "learning" / "FundamentalsPage.vue"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def poll_loop(page: str) -> str:
    """截出 pollPathVideo 里那个 while 循环。"""
    start = page.index("while (!video?.file_url)")
    end = page.index("videoResource.value = {", start)
    return page[start:end]


def test_the_restart_statuses_are_the_ones_the_backend_actually_returns(page):
    """前端认的"作业没了"状态，必须是后端真的会吐出来的那几种。"""
    matched = re.search(r"const VIDEO_RESTART_STATUSES = \[([^\]]+)\]", page)
    assert matched, "FundamentalsPage 里找不到 VIDEO_RESTART_STATUSES"
    statuses = {item.strip().strip("'\"") for item in matched.group(1).split(",") if item.strip()}
    assert statuses == {"idle", "missing", "stale"}

    backend_source = path_service.PathService.get_path_video.__code__.co_consts
    literals = {item for item in backend_source if isinstance(item, str)}
    for status in statuses:
        assert status in literals, f"后端 get_path_video 不再返回 {status}，前端这条分支该删了"


def test_the_loop_re_sends_the_generation_request(poll_loop):
    """作业没了就重新发起 —— 只 GET 是这次一直转圈的根因。"""
    assert "generatePathVideo(pathId)" in poll_loop


def test_the_loop_has_a_retry_budget(poll_loop):
    """后端每次都立刻失败时，不能打成死循环。"""
    assert "VIDEO_RESTART_LIMIT" in poll_loop
    assert "restarts" in poll_loop


def test_the_loop_still_gives_up_at_the_deadline(poll_loop):
    assert "Date.now() > deadline" in poll_loop


def test_a_dead_job_tells_the_student_to_click_again(poll_loop):
    """重试预算用完时要说清楚怎么办，不能又是一句"耗时过长"。"""
    assert "重新点击视频讲解" in poll_loop


def test_the_loop_keeps_checking_for_a_real_failure(poll_loop):
    """重新发起之后仍然要读 failed + error，否则失败原因又丢了。"""
    assert poll_loop.count("video?.status === 'failed'") >= 2


def test_the_backend_still_keeps_a_failed_job_around_for_a_while(page):
    """前端能读到失败原因的前提：后端不立刻摘除终态作业。"""
    registry = (ROOT / "backend" / "src" / "service" / "path" / "path_video_jobs.py").read_text(encoding="utf-8")
    ttl = re.search(r"_TERMINAL_TTL_SECONDS = (\d+)", registry)
    assert ttl and int(ttl.group(1)) >= 300


# ── 点了没反应：请求压根没发出去 ────────────────────────────────────────
# 症状：盯后端日志半天一行都没有，界面上一直转圈。
# 原因：isVideoLoading 属于"被作废的那一轮轮询"，但作废时没清；而它的复位在
# pollPathVideo 的 finally 里带 token 守卫（token 不等就 return），所以那轮一旦被
# 作废就再也不复位。showVideo() 开头又是 `if (isVideoLoading.value) 只切视图就 return`，
# 于是换过一次路径之后，再点「视频讲解」既不发起请求、也不报错。

def test_invalidating_the_poll_clears_its_loading_flag(page):
    start = page.index("function invalidateVideoPoll()")
    end = page.index("}", page.index("isVideoLoading.value = false", start)) + 1
    body = page[start:end]
    assert "videoPollToken += 1" in body
    assert "isVideoLoading.value = false" in body


def test_the_loading_flag_reset_is_token_guarded(page):
    """复位要认 token，否则先跑完的旧轮询会把新一轮的"加载中"擦掉 —— 正因如此，
    作废路径上必须自己清一次。"""
    assert "if (token === videoPollToken) isVideoLoading.value = false" in page


def test_switching_paths_still_invalidates_the_video_poll(page):
    """换路径是这条链最常见的触发点（视频是路径级产物，换了就不能往新路径上写）。"""
    assert page.count("invalidateVideoPoll()") >= 2


def test_the_video_button_still_posts_when_nothing_is_loading(page):
    """showVideo 的早退分支只在真的有一轮在跑时才该生效。"""
    start = page.index("async function showVideo()")
    body = page[start:page.index("await pollPathVideo()", start)]
    assert "if (isVideoLoading.value)" in body
    assert "await pollPathVideo()" in page[start:start + 900]
