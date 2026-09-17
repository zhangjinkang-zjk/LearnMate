# -*- coding: utf-8 -*-
"""诊断的正文要边写边推给学生，而不是攒够一整段再给。

起因：判分和出题各自要等模型二十到六十秒，而反馈是**一次性**返回的。学生答完之后
屏幕上什么都没有，只有一句"正在生成回复…"——服务端其实已经写好了，只是还没写完。等到
写完了，那句话才整段出现。

现在的约定：模型这两处的输出分两段 —— 先一行直接展示给学生的正文，独占一行的 `---`，
再是程序用的 JSON。正文一积出来就推给页面。

这里钉的是"推出去的那部分到底是什么"：**不能多推**（半截 `---`、JSON 尾巴漏到学生眼前
比没有流式更糟），**不能少推**（少推等于回到等一整段）。
"""

import asyncio
import json
import logging
from pathlib import Path

import pytest

from backend.src.service.diagnosis import service as diagnosis
from backend.src.utils.prompt_loader import load_prompt

PROMPTS = Path(__file__).resolve().parents[1] / "src" / "ai_core" / "prompts"

QUESTION_RAW = (
    "你以前用三视图画过零件吗？说说最近一次动手画的是什么。\n"
    "---\n"
    '{"question_type":"short_answer","reference_answer":"能说出三视图是三个方向的投影。",'
    '"evaluation_points":["三视图的定义"],"analysis":"先看概念是否清楚。","difficulty":"easy",'
    '"knowledge_tags":["三视图"]}'
)
EVALUATE_RAW = (
    "你抓住了要看返回值这一点，但还没说到失败之后怎么处理，这正是下一步要练的。\n"
    "---\n"
    '{"is_correct":false}'
)


async def _chunks(text: str, size: int = 7):
    """按块吐出，模拟模型的流。"""
    for start in range(0, len(text), size):
        yield text[start:start + size]
        await asyncio.sleep(0)


def _collect():
    seen: list[str] = []
    return seen, (lambda text: seen.append(text))


# ── 切分：给学生看的正文 vs 兜里的 JSON ────────────────────

def test_the_visible_part_stops_before_the_delimiter():
    visible, tail = diagnosis._split_visible(QUESTION_RAW)

    assert visible.startswith("你以前用三视图画过零件吗")
    assert "---" not in visible
    assert "reference_answer" not in visible
    assert "reference_answer" in tail


def test_output_without_the_delimiter_is_not_treated_as_visible():
    """模型没按格式写时整段都是 JSON —— 那种情况下"正文"必须是空的。

    把它当成正文，等于把 `{"question": ...}` 原样画到学生眼前。
    """
    visible, tail = diagnosis._split_visible('{"question":"旧格式"}')

    assert visible == ""
    assert tail == '{"question":"旧格式"}'


def test_the_tail_payload_parses_either_shape():
    assert diagnosis._tail_payload(QUESTION_RAW)["difficulty"] == "easy"
    # 老格式（整段 JSON）也要能解出来
    assert diagnosis._tail_payload('{"is_correct":true}')["is_correct"] is True


def test_an_unparseable_tail_is_empty_not_an_exception():
    """解不出来要给空字典，不能抛。

    模型写到一半被打断（正文已经显示给学生了）、或者干脆忘了写那段 JSON 时，
    ``parse_llm_json`` 是抛 JSONDecodeError 的。让它抛出去，外面那层 except 会把
    **整段**降级成兜底文案 —— 学生眼前那句已经读了一半的话会被换掉，
    而他看到的原因只是"程序要的那个字段没拿到"。
    """
    assert diagnosis._tail_payload("你抓住了要看返回值这一点") == {}
    assert diagnosis._tail_payload("") == {}
    assert diagnosis._tail_payload("正文\n---\n{坏掉的 JSON") == {}
    # 解出来的不是对象（比如模型回了个数组）也算没有可用字段
    assert diagnosis._tail_payload("正文\n---\n[1, 2]") == {}


def test_a_prose_only_answer_is_not_reported_as_a_parse_failure(caplog):
    """只写正文、不写那段 JSON，是访谈题面的**正常**输出，不该长成一条"解析失败"。

    原来它要经过 parse_llm_json：解析抛错 → json_parser 打一行 WARNING、这里再打一行，
    两行看着都像出了故障。而访谈每一问几乎都是纯散文，于是画像那一段日志里全是这种
    告警 —— 读日志的人会去找一个不存在的问题（"画像是不是坏了"）。
    """
    prose = "你打算把智能体用在什么地方，比如做一个能帮你整理课堂笔记的小助手，还是开发能处理具体任务的应用？"
    with caplog.at_level(logging.WARNING):
        assert diagnosis._tail_payload(prose) == {}
    assert not caplog.records, f"纯散文的正文不该产生告警：{[r.message for r in caplog.records]}"


