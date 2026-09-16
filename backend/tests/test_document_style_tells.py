"""文风观测是「只统计、不拦截」，所以这里要同时钉住两件事：

1. 该认出来的套话认得出来（否则观测值没有意义）；
2. 不该认的别乱认——正常教学正文、代码块、以及「把套话当讲解对象引用」的段落
   都必须判为无命中（否则噪音会把观测值淹掉）；
3. 它绝不能混进 validate_document_section 的打回条件（那是文档不收敛的坑）。
"""

from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import pytest

from backend.src.service.resource.document_quality import (
    detect_ai_style_tells,
    format_ai_style_tells,
    validate_document_section,
)


def _tells(text: str) -> dict[str, int]:
    return detect_ai_style_tells(text)


# ── 该认出来的 ──────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected_label",
    [
        ("在当今信息化时代，掌握这项技术显得尤为重要。", "套话开头"),
        ("众所周知，向量的点积反映了两个方向的接近程度。", "套话开头"),
        ("随着检索技术的不断发展，切片策略也在演进。", "套话开头"),
        ("综上所述，切分粒度的选择取决于查询的分布。", "空洞总结"),
        ("由此可见，重叠窗口的宽度需要与块大小匹配。", "空洞总结"),
        ("那么，什么是余弦相似度？它衡量的是方向的一致性。", "过渡腔"),
        ("接下来让我们看看具体的实现步骤。", "过渡腔"),
        ("这一步至关重要，写错会导致召回率骤降。", "副词堆砌"),
    ],
)
def test_recognizes_each_style_tell(text, expected_label):
    assert expected_label in _tells(text)


def test_enumeration_skeleton_needs_the_pair():
    """单个「最后」是正常行文，成对的「首先…其次」才是套路。"""
    assert "枚举骨架" not in _tells("最后我们把结果写回数据库，并记录耗时。")
    assert "枚举骨架" not in _tells("首先定义切分边界，这一步决定了后续一切。")
    assert _tells("首先切分边界，其次做窗口重叠，最后验证召回。")["枚举骨架"] >= 1


def test_two_sided_parallelism_needs_both_halves():
    assert "两面并列" not in _tells("一方面要控制块大小，避免混入多个主题。")
    assert _tells("一方面要控制块大小，另一方面要保留足够的上下文。")["两面并列"] >= 1


def test_counts_repeated_hits():
    text = "这一步至关重要。那一步也至关重要。整个流程至关重要。"
    assert _tells(text)["副词堆砌"] == 3


# ── 不该认的 ────────────────────────────────────────────


def test_clean_teaching_prose_has_no_hits():
    prose = (
        "## 切分粒度\n\n"
        "块大小决定了每个片段能承载多少语义。块太大时会混入多个主题，检索时"
        "命中其中一段却召回整块，噪声随之上升。块太小则相反：上下文被切断，"
        "跨边界的提问很难被召回。\n\n"
        "实践中先用句号、分号这些显式边界切，再按固定长度兜底。"
    )
    assert _tells(prose) == {}


def test_code_blocks_are_ignored():
    code = "```python\n# 综上所述这只是注释\nprint('首先其次最后')\n```\n"
    assert _tells(code) == {}


def test_quoted_phrases_are_treated_as_discussion_not_usage():
    """讲「如何避免套话」的段落本身会引用这些词，不能算命中。"""
    text = '写文档时要避开「综上所述」「众所周知」这类模板化表述，直接给结论。'
    assert _tells(text) == {}


def test_phrases_must_sit_at_a_sentence_start():
    """句中的「在当今」往往是在讨论这个词本身，不算套话开头。"""
    assert "套话开头" not in _tells("这段话里的在当今并不是开头，只是被引用。")
    assert "套话开头" in _tells("先说结论。在当今的实践中，这个假设并不成立。")


# ── 只观测不拦截 ────────────────────────────────────────


