# -*- coding: utf-8 -*-
"""学习方向要么是真的，要么就是没有 —— 不能拿一个空回答凑数。

起因（已从库里查证）：学生第 1 问答「不知道」，这个字符串被原样当成学习方向写进画像，
再被拿去拆科目、生成路径，最后长出一整套"副业赚钱"的营销课（`user_picture.id=19` 的
`onboarding.direction='不知道'`、`learning_direction_subjects=['数字工具与平台操作',
'内容创作与设计方法','在线营销与推广策略','财务与时间管理技巧']`，`learning_paths` 里
就是这三条 subject）。

判「这类回答不算数」的 `_NON_DIRECTION_ANSWERS` 表一直都有，但**只用它换过题面措辞**，
从没接到落盘那条路上。这份测试钉的就是那条路：判定（`is_usable_direction`）、访谈里的
追问、以及三处落库点。
"""

import json

import pytest
from types import SimpleNamespace

from backend.src.service.diagnosis import service as diagnosis_service
from backend.src.service.portrait import service as portrait_service

VUE_VIEW = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "features" / "learnmateFlow" / "LearnmateChatView.vue"
)


# ── 判定 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "不知道", "还不知道", "不清楚", "随便", "都行", "还没想好", "没想好",
    "1", "0", "。", "？", "?", "无", "没有", "test", "测试",
    "", "   ", None,
])
def test_a_content_free_answer_is_not_a_direction(value):
    assert portrait_service.is_usable_direction(value) is False


@pytest.mark.parametrize("value", [
    "机械制图", "智能体应用开发", "数据分析", "学", "a", "MCP",
    " 机械制图 ",  # 前后空白不该影响判定
])
def test_a_real_direction_is_a_direction(value):
    assert portrait_service.is_usable_direction(value) is True


def test_whitespace_is_collapsed_before_judging():
    """"不 知 道" 和 "不知道" 是同一个人说了同一句废话。"""
    assert portrait_service.is_usable_direction("不 知 道") is False


def test_one_character_is_only_usable_when_it_is_a_letter():
    """单个汉字/字母可能是方向（"学"），单个数字和符号不是。"""
    assert portrait_service.is_usable_direction("学") is True
    assert portrait_service.is_usable_direction("1") is False
    assert portrait_service.is_usable_direction("。") is False


# ── 访谈里"换一种问法再问一次" ────────────────────────────────────────────

def test_the_first_question_still_asks_for_the_direction():
    """正常路径不变：第 1 问（step=0）永远是第 0 段，一次都不偏移。"""
    assert portrait_service._stage_instruction_for(0, []) == portrait_service._INTERVIEW_STAGES[0]
    assert portrait_service._stage_instruction_for(0, [{"question": "问", "answer": "不知道"}]) \
        == portrait_service._INTERVIEW_STAGES[0]


def test_the_second_question_re_asks_the_direction_when_it_is_missing():
    """第 1 问答「不知道」→ 第 2 问换一种问法继续问方向，而不是去问"你打算怎么用它"。"""
    dialogue = [{"question": "你想学什么？", "answer": "不知道"}]
    assert portrait_service._stage_instruction_for(1, dialogue) == portrait_service._DIRECTION_PROBE_STAGE
    assert portrait_service._DIRECTION_PROBE_STAGE != portrait_service._INTERVIEW_STAGES[1]


def test_the_probe_instruction_is_one_string_not_a_tuple():
    """拼字符串时漏一个逗号它就成了元组，进提示词的会是 `('...',)` 这种东西。"""
    assert isinstance(portrait_service._DIRECTION_PROBE_STAGE, str)
    assert isinstance(portrait_service._INTERVIEW_STAGES, tuple)
    for stage in portrait_service._INTERVIEW_STAGES:
        assert isinstance(stage, str)


def test_the_probe_instruction_tells_the_model_how_to_ask_differently():
    """追问必须换入口（在上的课／在做的事），否则学生只会再答一次「不知道」。"""
    for hint in ("不要再问一遍", "例子", "一个词", "在上的课"):
        assert hint in portrait_service._DIRECTION_PROBE_STAGE, hint
    assert portrait_service._DIRECTION_PROBE_STAGE.count("？") + \
        portrait_service._DIRECTION_PROBE_STAGE.count("?") == 0, "指令里不该出现问号（会被当成题面）"


