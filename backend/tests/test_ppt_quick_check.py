# -*- coding: utf-8 -*-
"""PPT 格式快检：**别把正常内容判成"渲染泄漏"**。

## 为什么这条重要

快检是**硬闸**：它判不通过，整节 PPT 会被重新生成一次（实测单次 9–40 秒），
连续不过还会在烧完轮次后把整节换成兜底稿。

那条"HTML/KaTeX 泄漏"的正则原来长这样：

    katex|mathml|spanclass|xmlns|semantics|mrow|&lt;/?[a-z]|<(?!/?!--)[a-z][^>]*>

最后一段是"任意 `<` + 字母"。而 **Python 正常的 repr 正好长这样**：

    type(args)   →   <class 'tuple'>
    函数对象      →   <function f at 0x7f2a>

C++/Java 课的泛型 `vector<int>` 也一样中招。实测一节讲 `*args` 的 PPT 因此**连生 5 轮、
全被同一个理由拒掉**（25.5+39.5+8.9+22.2+9.7 ≈ 106 秒），最后整节丢掉换成兜底稿 ——
内容本身是对的，模型怎么改都改不掉，**这个循环不可能收敛**。

> 说明白证据的边界：那 5 轮的**被拒正文没有进事件流**（只有推送出去的成品才进 SSE 事件），
> 所以"到底是哪一句命中的"在产物里查不到。这里钉的是**已经能证明的那一半** ——
> 正则确实会误伤 Python repr，而这个主题的页面几乎必然出现 `type(args)` 的输出。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.ai_core.resource_ppt import _quick_check_ppt  # noqa: E402

# 一页"正常"的 PPT：标题 + layout + 两条实质要点 + 带标签的讲稿。
_GOOD_SLIDE = """## 默认参数的可变值陷阱
<!-- layout: content_cards -->

- **核心规则**：默认值只在函数定义时求值一次，之后每次调用复用同一个对象，所以可变默认值会在调用之间共享状态。
- **最小例子**：`def add(item, lst=[])` 连调三次会得到 [1]、[1, 2]、[1, 2, 3]，改用 `lst=None` 再在函数体内建列表即可避免。

> 讲稿：默认参数只在 def 执行那一刻求值一次，所以方括号里的列表全程序只有一个。"""


def _slide_with(body: str, note: str = "> 讲稿：这一段讲的是本页的核心规则，读的时候注意求值时机。") -> str:
    """拼一页正文。**要额外垫一条要点**：可见正文不足 60 字会先撞上 `too_sparse_visible_content`，
    那样测出来的就不是"有没有误判成 HTML 泄漏"了（第一版夹具就是这么栽的）。"""
    filler = ("- **核心规则**：本节只解决一个可验证的判断，读完后你应当能用一句话讲清它的适用条件，"
              "并指出一个常见的误用场景，而不是只记住结论。")
    return f"## 一个足够长的标题用来占位\n<!-- layout: content_cards -->\n\n{body}\n{filler}\n\n{note}"


# ── 误伤（这次修的就是这一类）──

def test_python_repr_is_not_mistaken_for_html_leak():
    """`type(args)` 的输出长这样，它是**正确的 Python**，不是 HTML。"""
    for text in ("<class 'tuple'>", "<class 'list'>", "<class 'int'>"):
        ok, reason = _quick_check_ppt(_slide_with(f"- **最小例子**：`print(type(args))` 的输出是 {text}，说明打包后的结果是一个元组。"))
        assert ok, f"{text} 被误判成 {reason}"


def test_function_and_module_reprs_are_not_mistaken_for_html_leak():
    for text in ("<function f at 0x7f2a>", "<module 'os' from '/usr/lib/python3'>"):
        ok, reason = _quick_check_ppt(_slide_with(f"- **易错点**：直接打印函数对象会看到 {text}，这不是它的返回值，要多加括号调用。"))
        assert ok, f"{text} 被误判成 {reason}"


def test_generic_type_arguments_are_not_mistaken_for_html_leak():
    """C++/Java 课的泛型写法。标签表里刻意不收 `int` 这类会撞上泛型的短名。"""
    ok, reason = _quick_check_ppt(_slide_with("- **核心规则**：声明 `vector<int> v` 表示这个容器只装整数，越界访问不会自动扩容，需要先判断容量。"))
    assert ok, f"vector<int> 被误判成 {reason}"


def test_a_less_than_in_prose_is_not_mistaken_for_a_tag():
    """`若 a<b 且 b>c` 里的 `<b …>` 不是标签：标签后面只能跟属性或直接闭合。"""
    ok, reason = _quick_check_ppt(_slide_with("- **最小例子**：若 a<b 且 b>c，则 b 是三个数里的中间值，可以用两两比较验证这个结论。"))
    assert ok, f"比较表达式被误判成 {reason}"


# ── 该抓的还得抓得住 ──

def test_real_katex_leak_is_still_caught():
    """这条是闸门存在的理由，改动不能把它关掉。"""
    for leak in ('<span class="katex">x</span>', "<math><mrow>x</mrow></math>", "<semantics>y</semantics>"):
        ok, reason = _quick_check_ppt(_slide_with(f"- **最小例子**：公式渲染后残留了 {leak}，说明 HTML 标签漏出来了。"))
        assert not ok and reason == "rendered_html_or_katex_leak", f"{leak} 没被抓到（{reason}）"


def test_a_plain_html_tag_is_still_caught():
    ok, reason = _quick_check_ppt(_slide_with("- **最小例子**：这一行里有 <div> 这样的标签，属于渲染产物泄漏。"))
    assert not ok and reason == "rendered_html_or_katex_leak"


def test_an_escaped_html_entity_is_still_caught():
    ok, reason = _quick_check_ppt(_slide_with("- **最小例子**：转义后的 &lt;span 也算泄漏，说明渲染中间态被写进了正文。"))
    assert not ok and reason == "rendered_html_or_katex_leak"


# ── 其余判断保持原样 ──

def test_a_normal_slide_passes():
    ok, reason = _quick_check_ppt(_GOOD_SLIDE)
    assert ok, reason


def test_an_unlabeled_note_reports_missing_speaker_notes():
    """这是**软**原因（调用方 `soft_quick_reasons` 里列着）：不会触发重写，只照发去审核。

    模型不写「讲稿：」标签是常态（实测 34 页里 12 页没写），所以这里只钉住"如实报出来"，
    不钉"必须拒绝"。
    """
    slide = _GOOD_SLIDE.rsplit("\n", 2)[0] + "\n\n> 记住默认值只在 def 执行那一刻求值一次。"
    ok, reason = _quick_check_ppt(slide)
    assert not ok and reason == "missing_speaker_notes"


def test_omitted_content_and_ellipsis_are_still_caught():
    ok, reason = _quick_check_ppt(_slide_with("- **核心规则**：推导过程略，直接给出结论，其余步骤不再赘述，记住结果即可。"))
    assert not ok and reason == "omitted_content"

    ok, reason = _quick_check_ppt(_slide_with("- **核心规则**：剩下的几种情况依此类推，无需逐个举例，结论完全一致。"))
    assert not ok and reason == "omitted_content"
