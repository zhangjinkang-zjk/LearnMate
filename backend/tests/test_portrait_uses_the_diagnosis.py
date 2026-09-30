# -*- coding: utf-8 -*-
"""基础测评（诊断）的结果要真的进画像。

前端 PortraitSummaryPage 一直把它当 `assessment` 发给 /ai_portrait/init_from_dialogue，
而后端 `InitFromDialogueRequest` 里没有这个字段 —— Pydantic 默认忽略多余字段，请求照常
200，分数就这么没了。所以页面上那句"正在结合访谈与基础测评生成综合画像"是假的：诊断
只起了个门槛作用（前端拿它判断"到底做没做诊断"），从没参与过画像。

修法是三处一起：接口收下它 → 服务把它写进提示词 → 顺手存进 traits 备查。这里逐个钉住，
另外钉住"没有测评结果时不能污染提示词"。
"""

from types import SimpleNamespace

import pytest

from backend.src.router.portrait_router import DiagnosisAssessment, InitFromDialogueRequest
from backend.src.service.portrait import service as portrait_service

ASSESSMENT = {
    "percentage": 60,
    "correct_count": 3,
    "total_questions": 5,
    "message": "已经具备部分基础，建议先补齐关键方法，再进入项目练习。",
}


# ── 接口这一层：字段收不收得下 ────────────────────────

def test_the_endpoint_accepts_the_assessment_field():
    """这是那个 bug 的本体：字段不存在时 Pydantic 不报错，只把它丢掉。"""
    request = InitFromDialogueRequest(dialogue=[], assessment=ASSESSMENT)

    assert request.assessment is not None
    assert request.assessment.percentage == 60
    assert request.assessment.correct_count == 3
    assert request.assessment.total_questions == 5
    assert "已经具备部分基础" in request.assessment.message


def test_an_old_request_without_the_assessment_still_works():
    """老客户端不带这个字段，不能变成 422。"""
    request = InitFromDialogueRequest(dialogue=[], identity="学生", direction="RAG")

    assert request.assessment is None
    assert request.direction == "RAG"


@pytest.mark.parametrize("bad", [
    {"percentage": 200},          # 超出百分比范围
    {"percentage": -1},
    {"percentage": 0, "correct_count": -3},
    {"percentage": 0, "message": "x" * 500},   # message 要进提示词，得有上限
])
def test_out_of_range_assessment_is_rejected(bad):
    with pytest.raises(Exception):
        InitFromDialogueRequest(dialogue=[], assessment=bad)


def test_the_shape_the_frontend_actually_sends_is_accepted():
    """照 DiagnosisPage 写进 sessionStorage 的那份原样来一遍。

    这份里带一个 session_id（诊断的会话号）。它**必须被收下**：服务端靠它回查那几道题的
    问答原话（见下方"问答原话这一层"），滤掉它就等于原话永远进不了画像。
    """
    written_by_frontend = {
        "session_id": "47d0e0f1a2b3",
        "percentage": 60,
        "correct_count": 3,
        "total_questions": 5,
        "message": "已经具备部分基础，建议先补齐关键方法，再进入项目练习。",
    }

    request = InitFromDialogueRequest(dialogue=[], assessment=written_by_frontend)

    assert request.assessment.percentage == 60
    assert request.assessment.session_id == "47d0e0f1a2b3", "会话号被丢掉，原话就回查不到了"


def test_an_old_client_without_the_session_id_still_works():
    """老客户端的 assessment 里没有会话号，不能变成 422，只是查不到原话而已。"""
    request = InitFromDialogueRequest(dialogue=[], assessment=ASSESSMENT)

    assert request.assessment.session_id == ""


def test_the_route_hands_the_assessment_to_the_service():
    """接口收下了不等于往下传了。"""
    import inspect
    from backend.src.router import portrait_router

    endpoint = inspect.getsource(portrait_router.init_from_dialogue)
    assert "assessment=data.assessment" in endpoint, "接口收下了却没往下传"


# ── 真跑一遍：模型拿到的那段提示词里有没有这次测评 ────
#
# 前面那些只看接口和函数的形状，看不到"测评分数到底有没有进提示词"。这里把 User、
# 画像记录和模型都换掉，只留服务自己的拼装逻辑，抓住真发给模型的那段文本。

DIALOGUE = [
    {"question": "你想系统学哪个方向？", "answer": "智能体应用开发"},
    {"question": "准备拿它做什么？", "answer": "做客服工单系统"},
]


