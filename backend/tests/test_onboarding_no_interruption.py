# -*- coding: utf-8 -*-
"""首次使用流程（画像访谈 / 基础检测）不该"异常中断"。

对应三条真实故障路径：
  1. 诊断提交答案先落库、后出下一题；中间被打断（客户端断连触发取消、模型超时、
     进程重启）会留下"已作答但没有下一题"，重试只会得到"该题已经提交过"，
     用户被永久钉在那一题上，只能整轮重开。
  2. 诊断流的断连处理顺手取消了业务任务，一次切页/刷新就把正在生成的题一起带走。
  3. 画像分析是全代码库唯一"模型失败即 500"的地方（其他调用都有兜底），
     而前端 PortraitSummaryPage 本来就有"画像分析没有完成，用访谈原始回答兜底"的分支。
"""

import asyncio
from types import SimpleNamespace

import pytest

from backend.src.ai_core import llm_config
from backend.src.router import diagnosis_router
from backend.src.service.diagnosis import service as diagnosis_service
from backend.src.service.portrait import service as portrait_service


# ── 诊断：假数据 ──────────────────────────────────────

class _AsyncValue:
    """Tortoise 外键可以 await，例如 ``await user.picture``。"""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _get():
            return self._value

        return _get().__await__()


class FakeQuery:
    def __init__(self, *, first_value=None, records=None):
        self.first_value = first_value
        self.records = list(records or [])

    def order_by(self, *_args):
        return self

    def prefetch_related(self, *_args):
        return self

    async def first(self):
        return self.first_value

    async def all(self):
        return self.records


class FakeRecord:
    def __init__(self, question_id, is_correct=None, content="题干", user_answer=""):
        self.question_id = question_id
        self.is_correct = is_correct
        self.question = SimpleNamespace(content=content)
        self.user_answer = user_answer


class FakeQuestion:
    def __init__(self, question_id, content):
        self.id = question_id
        self.content = content
        self.question_type = "short_answer"
        self.options = None
        self.difficulty = "medium"
        self.knowledge_tags = None


def _install_diagnosis_fakes(monkeypatch, *, record, records):
    async def fake_init_db():
        return None

    def filter_records(**filters):
        if "question_id" in filters:
            return FakeQuery(first_value=record)
        return FakeQuery(records=records)

    monkeypatch.setattr(diagnosis_service, "init_db", fake_init_db)
    monkeypatch.setattr(diagnosis_service.ExamRecord, "filter", filter_records)
    monkeypatch.setattr(diagnosis_service, "parse_traits", lambda _raw: {"onboarding": {}})
    monkeypatch.setattr(
        diagnosis_service.User,
        "filter",
        lambda **_filters: FakeQuery(first_value=SimpleNamespace(picture=_AsyncValue(SimpleNamespace(traits=None)))),
    )


# ── 1. 重复提交能接着走，而不是"该题已经提交过" ──────────────

@pytest.mark.asyncio
async def test_replaying_an_answered_question_returns_the_next_one(monkeypatch):
    """答案已落库但下一题没生成出来时，重试必须能接上，而不是 400 卡死。"""
    already_answered = FakeRecord(1, is_correct=True, user_answer="我的回答")
    answered = [FakeRecord(1, is_correct=True, user_answer="我的回答")]
    submitted = []

    async def fake_submit(*_args, **_kwargs):
        submitted.append(True)
        return {"session_summary": {"percentage": 0.0, "correct_count": 0}}

    async def fake_create_question(_user_id, _session_id, _payload):
        return FakeQuestion(2, "下一题")

    async def fake_generate_question(*_args, **_kwargs):
        return {"content": "下一题", "reference_answer": "答案"}

    async def fake_get_session(*_args, **_kwargs):
        return {}

    _install_diagnosis_fakes(monkeypatch, record=already_answered, records=answered)
    monkeypatch.setattr(diagnosis_service.ExamService, "get_session", staticmethod(fake_get_session))
    monkeypatch.setattr(diagnosis_service, "_submit_open_answer", fake_submit)
    monkeypatch.setattr(diagnosis_service, "_create_question", fake_create_question)
    monkeypatch.setattr(diagnosis_service, "_generate_question", fake_generate_question)

    result = await diagnosis_service.answer(9, "sess-1", 1, "我的回答", None, max_steps=3)

    assert result["finished"] is False
    assert result["question"]["content"] == "下一题"
    # 不能再跑一次 submit_answer：它会重复累加掌握度、学习事件和雷达。
    assert submitted == [], "重复提交不该重新执行判分落库"
    assert result["feedback"]["is_correct"] is True, "反馈要用已落库的判定"


