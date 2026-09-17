# -*- coding: utf-8 -*-
"""实践会话的阶段进度是服务端的账本。

改之前前端每收到一条回复就无条件 `advancePhase()`，而且 `PATCH /practice/sessions/{id}`
原样采信客户端传来的 `completed_phase_ids` —— 而 `_evaluate` 的 phase_score 就是
`len(completed) / 6 * 40`。也就是说：一次请求把六个阶段全标完成，直接拿满这 40 分。

现在只有一条推进路径：智能体在回复末尾写 `[[PHASE:done]]`，服务端解析它、剥掉它、
写进账本。这里钉住三件事：

1. 标记的剥离（含跨分片、含"不是标记的 `[[`"）
2. 推进规则（只认 `done`、每轮最多一格、按 `PHASES` 顺序）
3. 客户端送来的 `completed_phase_ids` 不再算数
"""

from types import SimpleNamespace

import pytest

from backend.src.service.advanced import practice_service
from backend.src.service.advanced.practice_service import (
    PHASES,
    PHASE_ORDER,
    PhaseStreamStripper,
    advance_phase_state,
    clamp_current_phase,
)

# 这个文件里的阶段断言用的都是 **PHASES（通用词汇）** —— 那是"没有 kind 的会话"
# 那套，也就是本次改动之前建的所有会话。账本函数现在要求显式传词汇：三类新任务各
# 有自己的 4 阶段（见 test_advanced_practice_phase_sets.py），混用等于把进度清零。


# ═══════════════════════════════════════
#  标记剥离
# ═══════════════════════════════════════

def test_a_marker_in_one_chunk_is_removed():
    stripper = PhaseStreamStripper()

    out = stripper.feed("这个阶段的依据够了。\n[[PHASE:done]]")

    assert out == "这个阶段的依据够了。\n"
    assert stripper.markers == ["done"]
    assert stripper.text == "这个阶段的依据够了。\n"


def test_a_marker_split_across_two_chunks_is_removed():
    """逐 chunk 做正则会漏掉这种 —— 而流式分片边界是随机的，必须假定它会跨。"""
    stripper = PhaseStreamStripper()

    first = stripper.feed("这个阶段的依据够了。\n[[PHASE:do")
    second = stripper.feed("ne]]")

    assert first == "这个阶段的依据够了。\n"
    assert second == ""
    assert stripper.markers == ["done"]
    assert stripper.text == "这个阶段的依据够了。\n"


def test_a_marker_split_into_three_chunks_is_removed():
    stripper = PhaseStreamStripper()

    out = "".join(stripper.feed(chunk) for chunk in ("[[PHA", "SE:do", "ne]]"))

    assert out == ""
    assert stripper.markers == ["done"]
    assert "PHASE" not in stripper.text


def test_a_marker_split_between_the_two_brackets_is_removed():
    """最阴的一种分片：`[` 和 `[` 落在相邻两片里。

    如果放走了第一片末尾那个单独的 `[`，`[[` 就横跨在"已下发 / 未下发"之间，
    正则再也匹配不到，标记会被原样漏给学生。靠"末尾的单个 `[` 一律扣住"防住。
    """
    stripper = PhaseStreamStripper()

    first = stripper.feed("这个阶段的依据够了。\n[")
    second = stripper.feed("[PHASE:done]]")

    assert first == "这个阶段的依据够了。\n", "末尾的 `[` 必须扣住，不能先发出去"
    assert second == ""
    assert stripper.markers == ["done"]
    assert "[PHASE" not in stripper.text


def test_any_chunking_of_the_same_reply_gives_the_same_text():
    """分片边界是网络决定的，剥离结果不能依赖它。"""
    import random

    reply = "先看日志。\n依据是超时阈值不一致。\n[[PHASE:done]]"
    expected = "先看日志。\n依据是超时阈值不一致。\n"

    for seed in range(50):
        random.seed(seed)
        chunks, index = [], 0
        while index < len(reply):
            size = random.randint(1, 4)
            chunks.append(reply[index:index + size])
            index += size
        stripper = PhaseStreamStripper()
        emitted = "".join(stripper.feed(chunk) for chunk in chunks) + stripper.flush()
        assert (emitted, stripper.text, stripper.markers) == (expected, expected, ["done"]), seed

    # 逐字符是最极端的分片
    stripper = PhaseStreamStripper()
    emitted = "".join(stripper.feed(char) for char in reply) + stripper.flush()
    assert (emitted, stripper.markers) == (expected, ["done"])


