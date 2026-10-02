# -*- coding: utf-8 -*-
"""分块：句子之间的空白不能被吃掉。

`_split_long_paragraph` 原来是 `sent.strip()` 之后 `current += sent`，而切分用的是
lookbehind（分隔符留在**上一句末尾**）：

    re.split(r"(?<=[。！？!?；;\n])", "...end. Next...")  →  ["...end.", " Next..."]

那句 `strip()` 把 " Next" 前的空格削掉，于是同一个块里的英文粘成 `end.Next`；段落内的
单个换行更是直接消失（两行并成一行）。中文因为句间本来就没有空格，看不出问题——所以这个
bug 只在英文/代码类材料上现形，而这些材料正是进阶学习那批用户手上的东西。

顺带钉住两件事（报告里对分块的三条断言，另两条的结论）：
- **入库正文相邻块之间确实没有重叠**（overlap 只在 `_hard_split` 那条最深的分支生效）；
- 送进嵌入模型的副本**有**跨片前缀（`apply_context_prefix`），两者不是一回事。
"""

import pytest

from backend.src.utils.file_processor import _split_long_paragraph, chunk_text


@pytest.mark.parametrize("mark", ["!", "?", ";"])
def test_english_sentences_keep_their_separating_space(mark):
    """核心回归：同一个块里的两句英文不能粘成 `matters!The second`。

    切分点用哪些符号这件事值得先说清：`[。！？!?；;\\n]` 里有全角句号 `。`，**没有**
    ASCII 的 `.`（见下面那条测试）—— 所以英文材料真正会切的是 `!` `?` `;` 和换行。
    报告里举的例子是 `"end."+"Next"`，符号说错了，机制是对的。
    """
    text = f"The first point matters{mark} The second point also matters."

    chunks = _split_long_paragraph(text, max_chars=200)

    assert chunks == [text]
    assert f"matters{mark}The" not in chunks[0]


def test_ascii_period_is_not_a_split_point():
    """**现状记录**，不是推荐做法：ASCII `.` 不在切分字符集里。

    所以英文材料的句级切分实际上只发生在 `!` `?` `;` 和换行上，其余的英文段落只能走
    `_hard_split`（那条分支才带 overlap）。没有顺手补上 `.` 是因为它会移动所有英文/代码
    材料的块边界（`3.14`、`e.g.`、`a.py` 都会成为切点）。要改得连着语料一起重切，
    那是另一件事。
    """
    assert _split_long_paragraph("A sentence. Another one.", max_chars=200) == [
        "A sentence. Another one."
    ]


def test_a_newline_inside_a_paragraph_survives():
    """段落内的换行是内容（代码、列表、诗句），不是切分噪声。"""
    text = "def add(a, b):\n    return a + b"

    chunks = _split_long_paragraph(text, max_chars=200)

    assert chunks == [text]
    assert "\n" in chunks[0]


def test_chunks_are_still_bounded_by_max_chars():
    """留白之后长度必须仍然守着上限 —— 别把 max_chars 撑破。"""
    text = ("Alpha beta gamma delta. " * 20).strip()

    chunks = _split_long_paragraph(text, max_chars=60)

    assert len(chunks) > 1
    assert all(len(chunk) <= 60 for chunk in chunks)


def test_chunk_boundaries_are_trimmed():
    """块**边界**的空白该去掉 —— 那是切分点产生的，不是原文里的（原文只在块内部保留）。"""
    chunks = _split_long_paragraph(" Alpha beta. " * 10, max_chars=30)

    assert all(chunk == chunk.strip() for chunk in chunks)
    assert all(chunk for chunk in chunks)


def test_chinese_is_unchanged():
    """中文句间本来就没有空格：不该凭空插一个进去。"""
    text = "第一句说的是定义。第二句说的是用法。"

    assert _split_long_paragraph(text, max_chars=200) == [text]


def test_a_single_over_long_sentence_falls_back_to_hard_split():
    """超过 max_chars 的单句走硬切，那条分支才是真重叠生效的地方。"""
    sentence = "x" * 300

    chunks = _split_long_paragraph(sentence, max_chars=100, overlap_chars=20)

    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)


def _longest_shared_seam(previous: str, following: str) -> int:
    """前一块的后缀与后一块的前缀的最长重合长度 —— "两块之间有没有重叠"就看它。"""
    longest = 0
    for size in range(1, min(len(previous), len(following)) + 1):
        if previous[-size:] == following[:size]:
            longest = size
    return longest


def test_stored_content_between_neighbouring_chunks_has_no_overlap():
    """入库正文：相邻块之间没有重叠（这是既有口径，别当成 bug 去"修"）。

    overlap 只在 `_hard_split`（单句长过 max_chars）那条最深的分支里生效；段落聚合和
    句子切分产出的相邻块是**不重叠**的。真正带重叠的是 `apply_context_prefix` 生成的那份
    **只用于编码**的副本 —— 两件事别混。用"最长接缝"而不是子串包含来判：用重复字写的
    测试文本会让子串包含随机命中。
    """
    text = "\n\n".join(
        f"段落{i}：" + "".join(f"第{i}段第{j}句说的是一个独立的知识点。" for j in range(20))
        for i in range(3)
    )

    chunks = chunk_text(text, max_chars=200, overlap_chars=80)

    assert len(chunks) > 1
    for previous, following in zip(chunks, chunks[1:]):
        assert _longest_shared_seam(previous, following) <= 20, "相邻入库块出现了重叠"


@pytest.mark.parametrize("empty_input", ["", "   ", "\n\n"])
def test_empty_input_still_returns_something(empty_input):
    """`chunk_text` 对空输入返回原串（调用方按"至少有一段"处理），别改成空列表。"""
    assert chunk_text(empty_input, max_chars=200, overlap_chars=80) == [empty_input]
