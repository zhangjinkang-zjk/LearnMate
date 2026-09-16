"""`_collect_review_stat` 的聚合语义。

这个函数决定"审核结果"那行日志报什么数字。审核本身发生在 graph 内部，
任务层只看得到流过来的事件 —— 统计错了不会报错，只会静默地把日志写成假的，
所以这里把每条分支都钉住。
"""
from backend.src.service.resource.service import _collect_review_stat


def _stat():
    return {"events": 0, "passed": 0, "needs_fix": 0, "failed": 0, "scores": []}


def _reviewer_event(status, **extra):
    return {"type": "agent_event", "phase": "reviewer", "status": status, **extra}


def test_ignores_non_agent_events():
    stat = _stat()
    _collect_review_stat({"type": "stream_slide_delta", "phase": "reviewer", "status": "done"}, stat)
    _collect_review_stat({"type": "progress", "status": "done"}, stat)
    assert stat == _stat()


def test_ignores_other_phases():
    stat = _stat()
    _collect_review_stat({"type": "agent_event", "phase": "executor", "status": "done"}, stat)
    _collect_review_stat({"type": "agent_event", "phase": "leader", "status": "done"}, stat)
    assert stat == _stat()


def test_counts_each_status():
    stat = _stat()
    _collect_review_stat(_reviewer_event("done", score=90), stat)
    _collect_review_stat(_reviewer_event("retrying"), stat)
    _collect_review_stat(_reviewer_event("failed"), stat)
    assert stat["events"] == 3
    assert stat["passed"] == 1
    assert stat["needs_fix"] == 1
    assert stat["failed"] == 1


def test_phase_and_status_are_case_insensitive():
    stat = _stat()
    _collect_review_stat({"type": "agent_event", "phase": "Reviewer", "status": "DONE", "score": 80}, stat)
    assert stat["passed"] == 1
    assert stat["scores"] == [80]


def test_reviewing_status_only_counts_as_event():
    # "reviewing" 是"正在审核"，既不是通过也不是未通过，只能计入总数。
    stat = _stat()
    _collect_review_stat(_reviewer_event("reviewing"), stat)
    assert stat["events"] == 1
    assert stat["passed"] == 0
    assert stat["needs_fix"] == 0
    assert stat["failed"] == 0


def test_bool_score_is_not_a_score():
    # bool 是 int 的子类，不排掉的话 True 会被当成 1 分混进均分。
    stat = _stat()
    _collect_review_stat(_reviewer_event("done", score=True), stat)
    _collect_review_stat(_reviewer_event("done", score=False), stat)
    assert stat["scores"] == []
    assert stat["passed"] == 2


def test_missing_or_none_score_is_skipped():
    # "使用兜底内容"那条审核事件就没有 score。
    stat = _stat()
    _collect_review_stat(_reviewer_event("done"), stat)
    _collect_review_stat(_reviewer_event("done", score=None), stat)
    assert stat["events"] == 2
    assert stat["scores"] == []


def test_numeric_score_is_truncated_to_int():
    stat = _stat()
    _collect_review_stat(_reviewer_event("done", score=87.6), stat)
    assert stat["scores"] == [87]


def test_non_numeric_score_is_skipped():
    stat = _stat()
    _collect_review_stat(_reviewer_event("done", score="优秀"), stat)
    assert stat["scores"] == []


def test_realistic_ppt_sequence():
    """按 resource_graph 的真实推送顺序走一遍。

    关键点：PPT 逐章节审核**不通过时不发 done**（只有 reviewing，重写由 executor 侧的
    retrying 表达，不属于 reviewer 阶段），所以 done 的条数才是"通过/兜底"的条数。
    """
    stat = _stat()
    events = [
        # 第 1 章：第 1 轮没过 → 第 2 轮通过。两轮都只发 reviewing，没通过不发 done。
        _reviewer_event("reviewing"),
        _reviewer_event("reviewing"),
        _reviewer_event("done", score=88),
        # 第 2 章：一次通过
        _reviewer_event("reviewing"),
        _reviewer_event("done", score=92),
        # reviewer_node 对整份资源的类型级审核：未通过时发 retrying
        _reviewer_event("retrying"),
        # 达最大审核次数、用兜底内容那条 done **没有 score**
        _reviewer_event("done", score=100),
    ]
    for event in events:
        _collect_review_stat(event, stat)

    assert stat["events"] == 7
    assert stat["passed"] == 3          # 88 / 92 / 100 三条 done
    assert stat["needs_fix"] == 1       # 类型级审核未通过
    assert stat["failed"] == 0
    assert stat["scores"] == [88, 92, 100]
    assert round(sum(stat["scores"]) / len(stat["scores"]), 2) == 93.33


def test_fallback_done_without_score_still_counts_as_passed():
    # "使用兜底内容"是 done 但没有 score：它算"这一章结束了"，但不该进均分。
    stat = _stat()
    _collect_review_stat(_reviewer_event("done", score=90), stat)
    _collect_review_stat(_reviewer_event("done"), stat)
    assert stat["passed"] == 2
    assert stat["scores"] == [90]