@pytest.mark.asyncio
async def test_replaying_the_last_question_finishes_with_a_real_summary(monkeypatch):
    """重复提交落在最后一题时，也要能拿到成绩收尾，而不是崩在空 summary 上。"""
    answered = [FakeRecord(i, is_correct=True) for i in (1, 2, 3)]
    scheduled = []

    async def fake_get_session(_session_id, _user_id):
        return {"percentage": 66.7, "correct_count": 2}

    async def fake_generate_paths(user_id, direction, goal):
        scheduled.append((user_id, direction, goal))

    _install_diagnosis_fakes(monkeypatch, record=FakeRecord(3, is_correct=True), records=answered)
    monkeypatch.setattr(diagnosis_service.ExamService, "get_session", staticmethod(fake_get_session))
    monkeypatch.setattr(diagnosis_service, "_generate_paths_after_diagnosis", fake_generate_paths)
    monkeypatch.setattr(
        diagnosis_service,
        "parse_traits",
        lambda _raw: {"onboarding": {"direction": "数据分析", "goal": "就业"}},
    )

    result = await diagnosis_service.answer(9, "sess-1", 3, "我的回答", None, max_steps=3)
    await asyncio.sleep(0)

    assert result["finished"] is True
    assert result["result"]["percentage"] == 66.7
    assert result["result"]["correct_count"] == 2
    assert scheduled == [(9, "数据分析", "就业")], "收尾仍要排上路径生成"


# ── 2. 断连不取消业务 ─────────────────────────────────

@pytest.mark.asyncio
async def test_disconnecting_does_not_cancel_the_running_operation():
    """客户端断开后，生成任务要继续跑完，而不是被 finally 取消掉。"""
    started = asyncio.Event()
    finished = []

    async def operation():
        started.set()
        await asyncio.sleep(0.05)
        finished.append(True)
        return {"session_id": "sess-1"}

    agen = diagnosis_router._stream_diagnosis(operation, "正在出题")

    async def consume():
        return [frame async for frame in agen]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.12)
    assert finished == [True], "断连把正在生成的诊断题一起取消了"


@pytest.mark.asyncio
async def test_closing_the_generator_does_not_cancel_the_running_operation():
    """aclose() 是老版本 Starlette 断连的形态，同样不能带走业务。"""
    started = asyncio.Event()
    finished = []

    async def operation():
        started.set()
        await asyncio.sleep(0.05)
        finished.append(True)

    agen = diagnosis_router._stream_diagnosis(operation, "正在出题")
    frame = await agen.__anext__()
    assert "status" in frame
    await asyncio.wait_for(started.wait(), 1)

    await agen.aclose()
    await asyncio.sleep(0.12)
    assert finished == [True]


@pytest.mark.asyncio
async def test_normal_completion_still_returns_the_result_frame():
    """接管逻辑只在断连时生效，正常路径的结果帧不能被吞掉。"""

    async def operation():
        return {"session_id": "sess-1"}

    frames = [frame async for frame in diagnosis_router._stream_diagnosis(operation, "正在出题")]

    assert any('"result"' in frame for frame in frames)
    assert frames[-1] == "data: [DONE]\n\n"


# ── 3. 模型挂住要走兜底，而不是无限等待 ───────────────────

class _HangingLlm:
    async def ainvoke(self, *_args, **_kwargs):
        await asyncio.sleep(30)


