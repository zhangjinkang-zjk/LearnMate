# -*- coding: utf-8 -*-
"""Regression tests for the portrait interview's next-question step.

Two defects, both invisible in production because the failure was logged at
``debug`` level:

1. ``next_interview_question`` wrapped the model call in
   ``asyncio.wait_for(..., timeout=10)``, while this call takes ~50s in practice
   (the prompt is ~1662 chars and the output is a single line of JSON — the slow
   part is the model, not the prompt).  The timeout was therefore *always* hit
   and every one of the five onboarding questions came from
   ``_fallback_interview_question`` instead of the model.

2. ``_fallback_interview_question`` interpolated the first answer verbatim into
   every later question (``如果把「{first}」做好了…``).  When that answer carried
   no direction — ``"1"``, ``"不知道"``, ``"还没想好"`` — the same meaningless
   fragment was repeated across the interview, which is what "五个问题过于生硬"
   looked like from the outside.

Note: these tests use ``@pytest.mark.asyncio`` rather than ``asyncio.run`` — the
latter leaves ``event_loop=None`` behind and silently stops every async test
collected after this file from being awaited.
"""

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.src.service.portrait import service as portrait_service

VUE_VIEW = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "features" / "learnmateFlow" / "LearnmateChatView.vue"
)


def _dialogue(*answers):
    return [{"question": f"第 {i + 1} 问", "answer": answer} for i, answer in enumerate(answers)]


# ── 第 1 题的答案能不能当方向用 ────────────────────────────────────────────

def test_a_real_direction_is_usable():
    assert portrait_service._usable_direction(_dialogue("智能体应用开发")) == "智能体应用开发"


def test_a_long_direction_is_excerpted_like_before():
    answer = "智能体应用开发与多智能体协同编排"
    assert portrait_service._usable_direction(_dialogue(answer)) == answer


@pytest.mark.parametrize("answer", [
    "1", "2", "0", "?", "？", ".", "。",
    "不知道", "还不知道", "不清楚", "不确定", "随便", "都可以", "还没想好", "没有",
    "", "   ",
])
def test_a_non_answer_is_not_usable_as_a_direction(answer):
    assert portrait_service._usable_direction(_dialogue(answer)) == ""


def test_a_single_character_can_still_be_a_direction():
    """单个汉字/字母是可能的方向（"学"），只有单个数字和符号才判为不可用。"""
    assert portrait_service._usable_direction(_dialogue("学")) == "学"
    assert portrait_service._usable_direction(_dialogue("a")) == "a"


def test_no_dialogue_at_all_is_not_usable():
    assert portrait_service._usable_direction([]) == ""
    assert portrait_service._usable_direction(None) == ""


# ── 兜底问题不能把一句无意义的话放大 ──────────────────────────────────────

def test_a_non_answer_is_not_echoed_back_into_later_questions():
    """这是"五个问题过于生硬"的本体：答了「1」，后面每问都在问「1」。

    「」这条断言是必须的：只检查 "「1」" 的话，"拿空串去套模板"（结果是「」，同
    样是一句残句）这种改法会漏过去。
    """
    dialogue = _dialogue("1", "做客服工单系统")
    for step in range(1, 5):
        question = portrait_service._fallback_interview_question(step, dialogue)["question"]
        assert "「1」" not in question
        assert "「」" not in question
        assert "1" not in question.replace("第 1 问", "")
        # 引用过回答的那几问，必须整句换成不引用回答的那一套，
        # 而不是拼出一句带空引号的话。（第 4、5 问本来就不引用回答，
        # 它们的通用表是空的，落到原表即可。）
        if portrait_service._GENERIC_QUESTION_VARIANTS[step]:
            assert question in portrait_service._GENERIC_QUESTION_VARIANTS[step]


def test_a_non_answer_still_gets_a_full_interview():
    """降级不能把访谈问残：四问都要有正经题面，不能出现空引号那样的残句。"""
    dialogue = _dialogue("还没想好")
    for step in range(1, 5):
        question = portrait_service._fallback_interview_question(step, dialogue)["question"]
        assert question.strip()
        assert "「" not in question