class _AsyncValue:
    """Tortoise 的外键是 awaitable：`picture = await user.picture`。"""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _get():
            return self._value

        return _get().__await__()


class _FakePicture:
    def __init__(self):
        self.cognition = ""
        self.learning_goal = ""
        self.personality_tags = ""
        self.profile_summary = ""
        self.traits = None

    async def save(self):
        return None


def _fake_world(monkeypatch, prompts: list[str]):
    picture = _FakePicture()

    class _Query:
        async def first(self):
            return SimpleNamespace(picture=_AsyncValue(picture))

    class _Llm:
        async def ainvoke(self, prompt, **_kwargs):
            prompts.append(prompt)
            return SimpleNamespace(content='{"profile_summary": "起点在起步阶段，建议先补概念。"}')

    from backend.src.ai_core import llm_config

    monkeypatch.setattr(portrait_service.User, "filter", lambda **_f: _Query())
    monkeypatch.setattr(llm_config, "llm", _Llm())
    return picture


@pytest.mark.asyncio
async def test_the_model_is_told_about_the_assessment(monkeypatch):
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        1, DIALOGUE, assessment=ASSESSMENT,
    )

    assert prompts, "模型没被调用"
    prompt = prompts[0]
    assert "{assessment_text}" not in prompt, "占位符没填，模型看到的是花括号"
    assert "60%" in prompt and "答对 3/5 题" in prompt, "这次测评没进提示词，画像用不上它"
    assert "已经具备部分基础" in prompt


@pytest.mark.asyncio
async def test_the_model_is_told_when_there_is_no_assessment(monkeypatch):
    """没做测评时也得说清，不能让模型自己猜或凭空提"测评"。"""
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(1, DIALOGUE)

    assert "没有基础测评结果" in prompts[0]


@pytest.mark.asyncio
async def test_the_assessment_survives_in_the_saved_portrait(monkeypatch):
    """画像之外的地方要能查"这个起点是怎么来的"。"""
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)

    result = await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        1, DIALOGUE, assessment=ASSESSMENT,
    )

    stored = (result.get("traits") or {}).get("onboarding") or {}
    assert stored.get("assessment", {}).get("percentage") == 60.0
    assert stored.get("assessment", {}).get("correct_count") == 3


@pytest.mark.asyncio
async def test_nothing_is_recorded_when_no_assessment_was_taken(monkeypatch):
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)

    result = await portrait_service.PortraitChatHistory_Service.init_from_dialogue(1, DIALOGUE)

    stored = (result.get("traits") or {}).get("onboarding") or {}
    assert "assessment" not in stored, "没做测评却记了一笔，会被读成「测了」"


# ── 提示词这一层：有没有被真实填进去 ──────────────────

def test_a_real_assessment_reaches_the_prompt():
    from backend.src.utils.prompt_loader import fill_prompt, load_prompt

    template = load_prompt("portrait/init_from_dialogue")
    prompt = fill_prompt(
        template,
        dialogue_text="AI第1问：你想学什么？\n用户回答：智能体应用开发",
        assessment_text=portrait_service._format_assessment(ASSESSMENT),
        diagnosis_text="测评第1题：工具调用和普通问答的差别？\n学生作答：它自己能决定下一步。",
    )

    assert "{assessment_text}" not in prompt, "占位符没被替换，模型会看到花括号"
    assert "{diagnosis_text}" not in prompt, "占位符没被替换，模型会看到花括号"
    assert "基础测评" in prompt
    assert "60%" in prompt
    assert "答对 3/5 题" in prompt
    assert "它自己能决定下一步。" in prompt, "原话没进提示词"


def test_the_prompt_tells_the_model_what_to_do_without_one():
    """没有测评结果时不能只说"没有" —— 得说清这段时间按访谈判断。"""
    from backend.src.utils.prompt_loader import fill_prompt, load_prompt

    prompt = fill_prompt(
        load_prompt("portrait/init_from_dialogue"),
        dialogue_text="AI第1问：你想学什么？\n用户回答：智能体应用开发",
        assessment_text=portrait_service._format_assessment(None),
        diagnosis_text="（这次没有取到基础测评的问答原话，只按上面的统计和访谈记录判断。）",
    )

    assert "没有基础测评结果" in prompt
    assert "没有取到基础测评的问答原话" in prompt
    assert "不要凭空提到" in prompt, "少了这句，模型在没有测评时也会写「结合你的测评结果」"


def test_the_prompt_has_a_slot_for_the_transcript():
    from backend.src.utils.prompt_loader import load_prompt

    assert "{diagnosis_text}" in load_prompt("portrait/init_from_dialogue")


