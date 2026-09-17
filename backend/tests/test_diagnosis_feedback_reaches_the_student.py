# -*- coding: utf-8 -*-
"""诊断那句反馈必须真的到学生眼前。

这条链以前是"前端自己去嵌套字典里掏"：服务端把反馈放在 `feedback.feedback` / `feedback.analysis`
两个键上，页面读不到任何一个就显示"正在生成回复…"。于是三种完全不同的情况长得一模一样 ——
后端没给、键名对不上、页面读错字段 —— 学生看到的都是一句永远不会兑现的"正在生成"。

现在服务端在响应体上平铺一个 `reply`，并保证它非空（`_reply_text` 是唯一出口）；页面优先读它。
这里钉两头：服务端不可能给空串，页面不可能再显示那句空话。
"""

from pathlib import Path

import pytest

from backend.src.service.diagnosis import service as diagnosis_service
from backend.src.service.diagnosis.service import _reply_text, answer

DIAGNOSIS_PAGE = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "pages" / "onboarding" / "DiagnosisPage.vue"
)


# ── 服务端：这句话不可能是空的 ────────────────────────────

def test_a_real_evaluation_reaches_the_reply():
    assert _reply_text({"is_correct": False, "feedback": "你的回答里已经有部分线索。"}) == "你的回答里已经有部分线索。"


def test_the_reply_falls_back_to_the_analysis_key():
    """老响应只有 analysis，没有 feedback —— 那也是学生该看到的话。"""
    assert _reply_text({"is_correct": False, "analysis": "先确认你是否理解概念。"}) == "先确认你是否理解概念。"


def test_a_plain_string_is_used_as_is():
    assert _reply_text("已记录。") == "已记录。"


@pytest.mark.parametrize("empty", [
    None,
    {},
    {"is_correct": False},
    {"feedback": ""},
    {"feedback": "   "},
    {"analysis": ""},
    {"feedback": None, "analysis": None},
    [],
    "",
    "   ",
    0,
])
def test_a_missing_reply_never_becomes_an_empty_string(empty):
    """空串是这个函数唯一不可接受的返回值 —— 它到了页面上就是"少一句话"，没人知道。"""
    text = _reply_text(empty)

    assert text.strip(), f"{empty!r} 让它返回了空"
    assert "已记录你的回答" in text


def test_both_return_paths_carry_the_reply():
    """答案分支和收尾分支都要带 —— 只加一个的话，另一个分支又回到"少一句话"。

    这里数的是出现次数而不是"有没有"：写漏一处，次数就不对。
    """
    import inspect

    source = inspect.getsource(answer)
    assert source.count('"reply": _reply_text(feedback)') == 2, (
        "answer() 有两个 return（答完 / 未答完），两个都要带上 reply"
    )


def test_the_reply_helper_is_the_only_place_that_builds_it():
    """响应体里的 reply 只能由 _reply_text 产出，不能就地写死一句话。"""
    import inspect

    source = inspect.getsource(answer)
    assert '"reply": "' not in source, "又一个地方自己拼了 reply，兜底逻辑就绕过去了"


# ── 前端：不可能再显示那句空话 ────────────────────────────

def _source() -> str:
    if not DIAGNOSIS_PAGE.exists():
        pytest.skip("前端不在这个工作区里，跨语言检查无从谈起")
    return DIAGNOSIS_PAGE.read_text(encoding="utf-8")


def test_the_page_reads_the_flat_reply_first():
    """服务端平铺的 reply 是权威版本，页面必须优先用它。"""
    source = _source()

    assert "result.reply" in source, "页面没读服务端平铺的 reply，又回去掏嵌套字典了"

    line = next((l.strip() for l in source.splitlines() if "result.reply" in l), "")
    assert line.startswith("const reply = "), f"这一行的写法变了：{line}"
    assert "result.reply ||" in line, f"reply 不是首选来源：{line}"
    # 定稿要落在同一个气泡上（流式那段已经在里面了），不能再推一个新气泡
    assert "setChannelText('reply'" in source, "服务端那句没有覆盖到流式气泡上"


def test_the_empty_promise_is_gone():
    """'正在生成回复…' 是那句永远不兑现的话：服务端其实已经写好了反馈，页面却在等一个
    不会到来的东西。它一旦重新出现，说明又有人的字段没对上。

    只看代码行：注释里提它是在说明"以前错在哪"，那不叫又回来了。
    """
    code = "\n".join(
        line for line in _source().splitlines()
        if not line.strip().startswith(("//", "<!--", "*"))
    )
    assert "正在生成回复" not in code, "那句「等一个不会来的回复」又回到代码里了"