def test_a_real_direction_is_still_echoed_back():
    """修的是"拿不到方向时不要硬套"，不是把引用用户原话这个能力整个去掉。"""
    dialogue = _dialogue("智能体应用开发", "做客服工单系统")
    question = portrait_service._fallback_interview_question(2, dialogue)["question"]
    assert "「智能体应用开发」" in question


def test_the_first_question_never_depends_on_the_earlier_answer():
    question = portrait_service._fallback_interview_question(0, [])["question"]
    assert question
    assert "「" not in question


def test_every_step_returns_a_question_either_way():
    for usable in (_dialogue("1"), _dialogue("智能体应用开发")):
        for step in range(5):
            question = portrait_service._fallback_interview_question(step, usable)["question"]
            assert question.strip(), f"step={step} 兜底问题为空"


def test_finish_is_reported_on_the_last_step():
    assert portrait_service._fallback_interview_question(4, _dialogue("1"), 5)["finish"] is True
    assert portrait_service._fallback_interview_question(1, _dialogue("1"), 5)["finish"] is False


# ── 模型调用必须有一个跑得完的超时 ────────────────────────────────────────

class _AsyncioSpy:
    """``portrait_service.asyncio`` 的替身：只截 ``wait_for`` 的超时，其余原样转发。

    直接 monkeypatch 真 ``asyncio.wait_for`` 会连带改到 pytest-asyncio 自己的机制，
    所以换的是这个模块级的名字，全局模块不动。
    """

    def __init__(self, captured):
        self._captured = captured

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def wait_for(self, coro, timeout=None):
        self._captured["timeout"] = timeout
        return await asyncio.wait_for(coro, timeout=timeout)


@pytest.fixture
def llm(monkeypatch):
    """Replace the model with a stub, and capture the timeout it is awaited with."""
    from backend.src.ai_core import llm_config

    class _Fake:
        def __init__(self, content):
            self.content = content
            self.calls = []

        async def ainvoke(self, prompt, **kwargs):
            self.calls.append({"prompt": prompt, **kwargs})
            return SimpleNamespace(content=self.content)

    fake = _Fake('{"question": "对于自动处理客服工单，你之前有没有亲手做过类似的东西？", "finish": false}')
    monkeypatch.setattr(llm_config, "llm", fake)

    captured = {}
    monkeypatch.setattr(portrait_service, "asyncio", _AsyncioSpy(captured))
    return fake, captured


@pytest.mark.asyncio
async def test_the_model_call_is_not_given_a_ten_second_budget(llm):
    """原来写死 timeout=10，而这一问实测要 ~50 秒 —— 等于每一问都必然超时。"""
    _, captured = llm
    await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
    )

    assert captured["timeout"] == portrait_service._INTERVIEW_LLM_TIMEOUT
    assert captured["timeout"] > 50, "实测这一问要 ~50 秒，超时必须留出余量"


@pytest.mark.asyncio
async def test_the_model_question_is_returned_and_marked_as_agent(llm):
    fake, _ = llm
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
    )

    assert result["source"] == "agent"
    assert result["question"].startswith("对于自动处理客服工单")
    assert fake.calls, "模型没有被调用"


@pytest.mark.asyncio
async def test_a_failing_model_call_degrades_and_is_marked_as_fallback(monkeypatch):
    from backend.src.ai_core import llm_config

    class _Boom:
        async def ainvoke(self, *_args, **_kwargs):
            raise RuntimeError("upstream 503")

    monkeypatch.setattr(llm_config, "llm", _Boom())
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
    )

    assert result["source"] == "fallback"
    assert result["question"].strip()


@pytest.mark.asyncio
async def test_a_question_outside_the_length_window_is_not_used(llm):
    """长度闸门只在 8..90 之间放行；不放行时必须降级，而不是回一句空题。"""
    fake, _ = llm
    fake.content = '{"question": "' + "很长的问题" * 40 + '"}'
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
    )

    assert result["source"] == "fallback"
    assert result["question"].strip()