def test_the_prompt_no_longer_calls_the_diagnosis_objective():
    """模板里原来写的是"基础测评是访谈之后的客观题结果"。

    诊断早就改成自由问答了（见 docs/系统设计.md）—— 而那句话正是模型判断"那几段原话
    能不能当依据用"的前提。写错前提，模型就会把学生的原话当成选择题的对错去读。
    """
    from backend.src.utils.prompt_loader import load_prompt

    template = load_prompt("portrait/init_from_dialogue")

    assert "客观题" not in template
    assert "自由问答" in template


# ── 文本这一层：怎么拼 ────────────────────────────────

def test_a_full_assessment_is_summarised_in_one_line():
    text = portrait_service._format_assessment(ASSESSMENT)

    assert "60%" in text
    assert "3/5" in text
    assert "已经具备部分基础" in text
    assert "。。" not in text, "评语本身带句号，再补一个就成了双句号"
    assert "\n" not in text, "这是一行输入，不该带换行"


@pytest.mark.parametrize("empty", [None, {}, {"percentage": "不是数字"}, {"percentage": None}])
def test_a_missing_assessment_says_so_instead_of_nothing(empty):
    """返回空串的话，提示词那一段就是一片空白，模型会猜自己是不是漏了什么。"""
    text = portrait_service._format_assessment(empty)

    assert text.strip()
    assert "没有基础测评结果" in text


def test_a_zero_score_is_a_result_not_a_missing_value():
    """0 分是最需要被看见的起点，不能被当成"没做测评"。"""
    text = portrait_service._format_assessment({"percentage": 0, "correct_count": 0, "total_questions": 5})

    assert "没有基础测评结果" not in text
    assert "0%" in text


# ── 落库这一层：之后还查得到吗 ────────────────────────

def test_a_valid_assessment_is_kept_for_later():
    cleaned = portrait_service._clean_assessment(ASSESSMENT)

    assert cleaned["percentage"] == 60.0
    assert cleaned["correct_count"] == 3
    assert cleaned["total_questions"] == 5
    assert "已经具备部分基础" in cleaned["message"]


@pytest.mark.parametrize("empty", [None, {}, {"percentage": "x"}, {"percentage": None}])
def test_a_missing_assessment_is_not_written_at_all(empty):
    """没有就是没有，别落一个 0 分的假记录 —— 那会被读成"测了，得了 0 分"。"""
    assert portrait_service._clean_assessment(empty) is None


def test_unknown_fields_are_dropped_before_they_are_stored():
    cleaned = portrait_service._clean_assessment({**ASSESSMENT, "偷偷加的东西": "x", "session_id": "abc"})

    assert set(cleaned) <= {"percentage", "correct_count", "total_questions", "message"}


def test_the_stored_assessment_goes_under_onboarding():
    """和 identity/direction/goal 放一起（诊断写的那一份也是这个键），不新开一个顶层键。"""
    import inspect

    source = inspect.getsource(portrait_service.PortraitChatHistory_Service.init_from_dialogue)
    assert 'onboarding["assessment"] = assessment_record' in source
    assert 'traits["onboarding"] = onboarding' in source


# ── 问答原话这一层：正文才是"为什么" ──────────────────
#
# 上面那些只保证"统计"进了画像。诊断是自由问答，学生写的那几段字里装着他实际的理解和
# 卡点，而原先一个字都没进过提示词 —— 画像只能看到"答对 3/5 题"，看不到他答错在哪、
# 用不用术语、能不能举例。原话由服务端按会话号回查（不采信客户端上传的正文），
# 所以这里连查询条件一起钉住。

class _FakeQuestion:
    def __init__(self, content):
        self.content = content


class _FakeExamRecord:
    def __init__(self, content, user_answer):
        self.question = _FakeQuestion(content)
        self.user_answer = user_answer


class _RecordQuery:
    def __init__(self, rows):
        self._rows = rows

    def order_by(self, *args, **kwargs):
        return self

    def prefetch_related(self, *args, **kwargs):
        return self

    async def all(self):
        return list(self._rows)


def _fake_exam_records(monkeypatch, rows, calls):
    """ExamRecord 在服务里是**函数内局部导入**的，所以要打在模型模块上。"""
    from backend.src.models import exam_model

    class _Model:
        def filter(self, **kwargs):
            calls.append(kwargs)
            return _RecordQuery(rows)

    monkeypatch.setattr(exam_model, "ExamRecord", _Model())
    return calls