def test_prose_wrapped_json_still_parses():
    """老格式（正文和 JSON 混着写）必须继续能解出来。

    所以判据是"整段里有没有花括号"，不能收紧成"是不是以花括号开头" —— 那种写法会把
    这一路直接丢掉，症状是程序字段莫名其妙拿不到，而正文看起来一切正常。
    """
    assert diagnosis._tail_payload('这是给你的题目 {"question": "讲讲你的项目"}') == {
        "question": "讲讲你的项目"
    }


# ── 推给页面的那条流 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_the_visible_line_streams_out_before_the_json_is_finished():
    seen, on_delta = _collect()

    state = await diagnosis._consume_stream(_chunks(EVALUATE_RAW), on_delta, timeout=5)

    assert state["done"] is True
    assert state["visible"].startswith("你抓住了要看返回值")
    # 拼起来就是那句话本身
    assert "".join(seen) == state["visible"]
    # 而且是**分多次**推的 —— 一次推完等于没流式
    assert len(seen) > 1, "正文是一次性推出去的，学生还是会干等"


@pytest.mark.asyncio
async def test_the_json_tail_never_reaches_the_student():
    seen, on_delta = _collect()

    await diagnosis._consume_stream(_chunks(QUESTION_RAW, size=3), on_delta, timeout=5)

    pushed = "".join(seen)
    assert "reference_answer" not in pushed, "JSON 尾巴漏到学生眼前了"
    assert "---" not in pushed, "分隔行本身不该显示出来"
    assert "knowledge_tags" not in pushed


@pytest.mark.asyncio
async def test_a_partial_delimiter_does_not_leak_either():
    """块边界正好切在 `-` 和 `--` 之间时，不能因为"还没到分隔行"就先把这两个字符推出去。"""
    seen, on_delta = _collect()
    raw = "这句话是给学生看的。\n--" + "-\n{\"is_correct\":true}"

    await diagnosis._consume_stream(_chunks(raw, size=1), on_delta, timeout=5)

    assert "".join(seen) == "这句话是给学生看的。"


@pytest.mark.asyncio
async def test_a_timeout_keeps_what_the_student_already_saw():
    """正文已经到学生眼前了，超时不该把它撤回 —— 拿到的部分就是这一轮的答复。"""
    seen, on_delta = _collect()

    async def slow():
        yield "你已经说到了要看返回值，"
        await asyncio.sleep(10)  # 卡住不再出字

    state = await diagnosis._consume_stream(slow(), on_delta, timeout=0.05)

    assert state["done"] is False, "这条流不该被当成正常收完"
    assert "".join(seen).startswith("你已经说到了要看返回值")
    assert state["visible"], "超时把已经展示出去的正文丢了"


@pytest.mark.asyncio
async def test_a_broken_stream_is_not_fatal():
    async def boom():
        yield "前半句"
        raise RuntimeError("upstream 503")

    state = await diagnosis._consume_stream(boom(), lambda _t: None, timeout=5)

    assert state["raw"].startswith("前半句")
    assert state["done"] is False


@pytest.mark.asyncio
async def test_the_final_text_is_corrected_against_the_whole_output():
    """流式期间为了不泄露会扣住结尾，收尾时要按完整输出把那段补回来。

    正文里一旦出现 `{`，流式守卫会停在它前面（那是 JSON 的开头）—— 但这句正文本身
    得是完整的，不能因为守卫就永久少半句。
    """
    seen, on_delta = _collect()
    raw = "你说的 {x} 这个概念，能再举一个例子吗？\n---\n{\"is_correct\":true}"

    state = await diagnosis._consume_stream(_chunks(raw, size=4), on_delta, timeout=5)

    assert state["visible"] == "你说的 {x} 这个概念，能再举一个例子吗？", "收尾没按完整输出校正，正文缺了一段"


# ── 真跑这两个模型调用：字有没有推出去 ────────────────────

def _fake_llm(raw: str, seen: list):
    """替身模型：astream 按块吐，同时记下它被怎么调的。"""

    class _Fake:
        def astream(self, prompt, **_kwargs):
            seen.append(prompt)

            async def _gen():
                for start in range(0, len(raw), 5):
                    yield raw[start:start + 5]

            return _gen()

    return _Fake()


