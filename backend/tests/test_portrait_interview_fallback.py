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

import pytest

from backend.src.service.portrait import service as portrait_service

VUE_VIEW = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "features" / "learnmateFlow" / "LearnmateChatView.vue"
)
PORTRAIT_API = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "shared" / "api" / "portraitApi.js"
)
ROUTER_SOURCE = Path(__file__).resolve().parents[1] / "src" / "router" / "portrait_router.py"


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

    这条测试按访谈的真实顺序分三段，因为"回答里有什么"决定了下一问怎么问：
    第 1 问那一轮手上只有第 1 个回答；追问那一轮才有前两个。
    """
    # 1) 第 1 问只答了「1」：这一问是"换一种问法再问方向"，用专门的追问题面，不引用「1」。
    question = portrait_service._fallback_interview_question(1, _dialogue("1"))["question"]
    assert question in portrait_service._DIRECTION_PROBE_QUESTIONS
    assert "「" not in question and "1" not in question

    # 2) 追问答出了方向：从这一问起引用的是补出来的那句，而不是那个「1」。
    dialogue = _dialogue("1", "做客服工单系统")
    assert portrait_service._usable_direction(dialogue) == "做客服工单系统"
    for step in range(2, 5):
        question = portrait_service._fallback_interview_question(step, dialogue)["question"]
        assert "「1」" not in question
        assert "「」" not in question
        assert "1" not in question.replace("第 1 问", "")

    # 3) 一路都没答出方向：整场都用不引用回答的那一套，而不是把「1」放大。
    #    第 2 问是追问（用专门的追问题面），第 3 问起回到不引用回答的通用表 ——
    #    段号跟着 _slot_index 顺延，所以第 3 问拿的是「用途」那一格。
    for step in range(1, 5):
        question = portrait_service._fallback_interview_question(step, _dialogue("1"))["question"]
        assert "「1」" not in question
        assert "「」" not in question
        assert "1" not in question.replace("第 1 问", "")
        expected = (portrait_service._DIRECTION_PROBE_QUESTIONS if step == 1
                    else portrait_service._GENERIC_QUESTION_VARIANTS[
                        portrait_service._slot_index(step, _dialogue("1"))])
        if expected:
            assert question in expected


def test_a_non_answer_still_gets_a_full_interview():
    """降级不能把访谈问残：四问都要有正经题面，不能出现空引号那样的残句。"""
    dialogue = _dialogue("还没想好")
    for step in range(1, 5):
        question = portrait_service._fallback_interview_question(step, dialogue)["question"]
        assert question.strip()
        assert "「" not in question


def test_the_probe_question_is_asked_once_and_only_once():
    """方向只重问一次：第 2 问追问，第 3 问还不知道方向就往下走。

    反复追问会挤掉起点、缺口、练习条件这几段 —— 它们本来就不依赖方向，问出来比
    再要一次「不知道」有用；方向最后由访谈页的补填入口收。

    追问占掉一格，后面的段依次顺延（见 `_slot_index`）：第 3 问 = 用途、第 4 问 = 起点、
    第 5 问 = 缺口，最后一段"练习条件"被挤出访谈。
    """
    dialogue = _dialogue("不知道")
    assert portrait_service._stage_instruction_for(1, dialogue) == portrait_service._DIRECTION_PROBE_STAGE
    assert portrait_service._stage_instruction_for(2, dialogue) == portrait_service._INTERVIEW_STAGES[1]
    assert portrait_service._stage_instruction_for(3, dialogue) == portrait_service._INTERVIEW_STAGES[2]
    assert portrait_service._stage_instruction_for(4, dialogue) == portrait_service._INTERVIEW_STAGES[3]


def test_a_usable_direction_does_not_shift_the_stages():
    """方向正常时阶段一步都不偏移（回归）。"""
    dialogue = _dialogue("机械制图")
    for step in range(5):
        assert portrait_service._stage_instruction_for(step, dialogue) == portrait_service._INTERVIEW_STAGES[step]


def test_the_probe_question_has_exactly_one_question_mark():
    """追问的兜底题面也不能被自己的闸门拦掉（两个问号 = 一次问了多件事）。"""
    for question in portrait_service._DIRECTION_PROBE_QUESTIONS:
        assert portrait_service._question_rejection_reason(question, [], 1) == "", question


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

def _two_part(visible: str, payload: str = '{"finish": false}') -> str:
    """模型按约定写的两段式输出：先给人看的一行，`---`，再是 JSON。"""
    return f"{visible}\n---\n{payload}"


class _FakeModel:
    """模型替身：**分两段**吐字（先正文、再 JSON），和真模型一样。

    一次吐整段的话，"正文先上屏、JSON 还没拼完"这条路径根本没被测到。
    """

    def __init__(self, content):
        self.content = content
        self.calls = []

    async def astream(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        from backend.src.utils.llm_stream import VISIBLE_MARKER

        head, sep, tail = self.content.partition(VISIBLE_MARKER)
        if not sep:
            # 没写分隔行的（老格式，整段 JSON）一次吐完
            yield self.content
            return
        yield head
        await asyncio.sleep(0)
        yield sep + tail


class _DeadModel:
    """模型挂了：连第一个字都出不来。"""

    async def astream(self, *_args, **_kwargs):
        raise RuntimeError("upstream 503")
        yield  # pragma: no cover —— 让它是个异步生成器，异常在迭代时才抛


@pytest.fixture
def llm(monkeypatch):
    """换掉模型，并截下它被等待时的超时。

    超时是从 ``llm_stream.consume_stream`` 这里截的：它用的是 ``asyncio.timeout``
    而不是 ``wait_for``。换的是模块级的名字，真实现照跑。

    顺带把「题面走模型」那条路打开：题面默认从模板表直出（不调模型），而用到这个 fixture
    的测试全都是冲着**模型那条路**来的（阶段锁、题面闸门、流式分片、超时）。不开的话它们
    会变成"在测模板"，看着绿其实什么都没测到。
    """
    from backend.src.ai_core import llm_config
    from backend.src.service.portrait import service as portrait_service
    from backend.src.utils import llm_stream

    monkeypatch.setattr(portrait_service, "_USE_MODEL_QUESTIONS", True)
    fake = _FakeModel(_two_part("对于自动处理客服工单，你之前有没有亲手做过类似的东西？"))
    monkeypatch.setattr(llm_config, "llm", fake)

    captured = {}
    real_consume = llm_stream.consume_stream

    async def _spy(chunks, on_delta=None, timeout=None):
        captured["timeout"] = timeout
        return await real_consume(chunks, on_delta, timeout)

    monkeypatch.setattr(llm_stream, "consume_stream", _spy)
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


@pytest.fixture
def model_questions(monkeypatch):
    """把「题面走模型」那条路打开（默认是模板直出，见 `_USE_MODEL_QUESTIONS`）。

    `llm` fixture 已经自动打开了；下面这几个测试自己换模型，所以要显式要一下 ——
    否则它们测的就是模板，看着绿其实什么都没测到。
    """
    from backend.src.service.portrait import service as portrait_service
    monkeypatch.setattr(portrait_service, "_USE_MODEL_QUESTIONS", True)


@pytest.mark.asyncio
async def test_a_failing_model_call_degrades_and_is_marked_as_fallback(monkeypatch, model_questions):
    from backend.src.ai_core import llm_config

    monkeypatch.setattr(llm_config, "llm", _DeadModel())
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
async def test_the_first_question_is_fixed_and_does_not_wait_for_the_model(llm):
    """第 1 问写死（`_DIRECTION_QUESTION`），**不调模型**。

    它前面没有任何对话可依据，模型在这句话上能加的只有措辞；而代价是每个学生点开访谈后
    都要先对着气泡里的 `···` 等一次首字延迟（这个模型二十几到三十几秒）才看到第一个问题。
    """
    fake, _ = llm
    deltas = []
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, [], step=0, max_steps=5, on_delta=deltas.append,
    )

    assert result["question"] == portrait_service._DIRECTION_QUESTION
    assert result["source"] == "fixed"
    assert not fake.calls, "第 1 问又走模型了：学生要为此白等一次首字延迟"
    # 题面仍然当**流式分片**推给页面：页面因此不需要知道这一问是哪个来源，屏幕上
    # "边写边显示"的那段就是这句；不推的话页面会退回它自己那份本地兜底题。
    assert deltas == [portrait_service._DIRECTION_QUESTION], "题面没有推给页面"


@pytest.mark.asyncio
async def test_the_interview_question_is_not_queued_behind_background_work(llm):
    """访谈题面必须走**高优先级**：它是学生正盯着等的那一次调用。

    标成 low 时它得和"整条路径的资源预生成、课堂过渡摘要、记忆抽取、进阶任务"抢同一条
    全局 10 路的低优先级通道，而且只要后台有高优先级调用在跑就先让它。症状看着像"问一句
    比生成一整章文档还慢"，其实字没多几个字，是排在别人后面。
    """
    fake, _ = llm
    await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=2, max_steps=5,
    )
    assert fake.calls, "模型没有被调用"
    assert fake.calls[0]["priority"] == "high", (
        "访谈题面又标成低优先级了：学生会为后台的资源生成/审核排队"
    )


@pytest.mark.asyncio
async def test_the_whole_interview_runs_without_the_model(monkeypatch):
    """五问都不经过模型 —— 题面全部来自那张模板表。

    这条同时钉住"默认走模板"：把模型换成**必然失败**的替身，五问照样一句不少、各不相同。
    以前每一问都要等一次首字延迟（二十几到三十几秒），整场访谈 3 分半花在"换个措辞"上。
    """
    from backend.src.ai_core import llm_config

    monkeypatch.setattr(llm_config, "llm", _DeadModel())

    questions = []
    for step in range(5):
        dialogue = _dialogue("智能体应用开发") if step else []
        result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
            1, dialogue, step=step, max_steps=5,
        )
        assert result["question"].strip(), f"第 {step + 1} 问是空的"
        assert result["source"] == "fixed"
        questions.append(result["question"])
    assert len(set(questions)) == 5, "五问里有重复的"


@pytest.mark.asyncio
async def test_the_template_question_still_reaches_the_page_as_a_delta():
    """模板题面也要走 on_delta：页面靠分片渲染题面，不推的话它会退回自己那份本地兜底题，
    屏幕上就是另外一句话了。"""
    deltas = []
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=2, max_steps=5, on_delta=deltas.append,
    )
    assert deltas == [result["question"]], "题面没有推给页面"
    assert "「智能体应用开发」" in result["question"], "模板没有引用学生说过的方向"


def test_the_fixed_first_question_passes_its_own_gate():
    """写死的题面也得过那套闸门（长度 / 问号数 / 选择题写法 / 重复）。

    它不经过模型，所以没有任何别的地方会替它检查 —— 写错了（比如手滑打了两个问号）
    不会有人发现，只会在学生那儿出成一道一次问两件事的题。
    """
    question = portrait_service._DIRECTION_QUESTION
    assert portrait_service._question_rejection_reason(question, [], 0) == ""
    # 一次只能问一件事，且要给出可以照着答的例子（第 0 段的规格）。
    assert question.count("？") + question.count("?") == 1
    assert "比如" in question


@pytest.mark.asyncio
async def test_a_dead_model_cannot_break_the_first_question(monkeypatch):
    """模型挂了牵连不到第 1 问 —— 它压根不经过模型，访谈也不会因此开不了场。"""
    from backend.src.ai_core import llm_config

    monkeypatch.setattr(llm_config, "llm", _DeadModel())
    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, [], step=0, max_steps=5,
    )

    assert result["question"] == portrait_service._DIRECTION_QUESTION
    assert result["source"] == "fixed"
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


# ── 题面要边写边推给学生看 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_question_streams_out_before_the_json_is_finished(llm):
    """题面要一个字一个字地推出去，而不是等整段 JSON 拼完再给。

    整段给的话，屏幕在模型想完之前一直是空的（实测第一个字要 20 到 35 秒），
    前端只能垫一句本地模板 —— 学生一动笔，那句模板就留在屏幕上了，看起来就是
    "题目写死的"。这条钉的是"推出去的是题面本身、且中途就推了"。
    """
    pushed: list[str] = []

    await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
        on_delta=pushed.append,
    )

    assert pushed, "一个字都没推出去，等于没流式"
    assert "".join(pushed).startswith("对于自动处理客服工单")
    for piece in pushed:
        assert "{" not in piece and "---" not in piece, f"JSON 尾巴漏到学生眼前了：{piece!r}"


@pytest.mark.asyncio
async def test_a_model_that_ignores_the_format_shows_nothing(monkeypatch, model_questions):
    """模型没写分隔行（老格式，整段 JSON）时一个字都不能推。

    推出去等于把 `{"question": ...}` 原样画到学生眼前 —— 比不流式更糟。这道闸门在
    "模型还没学会新格式"或"提示词被改回去"时才会用到，平时看不见。
    """
    from backend.src.ai_core import llm_config

    monkeypatch.setattr(
        llm_config, "llm",
        _FakeModel('{"question": "你以前试过智能体应用开发吗？", "finish": false}'),
    )
    pushed: list[str] = []

    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
        on_delta=pushed.append,
    )

    assert pushed == [], "整段 JSON 被当正文推给学生了"
    # 不流式不代表拿不到题：JSON 里那一问照样要用
    assert result["question"] == "你以前试过智能体应用开发吗？"


@pytest.mark.asyncio
async def test_the_streamed_question_is_what_gets_returned(llm):
    """返回的题面必须就是已经推给用户的那句：两边不一致等于屏幕上和记录里是两道题。"""
    pushed: list[str] = []

    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
        on_delta=pushed.append,
    )

    assert result["question"] == "".join(pushed).strip()


@pytest.mark.asyncio
async def test_a_rejected_question_is_kept_once_it_has_been_shown(monkeypatch, model_questions):
    """模型这一问不合用时，如果它**已经显示给用户了**，就不再换成兜底模板。

    在用户眼皮底下把一句正在读的问题改样，比留着一句不完美的问题更糟。拦截规则
    退回成"事后告警"。反过来说：一个字都没流出去（老格式整段 JSON）时，
    该拦还是要拦 —— 下面的 test_a_rejected_model_question_falls_back_to_the_stage_template
    钉的就是那一半。
    """
    from backend.src.ai_core import llm_config

    shown = "你想学 A、B、C 哪一个方向？"
    monkeypatch.setattr(llm_config, "llm", _FakeModel(_two_part(shown)))
    pushed: list[str] = []

    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
        on_delta=pushed.append,
    )

    assert "".join(pushed).strip() == shown, "题面没有推出去，这条测试就没测到点子上"
    assert portrait_service._question_rejection_reason(shown, [], 1), "这句本来就该被判为不合用"
    assert result["source"] == "agent"
    assert result["question"] == shown


@pytest.mark.asyncio
async def test_a_partial_stream_is_kept_when_the_model_dies_midway(monkeypatch, model_questions):
    """模型说到一半挂了：已经显示出来的那半句留着，别在用户眼前换成另一句。"""
    from backend.src.ai_core import llm_config
    from backend.src.utils import llm_stream

    class _Halfway:
        async def astream(self, *_args, **_kwargs):
            yield "你以前动手画过零件吗，比如照着图纸"
            raise RuntimeError("stream died")

    monkeypatch.setattr(llm_config, "llm", _Halfway())
    pushed: list[str] = []

    result = await portrait_service.PortraitChatHistory_Service.next_interview_question(
        1, _dialogue("智能体应用开发"), step=1, max_steps=5,
        on_delta=pushed.append,
    )

    assert pushed, "挂之前推出去的那半句没了"
    assert result["question"] == "".join(pushed).strip()
    assert result["source"] == "agent", "半句也是模型写的，不该退成兜底模板"


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


def test_the_interview_page_asks_for_the_streaming_question():
    """访谈页必须走流式那一版。

    整段返回那版要模型全写完（实测几十秒）才回来，前端只能先垫一句本地模板、等
    模型那版回来再替换；学生通常已经动笔，替换条件判不成立，屏幕上留下的永远是那句
    模板 —— 这正是"题目是写死的"这个观感的来源。两处都要钉：页面用流式接口，
    API 模块里确实有那条路径。
    """
    view = VUE_VIEW.read_text(encoding="utf-8")
    assert "streamNextPortraitInterviewQuestion" in view, "访谈页没有走流式接口"
    assert "getNextPortraitInterviewQuestion" not in view, "访谈页还在用整段返回那版"

    api = PORTRAIT_API.read_text(encoding="utf-8")
    assert "'/ai_portrait/interview/next/stream'" in api, "API 模块里没有流式那条路径"
    router = ROUTER_SOURCE.read_text(encoding="utf-8")
    assert '"/interview/next/stream"' in router, "路由里没有流式那条路径（prefix 是 /ai_portrait）"


def test_the_interview_page_renders_the_streamed_question():
    """流出来的字要真的画到屏幕上：只把回调接上、不渲染的话，屏幕还是空的。

    钉到模板那一行：光有 ``liveQuestion`` 这个名字，冒泡里不插值也照样"存在"。
    """
    view = VUE_VIEW.read_text(encoding="utf-8")
    assert "reply_delta" in view, "没有消费流式分片"
    assert 'v-if="liveQuestionStep >= 0"' in view, "流式题面的气泡没有渲染条件"
    assert "{{ liveQuestion" in view, "流式题面的气泡没有把字插进模板"


def test_the_summary_request_outlasts_the_backend_budget():
    """总结页那次画像抽取必须给足超时，否则浏览器会抢在后端前面放弃。

    后端给它留的是 PORTRAIT_LLM_TIMEOUT_SECONDS，而 httpClient 的全局超时是 15 秒 ——
    这个模型光第一个字就要二十几到三十几秒，于是请求**必然**被前端掐断：后端跑完了、
    画像也落库了，只是没人接，总结页永远停在"画像分析没有完成"，再点"重新生成画像"
    还是同一个 15 秒。
    """
    api = PORTRAIT_API.read_text(encoding="utf-8")
    match = re.search(r"const PORTRAIT_TIMEOUT_MS = (\d+)", api)
    assert match, "画像抽取请求没设自己的超时（会落到 httpClient 的 15 秒全局值上）"
    assert "/ai_portrait/init_from_dialogue', payload, { timeout: PORTRAIT_TIMEOUT_MS }" in api, \
        "超时常量定义了却没接到这次请求上"

    client_ms = int(match.group(1))
    backend_ms = portrait_service._PORTRAIT_LLM_TIMEOUT * 1000
    assert client_ms > backend_ms, (
        f"客户端超时 {client_ms}ms 不比后端预算 {backend_ms}ms 宽，"
        "浏览器会先放弃，后端那一版永远到不了总结页"
    )


def test_the_portrait_budget_clears_the_models_first_token_latency():
    """画像抽取要的是**整段**输出，所以预算必须明显高于"第一个字多久出来"。

    这个模型光第一个字就要二十几到三十几秒（访谈那条超时注释里记的是实测值），原来这里
    只给 40 秒，等于刚过首个 token 就把请求掐了 —— 库里最近 4 条画像有 2 条是降级后的
    空摘要。60 秒是"至少留出两倍首字延迟"的下限。
    """
    assert portrait_service._PORTRAIT_LLM_TIMEOUT >= 60, (
        f"画像抽取预算 {portrait_service._PORTRAIT_LLM_TIMEOUT}s 太低："
        "模型首字就要 22-35 秒，整段输出会被从中截断，落库的是空摘要"
    )


# ── 路由真的把分片推出去了吗 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_router_relays_the_streamed_question(monkeypatch):
    """接口存在、路径对，不等于接上了。

    中间少一个 ``on_delta=lambda ...``，题面就永远到不了页面 —— 而所有单元测试
    还是绿的（服务层自己那几条全过）。这条从路由往下走一遍。
    """
    from backend.src.router import portrait_router

    async def fake_next(user_id, dialogue, step=0, max_steps=5, on_delta=None):
        assert on_delta, "路由没把 on_delta 传下来，题面在服务层就流不出去"
        on_delta("你以前动手画过零件")
        on_delta("吗？")
        return {"question": "你以前动手画过零件吗？", "finish": False, "source": "agent"}

    monkeypatch.setattr(
        portrait_router.PortraitChatHistory_Service,
        "next_interview_question",
        staticmethod(fake_next),
    )

    response = await portrait_router.stream_next_interview_question(
        user_id=7,
        data=portrait_router.NextInterviewQuestionRequest(dialogue=[], step=0, max_steps=5),
    )
    text = "".join([chunk async for chunk in response.body_iterator])

    assert '"reply_delta"' in text, "分片没有被推给前端"
    assert "你以前动手画过零件" in text
    assert text.index('"reply_delta"') < text.index('"result"'), "分片必须排在结果帧前面"
    assert text.rstrip().endswith("data: [DONE]")


@pytest.mark.asyncio
async def test_the_router_puts_the_question_in_its_own_bubble(monkeypatch):
    """气泡归属：访谈这一轮只有题面，必须固定推进 "question" 那个气泡。

    channel 写错的话字会跑进判分那个气泡里 —— 屏幕上就是"两句不相干的话粘在一起"。
    """
    from backend.src.router import portrait_router

    async def fake_next(user_id, dialogue, step=0, max_steps=5, on_delta=None):
        on_delta("你以前动手画过零件吗？")
        return {"question": "你以前动手画过零件吗？", "finish": False, "source": "agent"}

    monkeypatch.setattr(
        portrait_router.PortraitChatHistory_Service,
        "next_interview_question",
        staticmethod(fake_next),
    )

    response = await portrait_router.stream_next_interview_question(
        user_id=7,
        data=portrait_router.NextInterviewQuestionRequest(dialogue=[], step=0, max_steps=5),
    )
    text = "".join([chunk async for chunk in response.body_iterator])

    assert '"channel": "question"' in text