@pytest.mark.asyncio
async def test_hung_question_model_falls_back_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(diagnosis_service, "_DIAGNOSIS_LLM_TIMEOUT", 0.05)
    monkeypatch.setattr(llm_config, "llm", _HangingLlm())

    payload = await diagnosis_service._generate_question(9, "学生", "数据分析", "就业", [], 0, 3)

    assert payload["content"], "超时后应返回兜底题，而不是把请求挂死"
    assert payload["reference_answer"]


@pytest.mark.asyncio
async def test_hung_evaluation_model_falls_back_to_keyword_judgement(monkeypatch):
    monkeypatch.setattr(diagnosis_service, "_DIAGNOSIS_LLM_TIMEOUT", 0.05)
    monkeypatch.setattr(llm_config, "llm", _HangingLlm())
    question = SimpleNamespace(
        id=1,
        content="什么是文档切分？",
        answer="按语义边界切分文本",
        analysis='{"evaluation_points": ["语义边界"]}',
    )

    result = await diagnosis_service._evaluate_answer(9, question, "按语义边界切分文本")

    assert result["is_correct"] is True, "兜底判分应识别出参考答案被覆盖"


# ── 4. 画像分析失败降级，而不是 500 ─────────────────────

class FakePicture:
    def __init__(self):
        self.cognition = ""
        self.learning_goal = ""
        self.personality_tags = ""
        self.profile_summary = ""
        self.traits = None
        self.saved = 0

    async def save(self):
        self.saved += 1


class _FailingLlm:
    async def ainvoke(self, *_args, **_kwargs):
        raise RuntimeError("provider exploded: api_key=secret-provider-detail")


def _install_portrait_fakes(monkeypatch, picture):
    user = SimpleNamespace(picture=_AsyncValue(picture))

    monkeypatch.setattr(portrait_service.User, "filter", lambda **_filters: FakeQuery(first_value=user))
    monkeypatch.setattr(llm_config, "llm", _FailingLlm())


@pytest.mark.asyncio
async def test_portrait_analysis_failure_degrades_instead_of_500(monkeypatch):
    """模型挂了仍要落上下文并返回结果 —— 前端的兜底展示分支就等这个返回值。"""
    picture = FakePicture()
    _install_portrait_fakes(monkeypatch, picture)

    result = await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        9,
        [{"question": "你的学习方向？", "answer": "想做数据分析"}],
        onboarding_context={"identity": "学生", "direction": "数据分析", "goal": "就业"},
    )

    assert isinstance(result, dict)
    assert picture.saved == 1, "降级路径仍要把访谈上下文落库"
    traits = portrait_service.parse_traits(picture.traits)
    assert traits["onboarding"]["direction"] == "数据分析"
    assert traits["onboarding"]["goal"] == "就业"
    assert traits["learning_direction"] == "数据分析"
    # 模型没给出摘要，前端据此走"画像分析没有完成"的分支
    assert not result["profile_summary"]


@pytest.mark.asyncio
async def test_portrait_analysis_timeout_also_degrades(monkeypatch):
    picture = FakePicture()
    monkeypatch.setattr(portrait_service, "_PORTRAIT_LLM_TIMEOUT", 0.05)
    user = SimpleNamespace(picture=_AsyncValue(picture))
    monkeypatch.setattr(portrait_service.User, "filter", lambda **_filters: FakeQuery(first_value=user))
    monkeypatch.setattr(llm_config, "llm", _HangingLlm())

    result = await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        9,
        [{"question": "你的学习方向？", "answer": "想做数据分析"}],
        onboarding_context={"identity": "学生", "direction": "数据分析", "goal": "就业"},
    )

    assert isinstance(result, dict)
    assert picture.saved == 1


@pytest.mark.asyncio
async def test_portrait_regenerate_keeps_the_existing_summary_on_failure(monkeypatch):
    """画像总结只是锦上添花，模型挂了不该把 /regenerate 变成 500。"""
    picture = FakePicture()
    picture.profile_summary = "上一次生成的摘要"
    picture.learning_goal = "job"
    _install_portrait_fakes(monkeypatch, picture)

    result = await portrait_service.PortraitChatHistory_Service.regenerate_portrait(9)

    assert result["profile_summary"] == "上一次生成的摘要"
    assert picture.saved == 0, "失败时不该写回任何东西"