@pytest.mark.asyncio
async def test_the_first_question_comes_from_the_model_too(llm):
    """第 1 问以前是本地直出（源码里那句 `not dialogue_text and step == 0` 早退），
    结果是每个学生的第一问都是同一句模板 —— 前端的替换条件是 source === 'agent'，
    兜底题的 source 是 'fallback'，模型那一版永远换不上去。

    这里钉住"第一问也交给模型"，同时钉住调用参数：它拿的是空的已有对话，模型要靠
    第 1 段的阶段指令（确认学习方向）出题。
    """
    fake, captured = llm
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, [], step=0, max_steps=5,
    )

    assert result["source"] == "agent", "第一问又被本地兜底接走了"
    assert result["question"].startswith("对于自动处理客服工单")
    assert fake.calls, "模型没有被调用，第一问还是写死的那句"
    assert captured["timeout"] == portrait_service._INTERVIEW_LLM_TIMEOUT
    prompt = fake.calls[0]["prompt"]
    assert portrait_service._INTERVIEW_STAGES[0] in prompt, "第 1 问没拿到第 1 段的阶段指令"
    assert "暂无" in prompt, "空对话没有被提示词接住，模型会以为前面已经聊过"
    assert "{stage_instruction}" not in prompt and "{dialogue_text}" not in prompt


@pytest.mark.asyncio
async def test_a_dead_model_still_gives_a_first_question(monkeypatch):
    """第一问交给模型之后，模型挂掉不能变成一道开不了的访谈。"""
    from backend.src.ai_core import llm_config

    class _Boom:
        async def ainvoke(self, *_args, **_kwargs):
            raise RuntimeError("upstream 503")

    monkeypatch.setattr(llm_config, "llm", _Boom())
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, [], step=0, max_steps=5,
    )

    assert result["source"] == "fallback"
    assert result["question"].strip()
    assert "「" not in result["question"], "第一问没有可引用的回答，不该出现空引号"


@pytest.mark.asyncio
async def test_a_finished_interview_returns_an_empty_question():
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=5, max_steps=5,
    )
    assert result == {"question": "", "finish": True}


# ── 阶段锁：模型只能看到当前这一问的范围 ──────────────────────────────────

def test_every_interview_stage_has_a_generic_fallback():
    """阶段表和"不引用回答"的兜底表描述的是同一条五段式访谈，长度必须对得上。"""
    assert len(portrait_service._INTERVIEW_STAGES) == len(portrait_service._GENERIC_QUESTION_VARIANTS)
    assert len(portrait_service._INTERVIEW_STAGES) == 5
    for index, stage in enumerate(portrait_service._INTERVIEW_STAGES):
        # 每段都必须同时写明"问什么"和"不要问什么"。后半句才是防跑偏的那一半：
        # 少了它，模型只知道这一段的主题，仍会顺手把后面阶段的问题一起问了。
        assert "不要" in stage, f"第 {index} 段没有写明「不要问什么」：{stage!r}"
        assert stage.rstrip().endswith("。"), f"第 {index} 段像是被截断了：{stage!r}"


@pytest.mark.asyncio
async def test_the_prompt_carries_only_the_current_stage(llm):
    """把阶段锁在服务端：模型看不到后面要问什么，就跳不了阶段、跑不了题。"""
    fake, _ = llm
    await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=2, max_steps=5,
    )

    prompt = fake.calls[0]["prompt"]
    assert portrait_service._INTERVIEW_STAGES[2] in prompt
    for index, stage in enumerate(portrait_service._INTERVIEW_STAGES):
        if index != 2:
            assert stage not in prompt, f"第 {index} 段的指令也进了提示词，模型可以自己挑阶段"
    assert "{stage_instruction}" not in prompt


@pytest.mark.asyncio
async def test_the_stage_advances_with_the_step(llm):
    fake, _ = llm
    for step in (1, 2, 3, 4):
        fake.calls.clear()
        await portrait_service.PortraitChatHistory_Service.next_interview_question(
            1, _dialogue("智能体应用开发"), step=step, max_steps=5,
        )
        assert portrait_service._INTERVIEW_STAGES[step] in fake.calls[0]["prompt"]