def test_a_usable_direction_never_shifts_the_stages():
    """方向正常时阶段一步都不偏移（回归：这条路径上什么都不能变）。"""
    dialogue = [{"question": "你想学什么？", "answer": "机械制图"}]
    for step in range(5):
        assert portrait_service._stage_instruction_for(step, dialogue) \
            == portrait_service._INTERVIEW_STAGES[step]


def test_the_probe_pushes_the_later_stages_back_by_one():
    """追问占掉第 2 问，后面的阶段要依次顺延 —— 尤其是「用途」不能整段消失。

    不顺延的话：第 3 问直接去问起点，整场访谈**一次都没问过学习目标**，而诊断要求
    目标非空、前端还按问次去读它（第 3 问 = 目标）。这条钉的就是那个"跳过用途"。
    """
    dialogue = [
        {"question": "你想学什么？", "answer": "还没想好"},
        {"question": "最近在做什么？", "answer": "机械制图"},
    ]
    assert portrait_service._stage_instruction_for(2, dialogue) == portrait_service._INTERVIEW_STAGES[1]
    assert portrait_service._stage_instruction_for(3, dialogue) == portrait_service._INTERVIEW_STAGES[2]
    # 一共 5 问：顺延之后最后一段"练习条件"被挤出访谈，这是已知且可接受的代价。
    assert portrait_service._stage_instruction_for(4, dialogue) == portrait_service._INTERVIEW_STAGES[3]


# ── 方向只从前两问里取，不能和"用途"混起来 ────────────────────────────────

def test_the_direction_is_read_from_the_first_two_questions_only():
    """第 1 问答「机械制图」、第 2 问答「用来就业」：方向只能是前者。

    第 3 问起问的是起点、缺口和练习条件，那些回答不是方向 —— 把其中一句当方向用，
    正是"用途变成了学习方向"那类事故的来源。
    """
    dialogue = [
        {"question": "你想学什么？", "answer": "机械制图"},
        {"question": "用来做什么？", "answer": "用来就业"},
        {"question": "以前做过吗？", "answer": "照着画过零件图"},
    ]
    assert portrait_service._usable_direction(dialogue) == "机械制图"
    # 第 3 问那句再像方向也不能被当成方向
    assert portrait_service._usable_direction([
        {"question": "你想学什么？", "answer": "不知道"},
        {"question": "换个角度问：在做什么项目？", "answer": "还没想好"},
        {"question": "以前做过吗？", "answer": "用来就业"},
    ]) == ""


def test_the_probe_answer_can_become_the_direction():
    """第 1 问答不出、第 2 问追问答出来了：方向取第 2 问那句（这是追问存在的意义）。"""
    dialogue = [
        {"question": "你想学什么？", "answer": "不知道"},
        {"question": "换个角度问：最近在做什么项目？", "answer": "机械制图"},
    ]
    assert portrait_service._usable_direction(dialogue) == "机械制图"


def test_the_slot_limit_matches_the_frontend():
    """后端只认前两问、前端 resolveInterviewSlots 用同一个数字，两边漂移就会一边取到
    「机械制图」、另一边取到「用来就业」。"""
    source = VUE_VIEW.read_text(encoding="utf-8")
    assert f"const DIRECTION_SLOTS = {portrait_service._DIRECTION_SLOTS}" in source


def test_the_first_question_is_the_same_sentence_in_both_languages():
    """第 1 问的题面在前后端各有一份：后端 `_DIRECTION_QUESTION`（直出并当分片推过去）、
    访谈页本地兜底题（请求整个没打通时才显示）。

    两份必须一字不差 —— 否则"学生看到的第一个问题是什么"会取决于网络好不好。后端那份改了
    而前端没跟上时，这里会挂。
    """
    source = VUE_VIEW.read_text(encoding="utf-8")
    assert f"'{portrait_service._DIRECTION_QUESTION}'" in source, (
        "第 1 问的题面在前后端分叉了：后端已经写死，访谈页那份本地兜底题要跟着改"
    )


# ── 落库：不可用的方向一个都不写 ──────────────────────────────────────────

class _AsyncValue:
    """Tortoise 的外键可以 await，例如 ``await user.picture``。"""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _get():
            return self._value

        return _get().__await__()


class FakeQuery:
    def __init__(self, first_value=None):
        self.first_value = first_value

    async def first(self):
        return self.first_value


