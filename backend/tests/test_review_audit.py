# -*- coding: utf-8 -*-
"""`eval/review_audit.py` 的判据：**日志里的审核事实数得对，数不出来时要承认数不出来。**

这条测试守的是"评估自己撒谎"这一类 bug，具体两处：

1. **"没执行" 与 "数不出来" 必须分开。** 日志级别没放开时，`路径审核结果` 一行都不会有；
   那时把执行率算成 `0%` 就是在**指控生产代码审核没跑**，而实际上只是证据没留下。
   所以 `审核实际执行率` 在零条记录时是 `None`，不是 `0.0`。
2. **同一科目被重复生成要看得见。** 分母是生成记录数，不是科目数 —— 一轮里某个科目换大纲
   重跑会出现多行，"5 条路径"很容易被读成"5 个科目各审了一遍"。

下面的日志行**抄自真实运行**（`eval/_journey2.log`），不是编的：正则是对着生产里
`logger.*(...)` 的格式串写的，改了那边的格式串，这里会匹配不到而变成 0 —— 不会匹配错。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from eval.review_audit import parse_log, render, summarize  # noqa: E402

# ── 真实日志样本 ──

PATH_LLM = ("INFO backend.src.service.path.service: 路径审核结果 "
            "subject=Python程序设计 passed=True source=llm nodes=12 retry=0")
PATH_ERROR = ("WARNING backend.src.service.path.service: 路径审核结果 "
              "subject=机器学习与深度学习 passed=True source=error nodes=15 retry=0")
PATH_SKIPPED = ("INFO backend.src.service.path.service: 路径审核结果 "
                "subject=空路径 passed=True source=skipped nodes=0 retry=0")
PPT_SUMMARY = ("INFO backend.src.ai_core.resource_ppt: [PPT-Review] 审核汇总 "
               "章节=14 送审=13次 未通过=1次 达标=13章 兜底=0章")
PPT_REJECT = ("WARNING backend.src.ai_core.resource_ppt: [PPT-Review] idx=3 "
              "section=Python内置数据类型总览 round=1 审核未通过: 系统格式快检未通过")
PPT_ERROR = ("ERROR backend.src.ai_core.resource_ppt: [PPT-Review] "
             "section=整数与浮点数运算 审核异常")
DOC_SUMMARY = ("INFO backend.src.ai_core.resource_document: [Doc-Review] 质检汇总 "
               "小节=6 首轮达标=6 质量重写=0次 异常重写=1次 兜底=0节 整章重修=0轮")

# `logger.exception` 抛出后紧跟的 traceback —— 不该被当成另一起事件
TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "backend/src/ai_core/resource_ppt.py", line 706, in _review_ppt_section\n'
    "ValueError: 审核异常: 模型返回了非法 JSON"
)


def test_a_path_review_line_is_parsed_into_its_five_fields():
    parsed = parse_log(PATH_LLM)
    assert parsed["path_reviews"] == [
        {"subject": "Python程序设计", "passed": True, "source": "llm", "nodes": 12, "retry": "0"}
    ]


def test_the_three_review_sources_are_kept_apart():
    """`llm` / `skipped` / `error` 是三件事：真的审了 / 没东西可审 / 审的时候炸了。

    把它们并成"通过 / 不通过"就等于把故障放行藏进"通过"里 —— 这正是这条测试的靶心。
    """
    summary = summarize(parse_log("\n".join([PATH_LLM, PATH_ERROR, PATH_SKIPPED])))

    assert summary["路径审核来源分布"] == {"llm": 1, "error": 1, "skipped": 1}
    assert summary["审核实际执行率"] == pytest.approx(1 / 3)
    assert [item["subject"] for item in summary["故障放行清单"]] == ["机器学习与深度学习"]
    assert [item["subject"] for item in summary["未执行审核清单"]] == ["空路径"]


def test_a_log_without_the_lines_reports_none_not_zero():
    """**没证据 ≠ 没执行。** 日志级别没放开时算出来 0%，读的人会去查生产代码 ——
    而真正该查的是那次运行忘了把 INFO 放出来。"""
    summary = summarize(parse_log("INFO 什么都没有的一行日志"))

    assert summary["路径数"] == 0
    assert summary["审核实际执行率"] is None
    assert "算不出" in render(summary, "空.log")


def test_the_same_subject_generated_twice_is_visible():
    """分母是生成记录数，不是科目数。"""
    summary = summarize(parse_log("\n".join([
        PATH_ERROR,
        PATH_ERROR.replace("nodes=15", "nodes=21"),  # 同一次运行里换了大纲重跑
    ])))

    assert summary["路径数"] == 2
    assert summary["重复生成的科目"] == {"机器学习与深度学习": 2}
    assert "×2" in render(summary, "空.log")


def test_ppt_section_failures_and_fallbacks_are_read():
    parsed = parse_log("\n".join([PPT_SUMMARY, PPT_REJECT, PPT_ERROR]))

    assert parsed["ppt"]["summary"] == {"sections": 14, "sent": 13, "failed": 1, "ok": 13, "fallback": 0}
    assert [item["section"] for item in parsed["ppt"]["errors"]] == ["整数与浮点数运算"]
    assert parsed["ppt"]["rejected"][0]["section"] == "Python内置数据类型总览"


def test_a_traceback_is_not_counted_as_a_second_event():
    """`logger.exception` 会把 traceback 接着打在后面几行。那几行里带着
    `审核异常` 字样，但它们不是新的一次异常 —— 数重了就会把"2 章异常"报成"4 章"。"""
    parsed = parse_log(PPT_ERROR + "\n" + TRACEBACK)

    assert len(parsed["ppt"]["errors"]) == 1


def test_document_quality_summary_is_read():
    parsed = parse_log(DOC_SUMMARY)

    assert parsed["doc"]["summary"]["sections"] == 6
    assert parsed["doc"]["summary"]["error_rewrite"] == 1


def test_the_audit_says_what_it_cannot_see():
    """覆盖缺口要写在报告里。资源链全局 reviewer 的异常不落库、不打日志 ——
    报告必须点明这是"看不见"，否则会被读成"这里零故障"。"""
    text = render(summarize(parse_log(PATH_LLM)), "x.log")

    assert "看不见" in text
    assert "零痕迹" in text