# ── 一眼就不对的模型问题要拦下来 ──────────────────────────────────────────

@pytest.mark.parametrize("question, hint", [
    ("", "空问题"),
    ("   ", "空问题"),
    ("学吗？", "太短"),
    ("很长的问题" * 40, "太长"),
    ("你试过什么？那你卡在哪一步？", "一次问了多件事"),
    ("你想学 A、B、C 哪一个？", "问成了选择题"),
])
def test_an_unusable_model_question_is_rejected(question, hint):
    assert hint in portrait_service._question_rejection_reason(question, [], 1)


def test_a_repeated_question_is_rejected_even_with_different_punctuation():
    """快速模型最常见的毛病是换个标点把上一问再问一遍。"""
    dialogue = [{"question": "你以前试过智能体应用开发吗？", "answer": "试过一点"}]
    reason = portrait_service._question_rejection_reason("你以前试过智能体应用开发吗?", dialogue, 2)
    assert "重复" in reason


def test_a_natural_on_stage_question_is_accepted():
    dialogue = [{"question": "你想学什么？", "answer": "智能体应用开发"}]
    question = "对于自动处理客服工单，你之前有没有亲手做过类似的东西，比如写过脚本或调用过 API？"
    assert portrait_service._question_rejection_reason(question, dialogue, 2) == ""


def test_a_question_with_a_single_question_mark_is_not_a_compound():
    """一个问号是正常问题；只有两个以上才算"一次问了多件事"。"""
    assert portrait_service._question_rejection_reason("你以前试过这个方向吗？", [], 2) == ""


@pytest.mark.asyncio
async def test_a_rejected_model_question_falls_back_to_the_stage_template(llm):
    fake, _ = llm
    fake.content = '{"question": "你想学 A、B、C 哪一个方向？"}'
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
    )

    assert result["source"] == "fallback"
    assert "A、B、C" not in result["question"]
    assert result["question"].strip()


@pytest.mark.asyncio
async def test_a_repeated_model_question_falls_back(llm):
    fake, _ = llm
    fake.content = '{"question": "你以前试过智能体应用开发吗？"}'
    dialogue = [
        {"question": "你以前试过智能体应用开发吗?", "answer": "智能体应用开发"},
        {"question": "第 2 问", "answer": "做客服工单"},
    ]
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, dialogue, step=2, max_steps=5,
    )

    assert result["source"] == "fallback"


# ── 前端那份兜底表必须和后端一致 ──────────────────────────────────────────

def test_the_frontend_non_answer_list_matches_the_backend():
    """访谈页有一份自己的兜底表（请求失败时用），两份表漂移会让同一个回答
    在后端被判成"方向"、在前端被判成"非答案"，题面随网络状况变样。"""
    source = VUE_VIEW.read_text(encoding="utf-8")
    block = source.split("const NON_DIRECTION_ANSWERS = new Set([", 1)[1].split("])", 1)[0]
    frontend = {
        token.strip().strip("'\"")
        for token in block.replace("\n", " ").split(",")
        if token.strip()
    }

    assert frontend, "没能从 LearnmateChatView.vue 里解析出 NON_DIRECTION_ANSWERS"
    assert frontend == portrait_service._NON_DIRECTION_ANSWERS


def test_the_frontend_generic_questions_match_the_backend():
    """同一份"不引用回答"的题面在后端和访谈页各存了一份，漂移的话同一次访谈
    会因为网络状况不同而给到两句不一样的话。"""
    source = VUE_VIEW.read_text(encoding="utf-8")
    block = source.split("const genericQuestionVariants = [", 1)[1].split("\n]", 1)[0]
    frontend = set(re.findall(r"'([^']+)'", block))

    backend = {question for stage in portrait_service._GENERIC_QUESTION_VARIANTS for question in stage}

    assert frontend, "没能从 LearnmateChatView.vue 里解析出 genericQuestionVariants"
    assert frontend == backend
