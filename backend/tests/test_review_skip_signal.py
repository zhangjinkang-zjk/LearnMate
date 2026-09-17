# -*- coding: utf-8 -*-
"""整轮跳过审核时，后端要告诉前端一声。

起因是一个很具体的现象：基础学习的自动生成用的是 `skip_review=True`
（`path/service.py`），于是生成器里那两处审核全部不跑 —— PPT 的逐节审核被
`skip_review_sections` 挡掉，文档的跨章节交叉验证被 `if not skip_review` 挡掉。

结果是**一条审核事件都不会上报**，而前端章节看板只能靠事件来推进审核状态，于是文档
和 PPT 的每一节都永远停在"待审核"。用户看到的是：资源已经生成并抛出来了，抽屉里却
一直写着"未审核"，像是审核环节卡住了 —— 其实是这一轮压根不审。

约定：后端在流程一开始就推一条 `phase=reviewer, status=skipped` 的 agent_event，
前端据它把所有章节（包括之后才冒出来的）落成"未审核"。

两边靠字面量对齐（跨语言没法 import），所以这里钉住这个配对。
"""

from pathlib import Path

import pytest

from backend.src.ai_core.agent_names import REVIEWER_AGENT
from backend.src.service.resource.service import _review_skip_payload

FRONTEND_STATE = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "entities" / "agent" / "agentWorkflowState.js"
)


# ── 后端发的是什么 ────────────────────────────────────

def test_nothing_is_sent_when_review_actually_runs():
    """正常审核时不能多发这条 —— 前端会据此把所有章节盖成"未审核"。"""
    assert _review_skip_payload(False) is None


def test_the_skip_signal_says_which_phase_and_that_it_was_skipped():
    payload = _review_skip_payload(True)
    assert payload is not None
    assert payload["type"] == "agent_event"
    # 前端按 agent_id / phase / status 三个字段认这条信号（见下面那条对齐检查）
    assert payload["agent_id"] == "reviewer"
    assert payload["phase"] == "reviewer"
    assert payload["status"] == "skipped"
    assert payload["agent_name"] == REVIEWER_AGENT


def test_the_message_says_skipped_rather_than_still_waiting():
    """文案必须让人看出"这次不做"，而不是"还没轮到" —— 后者会让学生一直等。"""
    message = _review_skip_payload(True)["message"]
    assert message.strip()
    assert "跳过" in message
    assert "等待" not in message and "稍后" not in message


@pytest.mark.parametrize("value", [True, 1, "yes"])
def test_any_truthy_skip_flag_produces_the_signal(value):
    """调用方传进来的是 state 里的值，不保证是严格的 bool。"""
    assert _review_skip_payload(value) is not None


# ── 两边对得上吗 ──────────────────────────────────────

def _frontend_source() -> str:
    if not FRONTEND_STATE.exists():
        pytest.skip("前端不在这个工作区里，跨语言对齐检查无从谈起")
    return FRONTEND_STATE.read_text(encoding="utf-8")


def test_the_frontend_recognises_this_exact_signal():
    """前端的判定条件是 `phase === 'reviewer' && status === 'skipped'`。

    两边任一改字面量，这条信号就会被悄悄丢掉 —— 章节又回到永远"待审核"，而且没有
    任何报错。跨语言没法 import，只能读文件钉。
    """
    source = _frontend_source()
    assert "'reviewer'" in source
    assert "'skipped'" in source
    assert "isReviewSkipEvent" in source, "识别这条信号的函数不见了"


def test_the_frontend_carries_the_skip_state_onto_sections():
    """收到信号之后要落到章节上：已经出现的、以及之后才冒出来的都算。

    只处理"当时已存在"的章节是不够的 —— 这条信号在流程一开始就到达，那时章节还
    一个都没有（这正是第一次修的时候漏掉的：信号记下了，新章节却又落回"等待审核"）。
    """
    source = _frontend_source()
    assert "reviewSkipped" in source
    assert "reviewSkipMessage" in source, "后端那句说明会被丢成兜底文案"
    # 新章节的初始审核状态要跟着这个会话语义走
    assert "workflowState.reviewSkipped ? 'skipped' : 'pending'" in source
