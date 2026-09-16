"""Regression coverage for context-aware document placeholder checks."""

from __future__ import annotations

import pytest

from backend.src.service.resource.document_quality import (
    evaluate_key_point_coverage,
    validate_document_chapter,
    validate_document_section,
)


_SECTION_BODY = (
    "文档质量门应区分未完成占位和真实教学内容。课程会解释术语的定义、使用边界、"
    "判断依据和工程影响，并通过具体示例帮助学习者理解为什么需要保留上下文。"
    "学习者还需要比较不同写法的优缺点，说明错误处理策略，并给出可以复核的结论。"
)


def _make_section(extra: str) -> str:
    return f"## 文档质量检查\n\n{_SECTION_BODY * 3}\n\n{extra}"


def _make_chapter(extra: str) -> str:
    sections = [
        f"## {title}\n\n{_SECTION_BODY * 3}"
        for title in ("识别占位", "理解语义", "工程实践")
    ]
    return "# 文档质量门\n\n" + "\n\n".join(sections) + f"\n\n{extra}"


@pytest.mark.parametrize(
    "placeholder",
    [
        "TODO",
        "- TBD",
        "**待补充**",
        "> 此处补充示例",
        "TODO：补充一份边界案例",
        "本节内容待补充。",
        "推导过程略。",
    ],
)
def test_quality_gate_rejects_standalone_or_short_placeholder_paragraphs(placeholder):
    section_errors = validate_document_section(
        _make_section(placeholder),
        "文档质量检查",
    )
    chapter_errors = validate_document_chapter(_make_chapter(placeholder))

    assert "包含省略或待补充占位语" in section_errors
    assert "文档包含省略或待补充占位语" in chapter_errors


def test_quality_gate_allows_placeholder_terms_as_teaching_content():
    teaching_content = """### TODO：技术债的来源与治理方法

TODO 是一种显式记录后续工作的工程标记，TBD 表示方案仍待确定。
“待补充”可以作为内容状态，但发布前必须由负责人复核，而不是让它替代关键论证。
待补充数据的治理方法包括责任人、截止时间和验收标准。"""

    assert validate_document_section(
        _make_section(teaching_content),
        "文档质量检查",
    ) == []
    assert validate_document_chapter(_make_chapter(teaching_content)) == []


def test_quality_gate_ignores_placeholder_terms_inside_code_blocks():
    code_examples = """```python
# TODO: 补充真实实现
raise NotImplementedError("TBD")
```

    # TODO: 缩进代码块中的教学示例
    return "待补充"
"""

    assert validate_document_section(
        _make_section(code_examples),
        "文档质量检查",
    ) == []
    assert validate_document_chapter(_make_chapter(code_examples)) == []


_COVERAGE_PARAGRAPH = (
    "文档切分决定了检索时每个片段能承载多少语义信息，块大小过大时会混入多个主题，"
    "块大小过小时又会丢掉上下文。实践中通常先按语义边界切分，再通过窗口重叠把相邻"
    "片段的衔接部分补回来，使跨越边界的问题仍然能够被召回。"
)


def _coverage_chapter() -> str:
    sections = [
        f"## {title}\n\n{_COVERAGE_PARAGRAPH * 4}"
        for title in ("切分粒度", "窗口重叠", "召回验证")
    ]
    return "# 文档切分策略：块大小与重叠调优\n\n" + "\n\n".join(sections)


def _coverage_context(key_points: list[str], topic: str = "文档切分策略：块大小与重叠调优") -> dict:
    return {"current": {"topic": topic, "teaching_spec": {"key_points": key_points}}}


def test_coverage_gap_is_advisory_and_never_blocks_the_document():
    """Coverage depends on wording, so it must not reject a structurally sound chapter.

    The generating prompt already carries these key points, so a wording mismatch
    would repeat on every regeneration instead of converging.
    """
    chapter = _coverage_chapter()
    context = _coverage_context(["文档切分与块重叠"])

    # 正文写了「文档切分」「窗口重叠」，但没有逐字写出「块重叠」这一段。
    assert "块重叠" not in chapter
    assert evaluate_key_point_coverage(chapter, context) != []
    assert validate_document_chapter(chapter, context) == []


@pytest.mark.parametrize(
    "key_point",
    [
        "文档切分/窗口重叠",
        "文档切分与窗口重叠",
        "文档切分（块大小、窗口重叠）",
    ],
)
def test_composite_key_points_match_their_own_terms(key_point):
    """Composite key points are authored with delimiters, so match them per term."""
    assert evaluate_key_point_coverage(_coverage_chapter(), _coverage_context([key_point])) == []


def test_aspect_suffix_matches_the_bare_concept():
    """「文档切分作用」 names a concept plus an angle; the text only writes the concept."""
    assert evaluate_key_point_coverage(_coverage_chapter(), _coverage_context(["文档切分作用"])) == []


def test_unrelated_key_points_are_still_reported():
    """The advisory signal must not degrade into always-clean."""
    gaps = evaluate_key_point_coverage(
        _coverage_chapter(),
        _coverage_context(["向量检索", "余弦相似度", "近邻搜索"]),
    )
    assert len(gaps) == 3


def test_topic_only_key_points_are_never_flagged():
    """`key_points == [topic]` is the deliberate fallback and always hits the H1."""
    context = _coverage_context(["文档切分策略：块大小与重叠调优"])
    assert evaluate_key_point_coverage(_coverage_chapter(), context) == []
