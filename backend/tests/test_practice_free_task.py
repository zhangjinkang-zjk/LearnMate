# -*- coding: utf-8 -*-
"""「无任务」：学生不挑任务，带着自己的项目来，聊什么由他说了算。

后端有两处按任务办事：**任务块**（`classroom_chat._render_task_block`）和**开场与每轮的
框定语**（`_opening_fallback` / `_compose_user_prompt`）。它们原来的前提是"实践会话一定
有个任务"，于是"没有任务"只能表达成"任务字段为空" —— 而那是**一个能读成两种意思的信号**
（前端没传？还是确实没有？）。教练读到它多半照旧按任务问："要交付什么""验收标准是什么"。

所以这里落的是一条**显式的**模式：`task_snapshot["mode"] == "free"`。

这个文件专门钉住"生产者 → 消费者"这一整条，因为这类错最典型的形态不是某一段文案写歪，
而是**写进账本的那个键，读的那边根本不认**（或反过来）。两边各自的单测都会过，链子断在
中间。下面第 3 条就是这条链。
"""

from types import SimpleNamespace

import pytest

from backend.src.service.advanced import practice_service
from backend.src.service.advanced.practice_service import (
    FREE_TASK_MODE,
    _opening_pending,
    _task_snapshot,
    _welcome_message,
)
from backend.src.service.path import classroom_chat as cg_chat


def _free_task():
    """前端为「无任务」造的那份伪任务（见 AdvancedLearningPage.FREE_TASK_ID）。"""
    return {
        "id": "__free__",
        "mode": "free",
        "kind_label": "无任务",
        "title": "拿你自己的项目来聊",
        "brief": "",
        "problem": "",
        "focus": "",
        "criteria": [],
        "deliverables": [],
        "constraints": [],
        "workspace": {"path_id": 3, "node_id": 9},
    }


# ═══════════════════════════════════════
#  账本：模式标记必须真的存下来
# ═══════════════════════════════════════

def test_the_free_marker_survives_the_snapshot_filter():
    """`_task_snapshot` 是个白名单，新字段不加进去就静默丢掉 —— 而这里丢掉的是
    **整条链的起点**：账本里没有 mode，往下三处全都认不出来。"""
    assert _task_snapshot(_free_task())["mode"] == FREE_TASK_MODE


def test_a_regular_snapshot_has_no_mode_key_at_all():
    """常规任务里**没有这个键**，而不是有个空串。

    读到缺失的含义是"这是常规任务"。塞个 `""` 进去就多出第三种要分辨的状态
    （有值 / 空串 / 缺失），而它们里有两个意思一样。
    """
    for task in ({"id": "path_1_node_2_project", "title": "做一个能跑的东西"}, {}, None, "不是 dict"):
        assert "mode" not in _task_snapshot(task)


# ═══════════════════════════════════════
#  链子：写进账本的，读的那边认不认
# ═══════════════════════════════════════

def test_free_mode_survives_the_whole_ledger_to_prompt_chain():
    """**这条是这个文件存在的理由。**

    前端 → `_task_snapshot`（写账本）→ `_is_free_task`（读账本）→ 任务块/提示词。
    中间任何一环改名或漏字段，两边各自的测试都还是绿的，只有这条会红。
    """
    snapshot = _task_snapshot(_free_task())

    assert cg_chat._is_free_task(snapshot), "账本里的 mode 读不出来，后面三处就全按任务处理了"
    block = cg_chat._render_task_block(snapshot)
    assert "没有选任务" in block, "任务块必须明说这次没有任务，不能整块消失"


def test_a_real_task_is_never_read_as_free():
    """反向也要钉：常规任务不能被误判成自由模式，否则教练会拒绝一切任务相关的追问。"""
    snapshot = _task_snapshot({"id": "path_1_node_2_project", "title": "做一个能跑的东西"})
    assert not cg_chat._is_free_task(snapshot)
    assert "任务：做一个能跑的东西" in cg_chat._render_task_block(snapshot)


# ═══════════════════════════════════════
#  任务块：说"没有任务"，而不是让块消失
# ═══════════════════════════════════════

def test_the_free_task_block_says_there_is_no_task():
    block = cg_chat._render_task_block({"mode": "free", "title": "拿你自己的项目来聊"})

    assert block.startswith("【本次实践任务】")
    assert block.endswith("【任务说明结束】")
    assert "没有选任务" in block
    # 三件事都要说：别替他挑任务、别问验收、他问什么就聊什么
    assert "不要替他挑一个任务" in block
    assert "验收标准" in block and "根本没有" in block


def test_the_free_block_does_not_render_the_option_label_as_a_task():
    """「拿你自己的项目来聊」是**界面上的选项标签**，不是任务名。

    直接套模板会拼出「任务：拿你自己的项目来聊」，教练于是真的以为有这么个任务，
    并且会照着它问"你打算怎么产出它"。
    """
    block = cg_chat._render_task_block({"mode": "free", "title": "拿你自己的项目来聊"})

    assert "任务：拿你自己的项目来聊" not in block
    assert not block.count("拿你自己的项目来聊")


def test_a_regular_block_is_byte_for_byte_the_old_one():
    """自由模式的早退**不许**顺手动到常规任务那一支。"""
    block = cg_chat._render_task_block({
        "title": "做一个能跑的东西",
        "problem": "把调度用起来",
        "focus": "任务拆解",
        "criteria": ["能运行"],
        "deliverables": [{"id": "d1", "label": "能跑的代码"}],
    })

    assert "任务：做一个能跑的东西" in block
    assert "要解决的问题：把调度用起来" in block
    assert "能力重点：任务拆解" in block
    assert "验收标准：能运行" in block
    assert "需要交付：能跑的代码" in block


