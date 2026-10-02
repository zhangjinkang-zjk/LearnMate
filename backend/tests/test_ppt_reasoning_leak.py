# -*- coding: utf-8 -*-
"""PPT 正文里混进模型的思考段：**整页会重复一遍，而且 `</think>` 直接给学生看**。

## 真实产物长什么样

这是实测的一次（`eval/results/20261002-201553`，第 1 轮第 6 页）。模型把自己写的草稿和
答案连在一起吐了出来，接缝是一个 `</think>`：

    …据此排除"具名参数在 `*args` 之前"…就能稳定得分。</think># **kwargs 关键字参数收容的字典化规则
    <!-- layout: content_cards -->
    **学习目标**：…（整页内容又出现一遍）

后果有两层：

1. **学生直接看到 `</think>`** —— 它出现在正文里，不是日志里。
2. **整页内容出现两遍**，一页上还并着两条引用行（草稿那条标签写成 `讨稿：`，答案那条是
   `讲稿：`）。讲稿修复函数只认一条，剩下那条就留在了页面上。

## 不是偶发

最近 5 轮真实生成里有 **2 轮**的成品正文带 `</think>`
（`20261002-192443`、`20261002-201553`），前几轮没有 —— 所以它跟着模型状态飘，
不能靠"下次不会再犯"。

## 判据为什么要用最后那个 `</think>`

`</think>` 之后才是模型的答案，前面那截是草稿。保留后面这截既去掉了标签，也顺手去掉了
重复的整页 —— 两件事一次解决。下面第一条用例用的就是上面那段真实原文，不是造出来的。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.ai_core.resource_ppt import _drop_leaked_reasoning, _repair_ppt_content  # noqa: E402

# 真实产物：模型一次输出里混了思考段的那一节（`**kwargs 关键字参数收容`）。
_REAL_LEAKED_SECTION = """## **kwargs 关键字参数收容的字典化规则
<!-- layout: content_cards -->
**学习目标**：学完本页能判断任意函数签名中 `**kwargs` 收容了哪些多余关键字参数，并说出它在内存中的数据类型是字典。

**核心规则**：调用函数时，凡未被位置参数和具名关键字参数匹配的关键字实参，全部按 `键=值` 收进 `kwargs` 字典；`kwargs` 只是变量名可改写，前缀 `**` 表示收容，绝不可省略。

**最小例子**：`def create_user(name, **kwargs)` 调用 `create_user('Alice', age=25, email='a@b.com')`，得到 `name='Alice'`，`kwargs={'age': 25, 'email': 'a@b.com'}`，可用 `kwargs['age']` 读取。

**顺序边界**：签名中参数必须按"位置参数 → `*args` → 具名关键字参数 → `**kwargs`"排列，`**kwargs` 必须居末；颠倒顺序会直接触发 `SyntaxError`，这是编译期就能发现的硬错误。

**自查提醒**：做排列组合多选题时，逐个数签名里 `*` 的个数——`*` 只能出现两次且第二次必带 `**`，据此排除"具名参数在 `*args` 之前""`**kwargs` 后还有参数"等错误选项。
> 讨稿：先记住 **kwargs 不是特殊变量，而是把所有没被接住的关键字实参打包成一个普通字典，所以它支持 get、keys 和下标访问。看 create_user 这个例子，name 接住位置参数，age 和 email 因为没有对应形参，被整体收进 kwargs。做排列组合题时按位置参数、*args、具名参数、**kwargs 这条固定顺序去比对，凡是顺序颠倒的选项一律排除，再检查 ** 有没有漏写，就能稳定得分。</think># **kwargs 关键字参数收容的字典化规则
<!-- layout: content_cards -->
**学习目标**：学完本页能判断任意函数签名中 `**kwargs` 收容了哪些多余关键字参数，并说出它在内存中的数据类型是字典。

**核心规则**：调用函数时，凡未被位置参数和具名关键字参数匹配的关键字实参，全部按 `键=值` 收进 `kwargs` 字典；`kwargs` 只是变量名可改写，前缀 `**` 表示收容，绝不可省略。

**最小例子**：`def create_user(name, **kwargs)` 调用 `create_user('Alice', age=25, email='a@b.com')`，得到 `name='Alice'`，`kwargs={'age': 25, 'email': 'a@b.com'}`，可用 `kwargs['age']` 读取。

