# -*- coding: utf-8 -*-
"""进阶学习的第一问不该是写死的。

改动之前：会话建好时 `_welcome_message()` 种下一句跟任务无关的通用话术，学生进页面
看到的第一句永远是

    我们从"理解问题"开始。先说说这个任务要解决的核心问题，以及你准备依据哪些信息判断。

换个任务也还是这句 —— 它不提任务名、不读任务内容，学生看完只能回一句"你在说啥"，
要等第二轮模型才把任务讲清楚。而教练（`classroom_chat` 的 `practice` 分支）必须等
学生先说话才会被调用，所以"会读任务的那一轮"永远排在第二。

现在分两层：
- 服务端种一句**带任务名**的开场（`_welcome_message`），首屏立刻能看到，也是模型挂掉
  时的兜底；
- 前端据 `opening_pending` 让教练真的读一遍任务、把那句换掉（流式，见
  `PracticeDialogue.requestOpening`）。

这里钉住第一层，以及"什么时候还需要教练开口"的判据。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.src.service.advanced import practice_service
from backend.src.service.advanced.practice_service import (
    PHASE_LABELS,
    _opening_pending,
    _serialize,
    _welcome_message,
)


def _session(messages=None, snapshot=None, **overrides):
    """够 _welcome_message / _opening_pending / _serialize 用的会话替身。"""
    base = {
        "session_key": "s1",
        "task_key": "t1",
        "path_id": 1,
        "node_id": 2,
        "status": "active",
        "current_phase": "understand",
        "completed_phases": [],
        "messages": messages if messages is not None else [],
        "task_snapshot": snapshot if snapshot is not None else {"title": "构建一个身份-权限模型"},
        "confirmed_facts": [],
        "assumptions": [],
        "final_submission": "",
        "evaluation": None,
        "updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ═══════════════════════════════════════
#  种下的那句开场
# ═══════════════════════════════════════

def test_the_seeded_opening_names_the_task():
    """学生看到的第一句必须点出任务是什么，否则他不知道要回答什么。"""
    text = _welcome_message({"title": "构建一个身份-权限模型"})["text"]
    assert "构建一个身份-权限模型" in text
    assert PHASE_LABELS["understand"] in text


def test_the_seeded_opening_is_something_the_student_can_actually_answer():
    text = _welcome_message({"title": "写一份检索方案"})["text"]
    assert "先说说" in text
    assert "「」" not in text, "拼出空引用等于没提任务名"


def test_the_seeded_opening_survives_a_missing_snapshot():
    """快照缺 title 时退回不带任务名的整句 —— 不能崩，也不能拼出「」。"""
    for snapshot in (None, {}, {"title": ""}, {"title": "   "}):
        text = _welcome_message(snapshot)["text"]
        assert text.strip()
        assert "「」" not in text


def test_the_seeded_opening_is_shaped_like_a_message():
    message = _welcome_message({"title": "写一份检索方案"})
    assert message["role"] == "assistant"
    assert message["text"].strip()


# ═══════════════════════════════════════
#  什么时候还需要教练开口
# ═══════════════════════════════════════

def test_a_fresh_session_is_waiting_for_the_coach():
    """刚建好的会话只有种下那句，教练还没开过口。"""
    snapshot = {"title": "构建一个身份-权限模型"}
    assert _opening_pending(_session(messages=[_welcome_message(snapshot)], snapshot=snapshot)) is True


def test_a_session_without_any_message_is_still_waiting():
    assert _opening_pending(_session(messages=[])) is True


def test_junk_rows_do_not_count_as_an_opening():
    """空消息、非 dict 的行都不算"教练说过了"。"""
    snapshot = {"title": "构建一个身份-权限模型"}
    messages = [None, {}, {"role": "assistant", "text": "   "}, _welcome_message(snapshot)]
    assert _opening_pending(_session(messages=messages, snapshot=snapshot)) is True


def test_the_student_speaking_ends_the_waiting():
    """学生先开口了，就不该再有教练开场插进来 —— 那会变成两个开场问题。"""
    session = _session(messages=[
        _welcome_message({"title": "构建一个身份-权限模型"}),
        {"role": "user", "text": "你在说啥"},
    ])
    assert _opening_pending(session) is False


def test_a_coach_written_opening_ends_the_waiting():
    """教练写过开场之后，刷新页面不该再生成一次（每次都不一样会很困惑）。"""
    session = _session(messages=[
        _welcome_message({"title": "构建一个身份-权限模型"}),
        {"role": "assistant", "text": "这个任务要你产出的是一个权限模型。先说说它要解决什么问题？"},
    ])
    assert _opening_pending(session) is False


def test_only_the_opening_turn_is_kept_open():
    """学生答过一轮之后，后面的助手回复都不该让它重新变成"等开场"。"""
    session = _session(messages=[
        {"role": "assistant", "text": "这个任务要你产出的是一个权限模型。先说说它要解决什么问题？"},
        {"role": "user", "text": "要区分角色和权限"},
        {"role": "assistant", "text": "这一步的依据是什么？"},
    ])
    assert _opening_pending(session) is False


# ═══════════════════════════════════════
#  下发
# ═══════════════════════════════════════

def test_the_api_exposes_whether_the_opening_is_still_pending():
    """前端拿不到这个信号就只能靠猜（比如比对文案），两处字面量迟早对不上。"""
    assert _serialize(_session(messages=[]))["opening_pending"] is True

    spoke = _session(messages=[
        _welcome_message({"title": "构建一个身份-权限模型"}),
        {"role": "user", "text": "要区分角色和权限"},
    ])
    assert _serialize(spoke)["opening_pending"] is False


def test_a_legacy_session_without_the_student_speaking_gets_a_real_opening():
    """库里老会话存的是改动前那句通用开场：它不带任务名，所以等于还没开过头。

    这正是要修的毛病 —— 学生打开这样一个会话，看到的还是那句"我们从理解问题开始"，
    所以它得算"还等着教练开口"。学生已经说过话的老会话不受影响
    （见 test_the_student_speaking_ends_the_waiting）。
    """
    legacy = "我们从“理解问题”开始。先说说这个任务要解决的核心问题，以及你准备依据哪些信息判断。"
    assert practice_service._LEGACY_OPENINGS == {legacy}, "认老会话全靠这个字面量，别让它漂了"

    session = _session(messages=[{"role": "assistant", "text": legacy}])
    assert _opening_pending(session) is True


def test_a_legacy_session_where_the_student_already_spoke_is_left_alone():
    legacy = "我们从“理解问题”开始。先说说这个任务要解决的核心问题，以及你准备依据哪些信息判断。"
    session = _session(messages=[{"role": "assistant", "text": legacy}, {"role": "user", "text": "我想先确认输入格式"}])
    assert _opening_pending(session) is False


def test_the_serialized_session_still_carries_its_messages():
    """加了新字段不等于可以少给别的字段 —— 前端整个对话面板都读这个响应。"""
    snapshot = {"title": "构建一个身份-权限模型"}
    payload = _serialize(_session(messages=[_welcome_message(snapshot)], snapshot=snapshot))
    assert payload["messages"] == [_welcome_message(snapshot)]
    assert payload["session_id"] == "s1"
    assert payload["current_phase"] == "understand"
    assert payload["current_phase_label"] == PHASE_LABELS["understand"]


# ═══════════════════════════════════════
#  前端不再抄一份
# ═══════════════════════════════════════

FRONTEND_DIALOGUE = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "features" / "advanced" / "PracticeDialogue.vue"
)


def test_the_frontend_does_not_keep_a_second_copy_of_the_opening():
    """前端以前抄了一份和服务端一模一样的话，两处各自漂移。

    现在只有服务端种开场（`_welcome_message`），前端负责让教练把它换掉。跨语言没法
    import，只能靠读文件钉住"别再抄一份回来"。
    """
    if not FRONTEND_DIALOGUE.exists():
        pytest.skip("前端不在这个工作区里，跨语言对齐检查无从谈起")
    source = FRONTEND_DIALOGUE.read_text(encoding="utf-8")

    assert 'scenario: \'practice_opening\'' in source, "前端得真的去请教练开口"
    assert "我们从" not in source, "开头那句写死的话不该再出现在前端"
    assert "先说说这个任务要解决" not in source


def test_the_frontend_only_asks_for_the_opening_when_the_server_says_so():
    """前端不自己判断"该不该开口"：那是服务端的账（`opening_pending`）。"""
    if not FRONTEND_DIALOGUE.exists():
        pytest.skip("前端不在这个工作区里，跨语言对齐检查无从谈起")
    source = FRONTEND_DIALOGUE.read_text(encoding="utf-8")

    assert "opening_pending" in source
    # 判据写在 requestOpening 的守卫里，前端不该另起一套（比如比对文案）
    assert "openingPending.value" in source
