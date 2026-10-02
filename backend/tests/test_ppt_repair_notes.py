# -*- coding: utf-8 -*-
"""PPT 讲稿修复：**不能把模型已经写好的讲稿当成"没写"再补一条**。

## 这个 bug 长什么样

真实生成出的 PPT 里，一页上出现过**两条讲稿**：

    > 记住默认值里的空列表只在执行 def 那一刻创建一次，之后每次省略参数拿到的都是同一个对象…
    > 讲稿：本页围绕「可变默认参数陷阱」展开讲解。请先说明本页学习目标，再用一个小例子或检查动作帮助学习者确认自己是否真正理解。

第一条是模型写的，讲得很实在，只是**没带「讲稿：」标签**；第二条是代码补的占位套话。
`_repair_ppt_content` 当时只用正则认 `> 讲稿：` 这个**标签**，认不出就判定"这页没写讲稿"，
于是补一条。两次真实生成里分别有 **12/34 和 11/17 页**是这样，而"整页一个字都没写"的是
**0 页** —— 兜底句几乎全用在了有真讲稿的页上。

（诊断过程留个教训：我最初把这两条都归给了模型，先说"模型退化成套话"、又改口说"模型没写
讲稿"，两次都错。**是解析器认标签不认内容**。所以下面第一条用例直接用那一页的真实文本当夹具。）

## 为什么这些用例值得存在

它是纯文本函数，却**原先嵌在 `generate_ppt_parallel` 里**，只能靠真发一次模型调用才覆盖得到 ——
而它产出的文本会直接进成品（学生看得到、视频会念出来）。现在它提到了模块层，可以便宜地测。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.ai_core import resource_ppt  # noqa: E402
from backend.src.ai_core.resource_ppt import _repair_ppt_content  # noqa: E402

# 兜底占位句曾经的原话。它读起来像"写给老师的指令"，不像讲稿 —— 现在不该再出现。
_OLD_PLACEHOLDER = "请先说明本页学习目标"

# 模型真实产出的那一页（**修复前**的形态：讲稿在，但没带「讲稿：」标签）。
_REAL_SLIDE_WITHOUT_LABEL = """## 可变默认参数的状态共享诊断与修复
<!-- layout: content_cards -->

**学习目标**：读到 `def counter(lst=[])` 这类函数签名，能指出空列表只在 `def` 执行的那一刻创建一次，进而判断连续多次调用是否发生了跨调用的状态泄漏。

**核心规则**：Python 的默认参数在函数定义时求值一次并绑定到对象；若该对象可变（列表、字典、集合），所有省略此参数的调用都共享同一份内容。

**自查提醒**：修复写法是把默认值改为 `None`，并在函数体首行重新建列表；看到默认值位置出现 `[]`、`{}`、`set()` 就应立刻怀疑状态共享。