**顺序边界**：签名中参数必须按"位置参数 → `*args` → 具名关键字参数 → `**kwargs`"排列，`**kwargs` 必须居末；颠倒顺序会直接触发 `SyntaxError`，这是编译期就能发现的硬错误。

**自查提醒**：做排列组合多选题时，逐个数签名里 `*` 的个数——`*` 只能出现两次且第二次必带 `**`，据此排除"具名参数在 `*args` 之前""`**kwargs` 后还有参数"等错误选项。
> 讲稿：先记住 `**kwargs` 不是特殊变量，而是把所有没被接住的关键字实参打包成一个普通字典，所以它支持 get、keys 和下标访问。看 create_user 这个例子，name 接住位置参数，age 和 email 因为没有对应形参，被整体收进 kwargs。做排列组合题时按位置参数、*args、具名参数、**kwargs 这条固定顺序去比对，凡是顺序颠倒的选项一律排除，再检查 ** 有没有漏写，就能稳定得分。"""

assert "</think>" in _REAL_LEAKED_SECTION, "夹具本身得带 </think>，否则这条用例什么也没测"


def _quotes(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip().startswith(">")]


# ── 那条真实产物 ──

def test_the_leaked_tag_does_not_survive_into_the_deck():
    out = _repair_ppt_content(_REAL_LEAKED_SECTION, "**kwargs 关键字参数收容")
    assert "</think" not in out.lower()


def test_the_page_body_appears_only_once():
    """重复的那一份必须消失 —— 判据用标题：一页只有一个标题。"""
    out = _repair_ppt_content(_REAL_LEAKED_SECTION, "**kwargs 关键字参数收容")
    titles = re.findall(r"(?m)^#{1,2} \S.*$", out)
    assert len(titles) == 1, f"标题出现了 {len(titles)} 个：{titles}"


def test_the_page_ends_with_exactly_one_note():
    out = _repair_ppt_content(_REAL_LEAKED_SECTION, "**kwargs 关键字参数收容")
    quotes = _quotes(out)
    assert len(quotes) == 1, f"一页上有 {len(quotes)} 条引用行：{quotes}"
    assert quotes[0].startswith("> 讲稿：")


def test_the_surviving_note_is_the_models_real_one_not_the_draft():
    """丢掉的是草稿（标签写成 `讨稿：`、正文里 `**kwargs` 没加反引号），留下的是答案。"""
    out = _repair_ppt_content(_REAL_LEAKED_SECTION, "**kwargs 关键字参数收容")
    note = _quotes(out)[0]
    assert "讨稿" not in note
    assert "`**kwargs` 不是特殊变量" in note


# ── 干净输入不能被它动到 ──

def test_a_clean_section_passes_through_untouched():
    clean = (
        "## 默认参数的可变值陷阱\n<!-- layout: content_cards -->\n"
        "- **核心规则**：默认值只在函数定义时求值一次，之后每次调用复用同一个对象。\n"
        "> 讲稿：默认参数只在 def 执行那一刻求值一次，所以方括号里的列表全程序只有一个。"
    )
    kept, dropped = _drop_leaked_reasoning(clean)
    assert dropped == 0 and kept == clean


def test_a_section_that_is_only_reasoning_becomes_empty():
    """整段都是思考、`</think>` 后面什么也没有 —— 返回空，让调用方走重写/兜底。

    返回空字符串是**对的**：那一段里没有任何能给学生看的内容。若把它原样留下，
    成品里就会出现一页只有思考段。
    """
    kept, dropped = _drop_leaked_reasoning("<think>先想一下这一页怎么排</think>")
    assert kept == "" and dropped > 0
    assert _repair_ppt_content("<think>先想一下这一页怎么排</think>", "标题") == ""


def test_the_last_tag_wins_so_a_second_draft_is_also_dropped():
    text = "草稿一</think>草稿二</think>## 真答案\n正文。"
    kept, _ = _drop_leaked_reasoning(text)
    assert kept.startswith("## 真答案")


def test_the_tag_is_recognised_regardless_of_case():
    kept, dropped = _drop_leaked_reasoning("草稿</THINK>## 标题")
    assert dropped > 0 and kept.startswith("## 标题")