ASSESSMENT_WITH_SESSION = {**ASSESSMENT, "session_id": "47d0e0f1a2b3"}

TRANSCRIPT = [
    _FakeExamRecord("智能体和平时用的聊天机器人最大差别在哪？", "它有工具调用，能自己决定下一步做什么。"),
    _FakeExamRecord("如果工具返回失败了呢？", "不知道"),
]


@pytest.mark.asyncio
async def test_the_students_own_words_reach_the_prompt(monkeypatch):
    """核心回归：那几段原话必须进提示词，不能只有"答对 3/5 题"这半句。"""
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)
    _fake_exam_records(monkeypatch, TRANSCRIPT, [])

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        1, DIALOGUE, assessment=ASSESSMENT_WITH_SESSION,
    )

    prompt = prompts[0]
    assert "{diagnosis_text}" not in prompt, "占位符没填，模型看到的是花括号"
    assert "它有工具调用，能自己决定下一步做什么。" in prompt, "学生的原话没进提示词"
    assert "如果工具返回失败了呢？" in prompt, "题目原话没进提示词"


@pytest.mark.asyncio
async def test_the_transcript_is_looked_up_by_user_and_session_together(monkeypatch):
    """session_id 是客户端传上来的。只按它查 = 拿别人的会话号就能读别人的作答。"""
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)
    calls: list[dict] = []
    _fake_exam_records(monkeypatch, TRANSCRIPT, calls)

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        7, DIALOGUE, assessment=ASSESSMENT_WITH_SESSION,
    )

    assert calls, "没有回查诊断原话"
    assert calls[0]["user_id"] == 7, "没按当前登录用户过滤"
    assert calls[0]["session_id"] == "47d0e0f1a2b3"


@pytest.mark.asyncio
async def test_no_session_id_means_no_lookup_at_all(monkeypatch):
    """老客户端不带会话号：不能因此查一次库，更不能报错。"""
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)
    calls: list[dict] = []
    _fake_exam_records(monkeypatch, TRANSCRIPT, calls)

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        1, DIALOGUE, assessment=ASSESSMENT,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_a_missing_transcript_says_so_instead_of_leaving_a_blank(monkeypatch):
    """和 assessment_text 同一个道理：空串会让模型对着空白猜自己是不是漏了什么。"""
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)
    _fake_exam_records(monkeypatch, [], [])

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        1, DIALOGUE, assessment=ASSESSMENT_WITH_SESSION,
    )

    assert "{diagnosis_text}" not in prompts[0]
    assert "没有取到基础测评的问答原话" in prompts[0]


@pytest.mark.asyncio
async def test_a_broken_lookup_does_not_take_down_the_portrait(monkeypatch):
    """回查原话是加分项。它挂了不能让"访谈收尾"整个 500 ——
    那会把用户卡在总结页反复点重试，而这正是下面模型那段小心避开的结局。"""
    prompts: list[str] = []
    _fake_world(monkeypatch, prompts)
    from backend.src.models import exam_model

    class _Boom:
        def filter(self, **kwargs):
            raise RuntimeError("数据库炸了")

    monkeypatch.setattr(exam_model, "ExamRecord", _Boom())

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        1, DIALOGUE, assessment=ASSESSMENT_WITH_SESSION,
    )

    assert prompts, "画像流程被一次回查失败带塌了"
    assert "没有取到基础测评的问答原话" in prompts[0]


@pytest.mark.asyncio
async def test_an_unanswered_question_is_still_shown(monkeypatch):
    """空作答本身就是信息（概念空白），跳过它会让模型以为这题压根不存在。"""
    _fake_exam_records(monkeypatch, [_FakeExamRecord("解释一下工具调用", "")], [])

    text = await portrait_service._load_diagnosis_transcript(1, "abc123")

    assert "解释一下工具调用" in text
    assert "（没有作答）" in text


@pytest.mark.asyncio
async def test_the_transcript_keeps_the_asking_order(monkeypatch):
    _fake_exam_records(monkeypatch, TRANSCRIPT, [])

    text = await portrait_service._load_diagnosis_transcript(1, "abc123")

    assert text.index("测评第1题") < text.index("测评第2题")
    assert text.index("智能体和平时用的聊天机器人") < text.index("如果工具返回失败了呢？")


@pytest.mark.asyncio
async def test_a_blank_session_id_returns_nothing(monkeypatch):
    calls: list[dict] = []
    _fake_exam_records(monkeypatch, TRANSCRIPT, calls)

    assert await portrait_service._load_diagnosis_transcript(1, "   ") == ""
    assert calls == []