def test_style_tells_never_block_a_section():
    """套话密集但结构完整的正文，validate_document_section 仍须放行。

    它一旦进入打回条件，每轮重写都会撞同一条规则、烧完重试次数再走兜底 ——
    比不拦更慢且不收敛。
    """
    body = (
        "在当今信息化时代，检索质量至关重要。众所周知，切分粒度决定了召回上限。"
        "综上所述，我们需要谨慎选择块大小与重叠窗口。接下来让我们看看具体做法。"
        "首先按语义边界切分，其次做窗口重叠，最后用同一组问题验证召回效果。"
        "一方面要控制块大小，另一方面要保留足够的上下文。"
        "块太大时会混入多个主题，命中其中一段却召回整块，噪声随之上升；"
        "块太小则相反，上下文被切断，跨边界的提问很难被召回。"
        "实践中先用句号、分号这些显式边界切，再按固定长度兜底，"
        "并用同一组问题分别比较两种切分方案的召回结果，"
        "直到新增的重叠部分不再带来收益为止。"
    )
    text = f"## 切分粒度\n\n{body}"
    assert _tells(text), "这段应当被判为满是套话，否则下面的断言没有意义"
    assert validate_document_section(text, "切分粒度") == []


def test_format_is_stable_and_sorted_by_count():
    assert format_ai_style_tells({}) == "无"
    assert format_ai_style_tells({"空洞总结": 1, "副词堆砌": 3}) == "副词堆砌×3 空洞总结×1"


# ── 接入生成流程 ────────────────────────────────────────

_TITLES = ("语义边界", "窗口重叠", "召回精度")
# 每节 ~250 字：够过单节 180 字下限，但三节合计不到整章 900 字，
# 这样整章校验必然失败、必然触发一轮整章重修 —— 正是要覆盖的场景。
_STYLISH_BODY = (
    "在当今信息化时代，检索质量至关重要。众所周知，切分粒度决定了召回上限。"
    "综上所述，我们需要谨慎选择块大小与重叠窗口。接下来让我们看看具体做法。"
    "首先按语义边界切分，其次做窗口重叠，最后用同一组问题验证召回效果。"
    "一方面要控制块大小，另一方面要保留足够的上下文。"
    "块太大时会混入多个主题，命中其中一段却召回整块，噪声随之上升；"
    "块太小则相反，上下文被切断，跨边界的提问很难被召回。"
    "重叠窗口的宽度通常取块大小的百分之一到二十，用来覆盖句子之间的衔接处。"
)


class _StylishLlm:
    """每节都返回一份满是套话、但结构合法的正文。

    标题从 prompt 里取而不是按调用序号发，否则整章重修那一轮会把标题串位，
    小节因「标题与规划不一致」被判失败、走兜底，就测不到要测的东西了。
    """

    # 路径节点文档走 resource/path_document，小节标记写的是「节」不是「章」。
    _TITLE_RE = re.compile(r"第 \d+/\d+ 节「(.+?)」")

    def __init__(self):
        self.calls = 0

    async def ainvoke(self, prompt, **_kwargs):
        self.calls += 1
        match = self._TITLE_RE.search(str(prompt))
        title = match.group(1) if match else _TITLES[0]
        return SimpleNamespace(content=f"## {title}\n\n{_STYLISH_BODY}")


async def _no_kb(*_args, **_kwargs):
    return "暂无相关知识库资料"


@pytest.mark.asyncio
async def test_style_hits_are_counted_once_per_shipped_section(monkeypatch, caplog):
    """整章重修会把 gen_section 再跑一遍，汇总必须按小节覆盖计数。

    累加的话同一节会被算两遍，汇总出现「命中小节 6/3」这种不可能的比值，
    指标直接失真 —— 而这个指标的用途正是观察实际文风，数字错了就白测。
    """
    from backend.src.ai_core import resource_graph

    monkeypatch.setattr(resource_graph, "llm", _StylishLlm())
    monkeypatch.setattr(resource_graph, "kb_search", _no_kb)

    with caplog.at_level(logging.INFO, logger="backend.src.ai_core.resource_graph"):
        content = await resource_graph.generate_document_parallel(
            "文档切分",
            sections=list(_TITLES),
            section_count=len(_TITLES),
            teaching_context={"current": {"topic": "文档切分", "teaching_spec": {"key_points": []}}},
            user_id=7,
            skip_review=True,
        )

    summary = [line for line in caplog.messages if "[Doc-Style] 文风观测汇总" in line]
    assert len(summary) == 1, "汇总应只出现一次"
    assert "命中小节=3/3" in summary[0], summary[0]
    assert "文风观测汇总" in summary[0]

    # 观测不得改变产物：套话照旧留在正文里。
    assert "综上所述" in content
    assert content.startswith("# 文档切分")