class FakePicture:
    def __init__(self, traits=None):
        self.traits = traits
        self.cognition = ""
        self.learning_goal = None
        self.personality_tags = ""
        self.profile_summary = ""
        self.saved = 0

    async def save(self):
        self.saved += 1


def _install_picture(monkeypatch, module, picture):
    user = SimpleNamespace(picture=_AsyncValue(picture))
    monkeypatch.setattr(module.User, "filter", lambda **_filters: FakeQuery(first_value=user))


@pytest.mark.asyncio
async def test_an_unusable_direction_is_not_written_into_the_portrait(monkeypatch):
    """「不知道」不能被写成学习方向 —— 这是整条事故链的起点。"""
    picture = FakePicture()
    _install_picture(monkeypatch, diagnosis_service, picture)

    await diagnosis_service._save_onboarding_context(9, "在校大学生", "不知道", "用来就业")

    onboarding = json.loads(picture.traits)["onboarding"]
    assert "direction" not in onboarding, "空回答被当成方向写进了画像"
    # 身份和目标照写：它们本身是有内容的（"用途"不是"方向"，但它是真的用途）
    assert onboarding["identity"] == "在校大学生"
    assert onboarding["goal"] == "用来就业"


@pytest.mark.asyncio
async def test_an_unusable_direction_does_not_overwrite_the_stored_one(monkeypatch):
    """画像里已经有一个真方向时，一句「不知道」不能把它抹掉。"""
    picture = FakePicture(traits=json.dumps({"onboarding": {"direction": "机械制图"}}, ensure_ascii=False))
    _install_picture(monkeypatch, diagnosis_service, picture)

    await diagnosis_service._save_onboarding_context(9, "在校大学生", "不知道", "用来就业")

    assert json.loads(picture.traits)["onboarding"]["direction"] == "机械制图"


@pytest.mark.asyncio
async def test_a_real_direction_is_still_written(monkeypatch):
    """修的是"空回答不能当方向"，不是"干脆不写方向"。"""
    picture = FakePicture()
    _install_picture(monkeypatch, diagnosis_service, picture)

    await diagnosis_service._save_onboarding_context(9, "在校大学生", "机械制图", "做出一个零件图")

    onboarding = json.loads(picture.traits)["onboarding"]
    assert onboarding["direction"] == "机械制图"
    assert onboarding["goal"] == "做出一个零件图"


@pytest.mark.asyncio
async def test_the_diagnosis_does_not_feed_an_unusable_direction_to_the_model(monkeypatch):
    """诊断拿不到真方向时按"未填写"处理：让模型按身份和目标问，而不是按"不知道该学什么"。"""
    captured = {}

    async def fake_init_db():
        return None

    async def fake_save(*_args, **_kwargs):
        captured["saved"] = True

    async def fake_event(*_args, **_kwargs):
        return {}

    async def fake_generate(user_id, identity, direction, goal, history, index, max_steps, on_delta=None):
        captured["direction"] = direction
        return {"content": "题", "reference_answer": "答案"}

    async def fake_create(_user_id, _session_id, _payload):
        return SimpleNamespace(
            id=1, question_type="short_answer", content="题", options=None,
            difficulty="medium", knowledge_tags=None,
        )

    monkeypatch.setattr(diagnosis_service, "init_db", fake_init_db)
    monkeypatch.setattr(diagnosis_service, "_save_onboarding_context", fake_save)
    monkeypatch.setattr(diagnosis_service, "record_learning_event", fake_event)
    monkeypatch.setattr(diagnosis_service, "_generate_question", fake_generate)
    monkeypatch.setattr(diagnosis_service, "_create_question", fake_create)

    await diagnosis_service.start(9, "在校大学生", "不知道", "用来就业")

    assert captured["direction"] == "", "「不知道」被当成学习方向发给了出题模型"