def test_is_free_task_rejects_junk():
    """客户端来的东西什么都可能是。判等之前先过 `_clip`，所以多余空白不算不同，
    而数字/布尔/裸字符串一律不算 free。"""
    assert cg_chat._is_free_task({"mode": "  free  "})
    for junk in (None, {}, [], "free", {"mode": 123}, {"mode": True}, {"mode": ""}, {"mode": "FREE "}):
        assert not cg_chat._is_free_task(junk)


# ═══════════════════════════════════════
#  开场：服务端种的那句 + 模型没出话时的兜底
# ═══════════════════════════════════════

def test_the_free_seed_does_not_pretend_there_is_a_task():
    """首屏那句不能讲"这个任务" —— 自由模式根本没有任务，第一眼就是一句凭空指代。"""
    text = _welcome_message(_task_snapshot(_free_task()))["text"]

    assert text.strip()
    assert "这个任务" not in text
    assert "「」" not in text
    # 还是要他开口，不能只把"没有任务"说明一遍就算完
    assert "先说" in text


def test_the_free_seed_differs_from_the_free_fallback():
    """两句**必须字面不同**：`_opening_pending` 靠"助手说过的话 != 种下的那句"判断
    开场已经生成过，字面相同就会每轮都重新请教练开场一次。"""
    seed = _welcome_message(_task_snapshot(_free_task()))["text"]
    fallback = cg_chat._opening_fallback({"title": "拿你自己的项目来聊"}, is_free_task=True)

    assert seed != fallback


def test_a_fresh_free_session_is_waiting_for_the_coach():
    """种下开场之后仍然要请教练开口 —— 那句通用文案不是终点，教练要给的是读过工作区的话。"""
    session = SimpleNamespace(
        messages=[_welcome_message(_task_snapshot(_free_task()))],
        task_snapshot=_task_snapshot(_free_task()),
    )
    assert _opening_pending(session)


def test_a_coach_reply_ends_the_free_waiting():
    """教练真开了口就不该再请他开一次场 —— 自由模式这条判据和常规任务共用，别被绕开。"""
    snapshot = _task_snapshot(_free_task())
    session = SimpleNamespace(
        messages=[
            _welcome_message(snapshot),
            {"role": "assistant", "text": "你想先看哪一块？"},
        ],
        task_snapshot=snapshot,
    )
    assert not _opening_pending(session)


def test_the_free_opening_fallback_does_not_use_the_option_label_as_a_task():
    text = cg_chat._opening_fallback({"title": "拿你自己的项目来聊"}, is_free_task=True)

    assert "这个任务是" not in text
    assert "拿你自己的项目来聊" not in text
    assert "「」" not in text
    assert text.strip()


# ═══════════════════════════════════════
#  每轮的提示词：框定语不能自相矛盾
# ═══════════════════════════════════════

def test_the_free_opening_prompt_does_not_ask_for_deliverables():
    """开场那一轮原来要模型"点明这个任务要他产出什么"。

    自由模式下上面那块写的是"这次没有任务"，同一份提示词里两句话打架 —— 模型会挑
    对它省事的那个信，也就是照旧按任务开局。
    """
    prompt = cg_chat._compose_user_prompt("practice_opening", "", {}, is_free_task=True)

    assert "点明这个任务要他产出什么" not in prompt
    # 开场这件事本身照旧：还是要问他从哪儿开始
    assert "他想从哪儿开始" in prompt


def test_the_free_practice_prompt_does_not_claim_he_is_doing_a_task():
    prompt = cg_chat._compose_user_prompt("practice", "帮我看看这段代码", {}, is_free_task=True)

    assert "正在做上面【本次实践任务】里的那个任务" not in prompt
    assert "没有任务" in prompt
    # 他的原话一个字都不能少
    assert "帮我看看这段代码" in prompt


@pytest.mark.parametrize("scenario", ["practice", "practice_opening"])
def test_regular_prompts_are_unchanged(scenario):
    """自由模式开关默认关闭，常规会话的提示词必须**逐字**保持原样。

    这两句是模型行为的实际约束，改了就是行为变更 —— 不能从自由模式这边顺带漂过去。
    """
    prompt = cg_chat._compose_user_prompt(scenario, "学生的原话", {})
    assert "没有任务" not in prompt
    if scenario == "practice":
        assert "学生正在做上面【本次实践任务】里的那个任务" in prompt
    else:
        assert "点明这个任务要他产出什么" in prompt


def test_opening_fallback_defaults_to_the_old_behaviour():
    """不传 `is_free_task` 时和后端改动之前一字不差。"""
    assert (
        cg_chat._opening_fallback({"title": "写一份检索方案"})
        == "这个任务是「写一份检索方案」。先说说它要解决的核心问题，以及你准备依据哪些信息判断。"
    )


def test_the_free_marker_is_the_documented_literal():
    """这个字面量是**前后端之间的约定**（前端造伪任务时写 `mode: 'free'`）。

    它没有 schema 兜着（`PracticeSessionRequest.task` 是自由 dict），所以改这里等于
    改协议 —— 钉一下，免得有人顺手改成枚举或缩写。
    """
    assert FREE_TASK_MODE == "free"
    assert practice_service.FREE_TASK_MODE == "free"
