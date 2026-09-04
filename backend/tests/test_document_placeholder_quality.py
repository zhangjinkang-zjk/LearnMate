"""Regression coverage for context-aware document placeholder checks."""

from __future__ import annotations

import pytest

from backend.src.service.resource.document_quality import (
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