def test_plain_square_brackets_are_left_alone():
    stripper = PhaseStreamStripper()

    out = "".join(stripper.feed(char) for char in "看这个 [链接](x) 和 [[这个]] 都不是标记") + stripper.flush()

    assert out == "看这个 [链接](x) 和 [[这个]] 都不是标记"
    assert stripper.markers == []


def test_the_marker_never_reaches_the_stored_reply():
    """落库要用 stripper.text，不能自己拼原始分片 —— 否则重开会话还能看到残留。"""
    stripper = PhaseStreamStripper()
    raw = ""
    for chunk in ("答案：先看日志。", "\n[[PHASE", ":done]]"):
        raw += chunk
        stripper.feed(chunk)
    stripper.flush()

    assert "PHASE" not in stripper.text
    assert "PHASE" in raw, "前提：原始文本里确实有标记，只是没被采用"
    assert stripper.text == "答案：先看日志。\n"


def test_a_hint_round_does_not_look_like_a_marker():
    stripper = PhaseStreamStripper()

    out = stripper.feed("先看看这条材料。")

    assert out == "先看看这条材料。"
    assert stripper.markers == []


def test_several_markers_are_all_recorded_once():
    stripper = PhaseStreamStripper()

    stripper.feed("[[PHASE:done]]中间[[PHASE:done]]")
    stripper.feed("[[PHASE:DONE]]")

    assert stripper.markers == ["done"]


def test_case_and_spacing_variants_are_accepted():
    stripper = PhaseStreamStripper()

    out = stripper.feed("够了 [[ phase : DONE ]]")

    assert out == "够了 "
    assert stripper.markers == ["done"]


def test_a_non_done_value_is_stripped_but_not_trusted():
    """模型写 `[[PHASE:review]]` 想直接跳到最后 —— 剥掉它，但别当推进信号。"""
    stripper = PhaseStreamStripper()

    out = stripper.feed("[[PHASE:review]]")

    assert out == ""
    assert stripper.markers == ["review"]

    completed, current = advance_phase_state([], "understand", stripper.markers, PHASES)
    assert (completed, current) == ([], "understand")


def test_an_unclosed_bracket_is_held_then_released():
    """模型引用语法时真的会写 `[[`；一直扣住会把正文卡死。"""
    stripper = PhaseStreamStripper()

    held = stripper.feed("引用语法 [[ 这样写")
    assert held == "引用语法 ", "先扣住：还不知道后面是不是标记"

    released = stripper.feed("啊" * 40)
    assert "[[ 这样写" in released, "扣够上限就当普通正文放行"
    assert stripper.markers == []


def test_flush_empties_the_held_tail():
    stripper = PhaseStreamStripper()
    stripper.feed("结尾有个孤立的 [[PHASE:do")

    tail = stripper.flush()

    assert tail == "[[PHASE:do"
    assert stripper.text.endswith("[[PHASE:do")


# ═══════════════════════════════════════
#  推进规则
# ═══════════════════════════════════════

def test_chatting_without_a_marker_does_not_advance():
    assert advance_phase_state([], "understand", [], PHASES) == ([], "understand")
    assert advance_phase_state(["understand"], "evidence", ["hypothesis"], PHASES) == (["understand"], "evidence")


def test_done_advances_exactly_one_phase():
    assert advance_phase_state([], "understand", ["done"], PHASES) == (["understand"], "evidence")


def test_progress_stays_a_contiguous_prefix():
    """标记不带阶段 id，所以一轮最多推一格，不会出现跳级。"""
    completed, current = [], "understand"
    for _ in range(len(PHASE_ORDER)):
        completed, current = advance_phase_state(completed, current, ["done"], PHASES)

    assert completed == list(PHASE_ORDER)
    assert current == PHASE_ORDER[-1], "最后一个阶段完成后再也没有下一格"


