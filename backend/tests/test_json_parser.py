# -*- coding: utf-8 -*-
"""模型回复里的非法转义不能作废整条回复。

2026-10-02 跑诊断→路径那条链时实测到的：那条路径的审核**一次都没真的跑过**。
日志里三处 JSON 解析失败全是同一个原因 —— 模型写中文范围号时在波浪号前加了个反斜杠
（`难度（1.5\\~2.18）`），而 `\\~` 不是合法 JSON 转义。`_loads_lenient` 的
`strict=False` 只放过裸控制字符，**放过不了非法转义**（那是两种不同的错）。

为什么这不是"小概率坏运气"：`parse_llm_json` 是全仓库 LLM JSON 的唯一出口（29 处调用、
15 个模块）。而两条审核链路（路径审核 `path_graph.reviewer_node`、PPT 审核）都是
`except` 之后"故障放行"：

    except Exception:  →  review_passed=True, review_source="error"

于是失败的后果不是报错，而是**审核静默地不跑**，链路上只留一行 WARNING —— 拿这种输出
去评估生成质量，等于在评一个没经过审核的东西。所以这两条链路必须钉在这里。
"""

import json

import pytest

from backend.src.utils.json_parser import parse_llm_json, _repair_invalid_escapes


# ── 真实故障样本 ─────────────────────────────────────────────────────────

def test_a_chinese_range_tilde_no_longer_kills_the_whole_reply():
    """日志里那条把路径审核打挂的回复（缩到最小）。其余字段必须一个不少。"""
    # 注意源码里写 `\\~`，喂给解析器的就是模型实际发的那个单反斜杠
    raw = (
        '{"passed": true, "score": 68, "feedback": "难度（1.5\\~2.18）偏低",'
        ' "issues": ["节点16-21的order_index排在15之后"]}'
    )

    result = parse_llm_json(raw)

    assert result["passed"] is True
    assert result["score"] == 68
    assert result["issues"] == ["节点16-21的order_index排在15之后"]
    # 补的是**编码那一层**：那个反斜杠留在正文里，而不是被删掉改内容
    assert result["feedback"] == "难度（1.5\\~2.18）偏低"


def test_a_fenced_reply_with_an_invalid_escape_parses():
    """围栏那条路也要走到（模型很爱加 ```json）。"""
    raw = '```json\n{"ok": true, "note": "涨幅 3\\%~5\\%"}\n```'

    assert parse_llm_json(raw)["ok"] is True


# ── 补的时候别把好的那半也补坏 ───────────────────────────────────────────

def test_valid_escapes_are_left_alone():
    """`\\"` `\\\\` `\\n` `\\uXXXX` 原样保留 —— 补坏它们就是把内容改错。"""
    raw = '{"quote": "他说\\"算了\\"", "path": "C:\\\\tmp", "line": "第一行\\n第二行", "cn": "\\u4e2d"}'

    result = parse_llm_json(raw)

    assert result["quote"] == '他说"算了"'
    assert result["path"] == "C:\\tmp"
    assert result["line"] == "第一行\n第二行"
    assert result["cn"] == "中"


def test_a_valid_escape_is_not_doubled_when_the_repair_runs():
    """**同一个回复里既有合法转义又有非法转义** —— 这是最容易补坏的一格。

    只因为这个文档里有 `\\~`、补全过程才被触发；此时 `C:\\\\tmp` 那个 `\\\\` 必须原封不动，
    整份替换式的补法（`content.replace("\\\\", "\\\\\\\\")`）会在这里把它变成 `\\\\tmp`。
    """
    raw = '{"path": "C:\\\\tmp", "note": "1.5\\~2.18"}'

    result = parse_llm_json(raw)

    assert result["path"] == "C:\\tmp", "合法转义被补了第二遍"
    assert result["note"] == "1.5\\~2.18"


def test_a_truncated_unicode_escape_is_treated_as_text():
    """`\\u` 后面不足四位十六进制就不是 Unicode 转义，按字面量走，别当它合法。"""
    assert parse_llm_json('{"s": "\\u12"}')["s"] == "\\u12"


# ── 它只修编码，不编结构 ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1',                 # 少一个大括号
        '{"a": 1, \\ }',           # JSON 里、字符串外多一个反斜杠（那是语法错，不是转义错）
        '{"a": "b" "c": "d"}',     # 键之间少了逗号
    ],
)
def test_structurally_broken_json_still_raises(raw):
    """结构坏掉的必须继续抛错。

    这一层只补转义，**不替模型把括号补上、把逗号猜出来** —— 那会把"模型输出坏了"变成
    "我们替它编了一份"，审核和诊断都拿不到信号。
    """
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json(raw)


def test_json_wrapped_in_prose_is_still_accepted():
    """顺带钉住既有行为：正文里夹一段 JSON 是允许的（抠出那段解析）。

    上面那条参数化的第二个用例之所以写"JSON 里、字符串外"，就是因为**夹在正文里的**
    反斜杠会被这一层抠掉、不影响解析 —— 两件事别混。
    """
    assert parse_llm_json('这是结果：{"a": 1} 就这样 \\') == {"a": 1}


def test_the_error_raised_is_the_one_from_the_original_text():
    """失败时抛最初那个错：报错位置要对应模型原文，补过的那份对不上。"""
    raw = '{"a": 1 \\'

    # 拿不补的那份比一遍，位置必须一致
    try:
        json.loads(raw)
    except json.JSONDecodeError as expected:
        with pytest.raises(json.JSONDecodeError) as raised:
            parse_llm_json(raw)
        assert raised.value.pos == expected.pos


# ── 补的方式本身 ─────────────────────────────────────────────────────────

def test_the_repair_only_touches_backslashes_inside_strings():
    """字符串**外面**的反斜杠一个都不动 —— 那不是转义问题，是语法问题。"""
    assert _repair_invalid_escapes('{"a": "x\\~y"} \\') == '{"a": "x\\\\~y"} \\'