@pytest.mark.asyncio
async def test_the_extraction_keeps_its_own_direction_when_the_request_is_a_non_answer(monkeypatch):
    """收尾那次画像提取：请求里的「不知道」不能压掉模型从对话里抽出来的方向。

    `init_from_dialogue` 里 `selected_direction or learning_direction` 是"请求值优先"，
    请求值是垃圾时这条优先权要收回。
    """
    from backend.src.ai_core import llm_config

    payload = json.dumps({
        "learning_direction": "机械制图",
        "cognition": "视觉型",
        "personality_tags": ["动手能力强"],
        "profile_summary": "想学机械制图的学生。",
    }, ensure_ascii=False)

    class _FakeLlm:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=payload)

    picture = FakePicture()
    _install_picture(monkeypatch, portrait_service, picture)
    monkeypatch.setattr(llm_config, "llm", _FakeLlm())

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        9,
        [{"question": "你想学什么？", "answer": "不知道"}],
        onboarding_context={"identity": "在校大学生", "direction": "不知道", "goal": "用来就业"},
    )

    onboarding = json.loads(picture.traits)["onboarding"]
    assert onboarding["direction"] == "机械制图", "请求里的空回答压掉了模型抽出来的方向"


@pytest.mark.asyncio
async def test_the_extraction_drops_a_non_answer_from_the_model_too(monkeypatch):
    """模型自己也可能把"没问出方向"原样填回来，落库前统一再过一道。"""
    from backend.src.ai_core import llm_config

    class _FakeLlm:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps(
                {"learning_direction": "不知道", "profile_summary": "。"}, ensure_ascii=False))

    picture = FakePicture()
    _install_picture(monkeypatch, portrait_service, picture)
    monkeypatch.setattr(llm_config, "llm", _FakeLlm())

    await portrait_service.PortraitChatHistory_Service.init_from_dialogue(
        9, [{"question": "你想学什么？", "answer": "不知道"}],
    )

    onboarding = json.loads(picture.traits).get("onboarding") or {}
    assert "direction" not in onboarding


# ── 前端：写盘那条路也要过判定 ────────────────────────────────────────────

def test_the_interview_page_only_persists_a_usable_direction():
    """`persistInterviewDirection` 以前是 `if (answers[0])` —— 无条件覆盖。"""
    source = VUE_VIEW.read_text(encoding="utf-8")
    body = source.split("const persistInterviewDirection = () => {", 1)[1].split("\n}", 1)[0]
    assert "resolveInterviewSlots(" in body, "落盘没有走「在前两问里取第一个可用回答」那条路"
    assert "answers[0]" not in body, "还在按下标取第 1 个回答（答「不知道」时会照单全收）"


def test_the_interview_page_asks_for_the_missing_slots():
    """五问答完还是缺方向/目标时，要有补填入口，并把用户挡在诊断页之前。"""
    source = VUE_VIEW.read_text(encoding="utf-8")
    assert "needsSlots" in source, "没有补填入口"
    assert "effectiveSlots" in source, "没判断「最终生效的那两个值」是否可用"
    assert "v-if=\"needsSlots\"" in source, "补填表单没有渲染条件"


def test_the_interview_page_never_borrows_the_goal_as_the_direction():
    """前端的取值规则要和后端一致：方向只看前两问，目标只看「用途那一问」。"""
    source = VUE_VIEW.read_text(encoding="utf-8")
    body = source.split("const resolveInterviewSlots = answers => {", 1)[1].split("\n}", 1)[0]
    # 目标由问次决定（第 1 问给了方向 → 用途在第 2 问；否则顺延到第 3 问），
    # 而不是"扫一遍找第一个可用的" —— 后者会把后面几问的回答借来当目标。
    assert "const goalAt = directionAt === 0 ? 1 : 2" in body
    assert "findIndex((value, index) => index > directionAt" not in body


def test_the_summary_page_does_not_borrow_cognition_as_the_direction():
    """总结页曾经回落 `onboarding.direction || cognition || answerAt(0)`。

    cognition 是认知风格（"视觉型"描述的是怎么学，不是学什么），answerAt(0) 是访谈的
    原始回答 —— 正是「不知道」待的地方。拿它们顶上就是又造了一个假方向。
    """
    source = (VUE_VIEW.parents[2] / "pages" / "onboarding" / "PortraitSummaryPage.vue").read_text(encoding="utf-8")
    body = source.split("const directionValue = computed(", 1)[1].split("\n", 1)[0]
    assert "cognition" not in body, "认知风格被当成了学习方向"
    assert "answerAt" not in body, "访谈原始回答被当成了学习方向"
    # 展示可以写"未填写"，但落盘/发请求那条路用的是 directionValue/goalValue
    assert "const direction = computed(() => directionValue.value || '未填写')" in source
    assert "generatePathsFromDirection(directionValue.value, goalValue.value)" in source