def test_completed_is_normalised_to_phase_order():
    """老会话里可能是客户端乱序写进去的，读出来统一按 PHASES 排。"""
    completed, current = advance_phase_state(["review", "understand"], "understand", ["done"], PHASES)

    assert completed == ["understand", "review"]
    assert current == "evidence"


def test_unknown_phase_ids_are_dropped():
    completed, _ = advance_phase_state(["understand", "随便编的"], "understand", [], PHASES)

    assert completed == ["understand"]


# ═══════════════════════════════════════
#  当前阶段的夹紧
# ═══════════════════════════════════════

def test_a_client_cannot_jump_the_current_phase_ahead():
    """一轮对话就把 current_phase 推到 review，进度条显示的就不是真实进度了。"""
    assert clamp_current_phase("review", [], PHASES) == "understand"
    assert clamp_current_phase("review", ["understand"], PHASES) == "evidence"


def test_a_client_can_look_back_at_a_finished_phase():
    assert clamp_current_phase("understand", ["understand", "evidence"], PHASES) == "understand"


def test_every_phase_is_reachable_once_all_are_done():
    assert clamp_current_phase("review", list(PHASE_ORDER), PHASES) == "review"


def test_an_unknown_phase_falls_back_to_the_first():
    assert clamp_current_phase("nonsense", ["understand"], PHASES) == "understand"


# ═══════════════════════════════════════
#  账本：客户端送来的进度不算数
# ═══════════════════════════════════════

class _FakeSession:
    def __init__(self, **kwargs):
        self.session_key = "s" * 32
        self.task_key = "path-68-node-10"
        self.user_id = 1
        self.path_id = 68
        self.node_id = 10
        self.task_snapshot = kwargs.get("task_snapshot") or {}
        self.status = kwargs.get("status", "active")
        self.current_phase = kwargs.get("current_phase", "understand")
        self.completed_phases = list(kwargs.get("completed_phases") or [])
        self.messages = list(kwargs.get("messages") or [])
        self.confirmed_facts = []
        self.assumptions = []
        self.final_submission = None
        self.evaluation = kwargs.get("evaluation")
        self.updated_at = None
        self.saved: list[tuple | None] = []

    async def save(self, update_fields=None):
        self.saved.append(tuple(update_fields) if update_fields else None)


class _Query:
    def __init__(self, session):
        self._session = session

    def filter(self, **kwargs):
        return self

    async def first(self):
        return self._session


def _install(monkeypatch, session):
    monkeypatch.setattr(
        practice_service,
        "AdvancedPracticeSession",
        SimpleNamespace(filter=lambda **kwargs: _Query(session)),
    )
    # 提交会起一个后台评分作业。单元测试里既没有 DB 也没有 LLM，别让它真的跑起来；
    # 这里只记录"该起作业"这件事，作业本身在 test_advanced_practice_grading 里测。
    scheduled: list[tuple[int, str]] = []

    async def _stub_job(user_id, session_key, producer):
        scheduled.append((user_id, session_key))
        return SimpleNamespace(state="generating"), True

    monkeypatch.setattr(practice_service, "ensure_grading_job", _stub_job)
    session.scheduled_gradings = scheduled
    return session


# 不含 依据/验证/方案 类关键词，所以这几项得分都为 0，分数差异只可能来自阶段分。
_NEUTRAL_MESSAGE = {"role": "user", "text": "我按计划完成了这个任务"}


@pytest.mark.asyncio
async def test_save_state_ignores_the_clients_phase_list(monkeypatch):
    session = _install(monkeypatch, _FakeSession(completed_phases=["understand"]))

    result = await practice_service.AdvancedPracticeService.save_state(
        1,
        session.session_key,
        current_phase="understand",
        completed_phase_ids=list(PHASE_ORDER),  # 客户端谎报全部完成
        messages=[_NEUTRAL_MESSAGE],
    )

    assert result["completed_phase_ids"] == ["understand"], "账本只认服务端自己记的"
    assert session.completed_phases == ["understand"]