@pytest.mark.asyncio
async def test_evaluating_an_answer_streams_the_reply(monkeypatch):
    """判分那段要真的推给页面 —— 它以前是"等整段生成完一次性返回"的那一段。"""
    from types import SimpleNamespace

    from backend.src.ai_core import llm_config

    prompts: list[str] = []
    monkeypatch.setattr(llm_config, "llm", _fake_llm(EVALUATE_RAW, prompts))
    question = SimpleNamespace(
        id=1, content="正投影是什么？", answer="投影线垂直于投影面。",
        analysis=json.dumps({"feedback_basis": "", "evaluation_points": ["定义"]}),
    )
    seen, on_delta = _collect()

    result = await diagnosis._evaluate_answer(1, question, "就是把零件从正面画出来。", on_delta)

    assert result["is_correct"] is False
    assert result["feedback"].startswith("你抓住了要看返回值"), "反馈不是那段正文"
    assert "".join(seen) == result["feedback"], "推给页面的和最终认定的话对不上"
    assert len(seen) > 1, "判分那段没有逐块推出去"


@pytest.mark.asyncio
async def test_generating_the_next_question_streams_it(monkeypatch):
    from backend.src.ai_core import llm_config

    prompts: list[str] = []
    monkeypatch.setattr(llm_config, "llm", _fake_llm(QUESTION_RAW, prompts))
    seen, on_delta = _collect()

    payload = await diagnosis._generate_question(1, "学生", "机械制图", "看懂零件图", [], 1, 5, on_delta)

    assert payload["content"].startswith("你以前用三视图画过零件吗")
    assert payload["difficulty"] == "easy", "JSON 尾巴没解析出来"
    assert "".join(seen) == payload["content"]
    assert len(seen) > 1, "题目没有逐块推出去"


@pytest.mark.asyncio
async def test_a_model_that_ignores_the_format_still_works(monkeypatch):
    """模型不按两段式写（老格式整段 JSON）时：不流式，但结果照样得对。"""
    from backend.src.ai_core import llm_config

    old_format = json.dumps({
        "question_type": "short_answer",
        "content": "旧格式的题面",
        "reference_answer": "参考答案",
        "evaluation_points": ["要点"],
        "difficulty": "medium",
        "knowledge_tags": ["标签"],
    }, ensure_ascii=False)
    monkeypatch.setattr(llm_config, "llm", _fake_llm(old_format, []))
    seen, on_delta = _collect()

    payload = await diagnosis._generate_question(1, "学生", "机械制图", "看懂零件图", [], 1, 5, on_delta)

    assert payload["content"] == "旧格式的题面", "老格式的 content 没兜住"
    assert "".join(seen) == "", "把整段 JSON 当正文推出去了"

def test_each_stream_is_bound_to_its_own_bubble():
    seen = []
    collect = lambda text, channel: seen.append((channel, text))  # noqa: E731
    diagnosis._channel_writer(collect, "reply")("判分那句")
    diagnosis._channel_writer(collect, "question")("下一题那句")

    # 两个通道必须各是各的：都塞进 reply 的话，题目会追加到回复气泡里
    assert seen == [("reply", "判分那句"), ("question", "下一题那句")]


def test_the_two_service_call_sites_bind_their_own_channel():
    """两处调用点各自绑通道，别指望调用方去分辨。

    这两条线是分开接的（判分在 _submit_open_answer、出题在 answer/start），所以这里
    按出现次数数：少一处就说明有一段正文没接上流式。
    """
    import inspect

    submit = inspect.getsource(diagnosis._submit_open_answer)
    assert '_channel_writer(on_delta, "reply")' in submit, "判分那段没接上流式"

    for name in ("start", "answer"):
        source = inspect.getsource(getattr(diagnosis, name))
        assert '_channel_writer(on_delta, "question")' in source, f"{name} 里的出题没接上流式"


def test_no_writer_means_no_callback_at_all():
    """非流式接口（/answer）不传 writer，不能在这里炸。"""
    assert diagnosis._channel_writer(None, "reply") is None


# ── 提示词：模型得知道要这么写 ────────────────────────────

@pytest.mark.parametrize("name", ["diagnosis", "diagnosis_evaluate"])
def test_the_prompt_asks_for_the_two_part_output(name):
    """模型不写 `---`，流式就退化成"等一整段"（这不会报错，只会悄悄变慢）。"""
    prompt = load_prompt(name)

    assert "---" in prompt, f"{name} 的提示词没要求写分隔行"
    assert "边写边显示" in prompt, "没告诉模型第一段会被实时显示，它会写「让我看看」这种开场白"


def test_the_prompt_and_the_code_agree_on_the_delimiter():
    """两边靠字面量对齐（提示词里的 `---` 和代码里的 _VISIBLE_MARKER），改一边就会静默失效。"""
    assert diagnosis._VISIBLE_MARKER == "\n---"
    for name in ("diagnosis", "diagnosis_evaluate"):
        prompt = (PROMPTS / f"{name}.yaml").read_text(encoding="utf-8")
        assert "一行 `---`" in prompt, f"{name} 让模型写的分隔行和代码认的对不上"
