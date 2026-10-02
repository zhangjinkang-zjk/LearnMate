# -*- coding: utf-8 -*-
"""PPT 分节辅助函数：**它们是纯文本函数，本来就该能直接调。**

这四个原先嵌在 `generate_ppt_parallel`（800 行）里面，只能靠**真发一次模型调用**才覆盖到。
把内部函数提到模块层的判据是算出来的、不是看出来的：它们的自由变量里只有内建名字
（`str`/`int`/`len`/`range`/`tuple`），没有任何来自外层函数的变量 —— 所以名字从闭包变量
变成全局变量，**调用点一个字都不用改**。

这里钉住两件事：
1. 搬出来之后行为没变（尤其是 `_limit_section_pages`，讲稿丢失那次事故的证据就打在它里面）；
2. 它们确实是**顶层**函数 —— 否则就等于没搬（嵌在里面的那份会遮住外面这份，
   用例全绿而真正在跑的仍是里面那份）。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.ai_core import resource_ppt  # noqa: E402
from backend.src.ai_core.resource_ppt import (  # noqa: E402
    _iter_text_chunks,
    _limit_section_pages,
    _strip_framework,
    _trim_section_context,
)

# 一页真实的 PPT（正文 + 讲稿），分页符按下游那套写法。
_SLIDE = (
    "## 默认参数的可变值陷阱\n"
    "<!-- layout: content_cards -->\n"
    "\n"
    "- **核心规则**：默认值只在函数定义时求值一次，之后每次调用复用同一个对象。\n"
    "\n"
    "> 讲稿：默认参数只在 def 执行那一刻求值一次，所以方括号里的列表全程序只有一个。"
)


def _note_pages(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*---+\s*\n", text) if p.strip()]


# ── 它们是顶层函数，不是嵌套的 ──

def test_the_helpers_are_module_level_functions():
    """嵌在 `generate_ppt_parallel` 里的同名函数会**静默遮住**模块层这份。"""
    source = Path(resource_ppt.__file__).read_text(encoding="utf-8")
    for name in ("_strip_framework", "_limit_section_pages",
                 "_trim_section_context", "_iter_text_chunks"):
        # 用 `[ \t]*` 而不是 `\s*`：`\s` 会连换行一起吃掉，缩进就看不出来了
        hits = re.findall(rf"^([ \t]*)def {name}\b", source, flags=re.MULTILINE)
        assert len(hits) == 1, f"{name} 出现了 {len(hits)} 次"
        assert hits[0] == "", f"{name} 还缩进着（{hits[0]!r}），等于没搬出去"


# ── 限页：截断可以，但不能切出"没讲稿的那一页" ──

def test_pages_over_the_limit_are_truncated():
    content = "\n---\n".join([_SLIDE, _SLIDE.replace("默认参数", "位置参数"), _SLIDE.replace("默认参数", "关键字参数")])
    out = _limit_section_pages(content, "参数传递")
    assert len(_note_pages(out)) == resource_ppt.PPT_MAX_PAGES_PER_SECTION


def test_a_section_within_the_limit_is_untouched():
    content = "\n---\n".join([_SLIDE, _SLIDE.replace("默认参数", "位置参数")])
    assert _limit_section_pages(content, "参数传递") == content


def test_every_page_that_survives_still_has_its_note():
    """截断只能整页丢，不能把某一页的讲稿留在别的页上。

    这条是那次"讲稿丢失"事故的直接产物：`_limit_section_pages` 里除了截断，还有一段
    证据日志，专门盯"限页之后出现了没有讲稿的页"。
    """
    content = "\n---\n".join([_SLIDE] * 4)
    for page in _note_pages(_limit_section_pages(content, "参数传递")):
        assert "> 讲稿：" in page


def test_an_empty_or_blank_content_yields_no_pages():
    assert _limit_section_pages("", "空章节") == ""
    assert _limit_section_pages("   \n\n  ", "空章节") == ""


def test_stray_separator_lines_do_not_create_phantom_pages():
    """首尾的分页线不该切出空页（空页会被 `if slide.strip()` 丢掉，但页数要对得上）。"""
    content = f"---\n{_SLIDE}\n---\n"
    assert len(_note_pages(_limit_section_pages(content, "参数传递"))) == 1


# ── 剥离 markdown 骨架 ──

def test_markdown_scaffolding_is_stripped_from_visible_text():
    raw = (
        "## 标题\n\n- **核心规则**：一行字。\n\n"
        "> 引用内容\n\n"
        "`code` 和 [链接](https://example.com)\n\n"
        "$$E = mc^2$$\n\n"
        "```python\nprint(1)\n```\n"
    )
    out = _strip_framework(raw)
    for gone in ("##", "**", ">", "`", "](", "$$", "```", "print(1)"):
        assert gone not in out, f"{gone!r} 没被剥掉：{out!r}"
    assert "核心规则" in out and "引用内容" in out and "链接" in out


# ── 章节上下文裁剪：首章全给，后续章省 token ──

def test_the_first_section_keeps_the_full_context():
    full = ("画像" * 50, "目标" * 50, "指导" * 200)
    assert _trim_section_context(*full, "第一章", 0, 6) == full


def test_later_sections_get_trimmed_context():
    portrait, lo, guidance = "画像" * 50, "目标" * 50, "指导" * 200
    tp, tl, tg = _trim_section_context(portrait, lo, guidance, "参数传递", 3, 6)
    assert len(tp) < len(portrait) and len(tl) < len(lo)
    assert len(tg) <= 120 + len("…（完整要求见首章）")
    # 章节定位要留下 —— 裁的是重复内容，不是"这一章是什么"
    assert "参数传递" in tp and "参数传递" in tl and "第4章" in tl


def test_placeholder_values_do_not_leak_into_the_trimmed_context():
    tp, tl, _ = _trim_section_context("暂无画像数据", "暂无学习目标数据", "", "参数传递", 2, 6)
    assert tp == "" and tl == ""


# ── 按块切分文本（推送用）──

def test_text_is_chunked_without_losing_anything():
    text = "一二三四五六七八九十" * 3
    chunks = list(_iter_text_chunks(text, 7))
    assert "".join(chunks) == text
    assert all(len(c) <= 7 for c in chunks)