> 记住默认值里的空列表只在执行 def 那一刻创建一次，之后每次省略参数拿到的都是同一个对象，所以 add(1)、add(2)、add(3) 会依次打印 [1]、[1, 2]、[1, 2, 3]。"""


def _quotes(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip().startswith(">")]


# ── 有讲稿，只是没带标签 ──

def test_a_note_without_the_label_is_kept_not_replaced():
    """这一条就是那个真实 bug。模型写的讲稿必须原样留下。"""
    out = _repair_ppt_content(_REAL_SLIDE_WITHOUT_LABEL, "可变默认参数陷阱")
    assert "记住默认值里的空列表只在执行 def 那一刻创建一次" in out


def test_the_unnamed_note_does_not_come_with_a_second_placeholder():
    """成品里不能出现两条讲稿 —— 一条真的、一条补的。"""
    out = _repair_ppt_content(_REAL_SLIDE_WITHOUT_LABEL, "可变默认参数陷阱")
    quotes = _quotes(out)
    assert len(quotes) == 1, f"一页上出现了 {len(quotes)} 条讲稿：{quotes}"
    assert quotes[0].startswith("> 讲稿：")


def test_the_real_note_is_relabelled_not_rewritten():
    """系统只该补上「讲稿：」这个标签，不该改模型写的正文。"""
    out = _repair_ppt_content(_REAL_SLIDE_WITHOUT_LABEL, "可变默认参数陷阱")
    body = _quotes(out)[0].removeprefix("> 讲稿：")
    assert body.startswith("记住默认值里的空列表只在执行 def 那一刻创建一次")


# ── 带标签的（原本就对）不能被改坏 ──

def test_a_labeled_note_stays_a_single_line_with_its_body():
    slide = "## 标题\n\n**核心规则**：一句话规则。\n\n> 讲稿：直接讲给学生听的一段说明，不要写成对老师的指令。"
    out = _repair_ppt_content(slide, "标题")
    quotes = _quotes(out)
    assert len(quotes) == 1
    assert "直接讲给学生听的一段说明" in quotes[0]


def test_a_misspelled_label_is_stripped_rather_than_kept():
    """模型会把「讲稿」写成同音/形近的变体 —— 真实一轮 12 条里出现过 5 条
    （讨稿 / 讘稿 / 讥稿 / 讙稿，都抄自实测输出）。

    剥不干净的话成品里就是 `> 讲稿：讨稿：…` 这种**双标签**：学生看到两个标签，
    视频朗读会连读两遍。所以标签按「短标签 + 稿 + 冒号」认，而不是只认「讲稿」两个字。
    """
    for wrong in ("讨稿", "讘稿", "讥稿", "讙稿"):
        slide = (
            "## 标题\n\n**核心规则**：一句话规则，够长到不触发学习提示兜底。\n\n"
            f"> {wrong}：默认参数有两条必须记住的规则，第一条是位置约束。"
        )
        out = _repair_ppt_content(slide, "标题")
        quotes = _quotes(out)
        assert len(quotes) == 1, f"{wrong}：出现了 {len(quotes)} 条引用行"
        assert quotes[0].startswith("> 讲稿：默认参数有两条必须记住的规则"), quotes[0]


def test_two_stacked_labels_are_both_stripped():
    """正文里会**叠着两层标签**：系统自己加的「讲稿：」+ 模型写的变体。

    这一条是补写的 —— 上面那条单标签用例当时全绿，而**真实产物回放**里 5/13 页
    还留着双标签（`> 讲稿：讘稿：…`），因为只剥了一次。教训：用例的输入要照抄
    真实数据，不能自己造一个"干净"的。
    """
    slide = (
        "## 标题\n\n**核心规则**：一句话规则，够长到不触发学习提示兜底。\n\n"
        "> 讲稿：讘稿：本页的目标是分清形参与实参，实参按位置绑定到形参。"
    )
    out = _repair_ppt_content(slide, "标题")
    quotes = _quotes(out)
    assert len(quotes) == 1
    assert quotes[0].startswith("> 讲稿：本页的目标是分清形参与实参"), quotes[0]


# ── 一个字都没写的页 ──

def test_a_slide_with_no_note_at_all_gets_a_placeholder_that_is_not_an_instruction():
    """真的一行引用都没有时才补占位；补出来的也不能是"写给老师的指令"。"""
    slide = "## 标题\n\n**核心规则**：一句话规则，够长到不触发学习提示兜底。"
    out = _repair_ppt_content(slide, "标题")
    quotes = _quotes(out)
    assert len(quotes) == 1
    assert quotes[0].startswith("> 讲稿：")
    assert _OLD_PLACEHOLDER not in out
    # 占位句自己也不能假装在讲课
    assert "帮助学习者确认自己是否真正理解" not in out


# ── 分页线：修复的产物必须"再切一次也不变形" ──

def _pages(text: str) -> list[str]:
    """按**下游那套**方式切页（限页、拼装成册用的就是它）。"""
    return [p for p in re.split(r"\n\s*---+\s*\n", text) if p.strip()]


def test_a_trailing_separator_line_does_not_produce_a_note_less_page():
    """**真实 bug 的复现，别删。**

    模型有时把分隔线写到最后一行、后面没有换行。分页正则要求分隔线**前后都有换行**，
    所以它认不出来，被当成正文留在了这一页里；而讲稿是补在**页尾**的 —— 补完之后那条线
    从"页尾"变成"页中"，下游再切一次就多切出一页：

        第 1 页：正文，没有讲稿
        第 2 页：只有一条讲稿

    真实生成里 3 轮出现 2 次（`可变关键字参数 **kwargs 详解`、`Python参数传递对象模型`），
    页面形状与下面这个断言完全一致。
    """
    out = _repair_ppt_content(_REAL_SLIDE_WITHOUT_LABEL + "\n---", "可变默认参数陷阱")
    pages = _pages(out)
    assert len(pages) == 1, f"被切成了 {len(pages)} 页"
    assert _quotes(pages[0]), "唯一那一页没有讲稿"


def test_a_leading_separator_line_is_also_dropped():
    out = _repair_ppt_content("---\n" + _REAL_SLIDE_WITHOUT_LABEL, "可变默认参数陷阱")
    pages = _pages(out)
    assert len(pages) == 1
    assert _quotes(pages[0])


def test_the_repair_output_survives_being_split_again():
    """修复的产物一定会被**再切一次**，所以它必须是不动点。

    这里把一个正常页面加上各种"开头/结尾的分页线写法"（含缺换行、带空格、CRLF），
    要求每一种都仍然只有一页、且那一页有讲稿。
    """
    for ending in ("", "\n---", "\n----", "\n --- ", "\n---\n", "\r\n---", "\n--- \n\n"):
        out = _repair_ppt_content(_REAL_SLIDE_WITHOUT_LABEL + ending, "可变默认参数陷阱")
        pages = _pages(out)
        assert len(pages) == 1, f"结尾 {ending!r} 被切成了 {len(pages)} 页"
        assert _quotes(pages[0]), f"结尾 {ending!r} 的那一页没有讲稿"


# ── 两个源码级守护 ──

def test_the_instruction_shaped_placeholder_is_gone_from_the_module():
    """行为用例挡不住"某个分支没被走到"：兜底句只在没有引用行时出现，
    而真实数据里这种情况一次都没发生。所以这里直接看源码里还有没有那句话。"""
    source = Path(resource_ppt.__file__).read_text(encoding="utf-8")
    assert _OLD_PLACEHOLDER not in source


def test_the_repair_function_is_defined_exactly_once():
    """同名函数写两遍不报错，只会**静默地**让其中一份永不生效（`_add_bullets` 栽过一次）。
    这里尤其危险：嵌在 `generate_ppt_parallel` 里的那份会遮住模块层这份，
    行为用例全绿，而被修的那份根本没在跑。"""
    source = Path(resource_ppt.__file__).read_text(encoding="utf-8")
    assert len(re.findall(r"^\s*def _repair_ppt_content\b", source, flags=re.MULTILINE)) == 1