@pytest.mark.asyncio
async def test_save_state_clamps_the_requested_phase(monkeypatch):
    session = _install(monkeypatch, _FakeSession())

    result = await practice_service.AdvancedPracticeService.save_state(
        1,
        session.session_key,
        current_phase="review",
        completed_phase_ids=[],
        messages=[_NEUTRAL_MESSAGE],
    )

    assert result["current_phase"] == "understand"


@pytest.mark.asyncio
async def test_submitting_a_forged_phase_list_does_not_pay_phase_points(monkeypatch):
    """改动前：这条请求能拿到满分 40 的阶段分。"""
    session = _install(monkeypatch, _FakeSession(completed_phases=["understand"]))

    result = await practice_service.AdvancedPracticeService.submit(
        1,
        session.session_key,
        final_submission=_NEUTRAL_MESSAGE["text"],
        current_phase="review",
        completed_phase_ids=list(PHASE_ORDER),  # 谎报六个阶段全完成
        messages=[_NEUTRAL_MESSAGE],
    )

    evaluation = result["evaluation"]
    # 服务端账本只有 understand → round(1/6*40) = 7；用户只有一轮 → activity 2。
    assert evaluation["score"] == 9, "40 分的阶段分只该按服务端账本里的 1 个阶段算"
    assert evaluation["criteria"][0] == {"label": "问题理解", "passed": True}
    assert result["completed_phase_ids"] == ["understand"]


@pytest.mark.asyncio
async def test_submitting_schedules_a_server_side_grading_job(monkeypatch):
    """提交先给确定性基线（用户不用等），复核交给后台作业覆盖它。"""
    session = _install(monkeypatch, _FakeSession(completed_phases=["understand"]))

    result = await practice_service.AdvancedPracticeService.submit(
        1,
        session.session_key,
        final_submission=_NEUTRAL_MESSAGE["text"],
        current_phase="understand",
        completed_phase_ids=[],
        messages=[_NEUTRAL_MESSAGE],
    )

    assert session.scheduled_gradings == [(1, session.session_key)]
    assert result["evaluation"]["source"] == "deterministic"


def test_evaluation_status_tells_apart_scored_and_final(monkeypatch):
    scored = _FakeSession(status="completed", evaluation={"score": 70})

    monkeypatch.setattr(practice_service, "is_grading", lambda user_id, key: True)
    assert practice_service.practice_evaluation_status(scored) == "reviewing"

    monkeypatch.setattr(practice_service, "is_grading", lambda user_id, key: False)
    assert practice_service.practice_evaluation_status(scored) == "ready"

    assert practice_service.practice_evaluation_status(_FakeSession(status="active")) == "none"


@pytest.mark.asyncio
async def test_record_phase_markers_writes_the_ledger(monkeypatch):
    session = _install(monkeypatch, _FakeSession(current_phase="understand"))

    state = await practice_service.AdvancedPracticeService.record_phase_markers(session, ["done"])

    assert state == {
        "current_phase": "evidence",
        "current_phase_label": "寻找证据",
        "completed_phase_ids": ["understand"],
    }
    assert session.saved == [("completed_phases", "current_phase", "updated_at")]


@pytest.mark.asyncio
async def test_record_phase_markers_without_a_marker_writes_nothing(monkeypatch):
    session = _install(monkeypatch, _FakeSession())

    assert await practice_service.AdvancedPracticeService.record_phase_markers(session, []) == {}
    assert session.saved == []


@pytest.mark.asyncio
async def test_record_phase_markers_leaves_a_finished_session_alone(monkeypatch):
    session = _install(
        monkeypatch, _FakeSession(status="completed", completed_phases=list(PHASE_ORDER))
    )

    assert await practice_service.AdvancedPracticeService.record_phase_markers(session, ["done"]) == {}
    assert session.saved == []


@pytest.mark.asyncio
async def test_record_phase_markers_survives_a_missing_session():
    """practice 场景但没带 practice_session_id 时调用方会传 None。"""
    assert await practice_service.AdvancedPracticeService.record_phase_markers(None, ["done"]) == {}
