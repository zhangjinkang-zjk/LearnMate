# -*- coding: utf-8 -*-
"""PPT 那条链：大纲 → 逐节并行生成 → 格式快检与修补 → 分节审核。

与 `ppt_planner.py` 的分工：planner 决定**讲哪些页**（大纲、公式速查表、页数上限），
这里负责**把页写成能用的文本**，并保证它不被机械硬伤卡住。

为什么这一层的函数住在模块层、而不是嵌在 `generate_ppt_parallel` 里：`_quick_check_ppt`
判错一次很贵（整节重新生成，实测 9–40 秒），而它原先只能靠真发一次模型调用才覆盖得到。
提出来之后，这些纯文本函数可以直接调、直接测。
"""
import asyncio
import logging
import re
import time

from backend.src.ai_core.llm_config import llm
from backend.src.ai_core.ppt_planner import (
    PPT_DEFAULT_SECTIONS,
    PPT_MAX_PAGES_PER_DECK,
    PPT_MAX_PAGES_PER_SECTION,
    generate_formula_sheet,
    generate_ppt_outline,
)
from backend.src.ai_core.streaming import push_agent_event as _push_agent_event
from backend.src.utils.knowledge_base import search as kb_search
from backend.src.utils.prompt_loader import load_prompt, fill_prompt
from backend.src.utils.json_parser import parse_llm_json
from backend.src.utils.slide_schema import PPT_SPEAKER_NOTES_MAX_CHARS, limit_speaker_notes
from backend.src.ai_core.resource_common import _parse_review_response
from backend.src.ai_core.resource_prompts import build_resource_prompt, _int_env


logger = logging.getLogger(__name__)


PPT_TARGET_CONCURRENT_USERS = max(1, _int_env("PPT_TARGET_CONCURRENT_USERS", 5))


PPT_MAX_SECTIONS_PER_REQUEST = max(1, _int_env("PPT_MAX_SECTIONS_PER_REQUEST", 19))


_PPT_GLOBAL_GEN_SEM = asyncio.Semaphore(PPT_TARGET_CONCURRENT_USERS * PPT_MAX_SECTIONS_PER_REQUEST)


# ═══════════════════════════════════════
#  PPT 格式快检 与 内容修补
# ═══════════════════════════════════════
#
# 快检原先嵌在 `generate_ppt_parallel` 里，只能靠真发一次模型调用才覆盖得到，而它判错一次
# **很贵**：误判 → 整节重新生成（实测单次 9–40 秒）。所以提到模块层，好被测试直接调。

# HTML / KaTeX 渲染产物的特征。
#
# **标签名必须写全，不能用"任意 `<字母`"来认。** 原来那条是 `<(?!/?!--)[a-z][^>]*>`，
# 而 Python 正常的 repr 正好长这样：`type(args)` 的输出 `<class 'tuple'>`、
# `<function f at 0x…>`；C++/Java 课的泛型 `vector<int>` 也一样中招。
# 实测一节讲 `*args` 的 PPT 因此**连生 5 轮、全被同一个理由拒掉**（25.5+39.5+8.9+22.2+9.7
# ≈ 106 秒），最后整节丢掉换成兜底稿 —— 内容本身是对的，模型怎么改都改不掉，
# **这个循环不可能收敛**。
_HTML_TAG_NAMES = (
    "html|head|body|div|span|p|br|hr|table|thead|tbody|tfoot|tr|td|th|caption|colgroup|col|"
    "ul|ol|li|dl|dt|dd|a|img|svg|path|g|rect|circle|ellipse|line|polyline|polygon|text|tspan|"
    "script|style|link|meta|iframe|canvas|video|audio|source|track|"
    "b|i|u|s|em|strong|sub|sup|small|big|font|center|code|pre|blockquote|figure|figcaption|"
    "h1|h2|h3|h4|h5|h6|"
    "math|semantics|annotation|mrow|mi|mo|mn|msup|msub|mfrac|msqrt|mroot|mtable|mtr|mtd|"
    "mtext|mspace|mpadded|menclose|mover|munder|munderover|mstyle|mphantom"
)


# 标签后面只能跟「属性」或直接闭合 —— 否则 `若 a<b 且 b>c` 这种数学式子里的 `<b …>` 会中招。
_HTML_LEAK_RE = re.compile(
    r"katex|mathml|spanclass|xmlns|semantics|mrow|&lt;/?[a-z]|"
    rf"</?(?:{_HTML_TAG_NAMES})(?:\s+[a-zA-Z-]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?)*\s*/?>",
    re.IGNORECASE,
)


_ELLIPSIS_RE = re.compile(r"\.{4,}|……{1,}")


_OMITTED_RE = re.compile(r"(同上|以此类推|依此类推|类似可得|不再赘述|此处不再展开|（略）|证明略|过程略|推导略|步骤略)")


_EMPTY_FORMULA_RE = re.compile(r"^\s*\$\$\s*\$\$\s*$", re.MULTILINE)


_HOLLOW_LABELS = (
    "学习目标", "核心规则", "最小例子", "自查提醒", "承接目标", "操作示范",
    "条件边界", "迁移检查", "要点", "步骤", "第一步", "第二步", "第三步",
    "第四步", "第五步",
)


def _ppt_content_len(text: str) -> int:
    """中英文/数字的**有效字数**：去掉行内代码的引号和 `$…$` 公式后再数。

    原先快检和修补各写了一份同名实现 —— 同名函数是会互相遮蔽的那种坑，这里只留一份。
    """
    clean = re.sub(r"`([^`]+)`", r"\1", text)
    clean = re.sub(r"\$[^$]*\$", "", clean)
    return len(re.findall(r"[一-鿿A-Za-z0-9]", clean))


def _is_hollow_ppt_item(text: str) -> bool:
    """要点是不是"空槽"（只有栏目名、冒号后没有实质内容）。"""
    item = re.sub(r"^\s*(?:[-*+]|\d+[.)、])\s*", "", text).strip()
    item = re.sub(r"^\s*(?:\*\*)?(.+?)(?:\*\*)?\s*$", r"\1", item).strip()
    match = re.match(r"^([^：:]{1,12})[：:]\s*(.*)$", item)
    if not match:
        return _ppt_content_len(item) < 8
    label, body = match.group(1).strip(), match.group(2).strip()
    if any(label.startswith(name) or name in label for name in _HOLLOW_LABELS):
        return _ppt_content_len(body) < 12
    return _ppt_content_len(item) < 12


def _quick_check_ppt(content: str) -> tuple[bool, str]:
    """格式安全快检：只拦截机械硬伤，内容质量留给 reviewer。"""
    normalized = str(content or "").strip()
    normalized = re.sub(r"^```(?:markdown|md)?\s*", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*```$", "", normalized)

    def _fail(reason: str, snippet: str = "") -> tuple[bool, str]:
        """判不通过时把**命中的片段**一起打出来。

        原先只记 `reason=rendered_html_or_katex_leak`，没有片段；而被拒的那一版正文
        根本不会进 SSE 事件流（只有推送出去的成品才进），于是"到底哪一句被判成渲染泄漏"
        **事后无从查证**。片段进日志，下一眼就能看见。
        """
        if snippet:
            logger.warning("[PPT-Fmt] 快检未通过 reason=%s 命中=%r", reason, snippet[:160])
        return False, reason

    if not normalized:
        return _fail("empty_content")
    failure_marker = re.search(
        r"(生成失败|无法生成|生成出错|failed to generate|generation failed)",
        normalized[:800],
        re.IGNORECASE,
    )
    if failure_marker:
        return _fail("generation_failure_marker", failure_marker.group(0))

    slides = re.split(r"\n\s*---+\s*\n", normalized)
    checked_slides = 0
    for slide in slides:
        slide = slide.strip()
        if not slide:
            continue
        leak = _HTML_LEAK_RE.search(slide)
        if leak:
            return _fail("rendered_html_or_katex_leak",
                         slide[max(0, leak.start() - 40):leak.end() + 20])
        if _EMPTY_FORMULA_RE.search(slide):
            return _fail("empty_formula_block", "$$ $$")
        has_layout = slide.startswith("<!-- layout:")
        has_title = slide.startswith("# ") or slide.startswith("## ")
        if not (has_layout or has_title):
            continue
        checked_slides += 1
        if "（上）" in slide or "（下）" in slide:
            return _fail("split_title_marker", "（上）/（下）")
        if slide.count("$") % 2 != 0:
            return _fail("unbalanced_dollar", "本页的 $ 个数是奇数")
        text_no_math = re.sub(r"\$\$[\s\S]*?\$\$", "", slide)
        text_no_math = re.sub(r"\$[^$]*\$", "", text_no_math)
        ellipsis = _ELLIPSIS_RE.search(text_no_math)
        if ellipsis:
            return _fail("ellipsis_placeholder", ellipsis.group(0))
        omitted = _OMITTED_RE.search(text_no_math)
        if omitted:
            return _fail("omitted_content", omitted.group(0))
        notes_match = re.search(
            r"(?m)^>\s*(?:讲稿|speaker notes?|notes?)\s*[:：]\s*(.*)$", slide, re.IGNORECASE
        )
        if not notes_match:
            # 注意：这是**软**原因（调用方 `soft_quick_reasons` 里列着），不会触发重写，
            # 只是照发去审核。想改成硬原因前先看 `_repair_ppt_content` 里那段注释 ——
            # 模型不写「讲稿：」标签是常态（实测 34 页里 12 页没写）。
            return _fail("missing_speaker_notes")
        if len(re.sub(r"\s+", " ", notes_match.group(1)).strip()) > PPT_SPEAKER_NOTES_MAX_CHARS:
            return _fail("speaker_notes_too_long")
        visible_lines = []
        for line in text_no_math.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("<!--", "#", ">")):
                continue
            if re.match(r"^\s*(?:[-*+]|\d+[.)、])\s*", stripped):
                if _is_hollow_ppt_item(stripped):
                    return _fail("hollow_bullet_or_step", stripped)
                visible_lines.append(stripped)
        if _ppt_content_len("\n".join(visible_lines)) < 60:
            return _fail("too_sparse_visible_content")
    if checked_slides <= 0:
        return _fail("missing_slide_title")
    return True, ""


def _log_ppt_pages_without_notes(stage: str, section_title: str, slides: list[str]) -> list[int]:
    """报出**哪几页没有讲稿**（返回 1 起的页码）。

    ## 为什么要单独有这么一个探针

    真实产物里出现过一页"整页没有讲稿，而下一页只有孤零零一条讲稿"（实测 15 页里第 11 页，
    模型把讲稿写在了分页符**之后**）。按理这不该存在 —— `_repair_ppt_content` 保证每页都
    会有一条讲稿（认标签、认引用行、都没有才补占位），可那一页三条路一条都没走。

    出问题的正文**不会进 SSE 事件流**（只有推送出去的成品才进），所以事后从产物里查不到
    中间态。链条上每一段各调一次这个函数，下一次真实生成就能直接看到**断在哪一环**。
    """
    missing = [
        i + 1 for i, slide in enumerate(slides)
        if not any(line.strip().startswith(">") for line in slide.splitlines())
    ]
    if missing:
        logger.warning(
            "[PPT-讲稿] %s section=%s 有 %d 页没有讲稿：第 %s 页",
            stage, section_title, len(missing), "、".join(str(i) for i in missing),
        )
    return missing


_SEPARATOR_ONLY_LINE = re.compile(r"^\s*---+\s*$")

# 模型偶尔把自己的思考段一起吐进正文。实测的接缝就长这样（两端都是真实产物里的原文）：
#
#     …就能稳定得分。</think># **kwargs 关键字参数收容的字典化规则
#
# 后果有两层：**学生会在正文里直接看到 `</think>`**，而且整页内容重复了一遍
# （草稿一份、答案一份，`</think>` 正好是那道接缝）。
# `</think>` 之后才是模型的答案，前面那截是草稿 —— 所以只保留最后一个 `</think>` 之后的内容，
# 两件事一次解决。实测最近 5 轮里有 2 轮的成品正文带着它，不是偶发。
_LEAKED_REASONING_RE = re.compile(r"(?s)^.*</think>", re.IGNORECASE)


def _drop_leaked_reasoning(text: str) -> tuple[str, int]:
    """丢掉 `</think>` 之前的思考段。

    Returns:
        (剩下的正文, 丢掉的字数)。没有 `</think>` 时原样返回、丢 0 字。
    """
    raw = str(text or "")
    if "</think>" not in raw.lower():
        return raw, 0
    kept = _LEAKED_REASONING_RE.sub("", raw, count=1).strip()
    return kept, len(raw.strip()) - len(kept)


def _strip_edge_separator_lines(text: str) -> str:
    """去掉这一页**首尾**的分页线（`---` 独占一行的那些）。

    ## 它为什么会把讲稿"弄丢"（实测过，修的时候别删）

    分页的正则要求分隔线**前后都有换行**，所以"写到最后一行、后面没有换行"的 `---`
    认不出来 —— 它被当成正文留在了这一页里。而讲稿是补在**页尾**的，补完这条线就从
    "页尾"变成了"页中"；下一次分割（`_limit_section_pages`、拼装成册）会在这里多切一刀，
    切出「一页没有讲稿 ＋ 一页只有讲稿」。

    实测复现（这一条已经写进 `test_ppt_repair_notes.py`）：

        A + "\\n> 讲稿：…\\n---"  →  出来被重切成 2 页，第 1 页 0 条讲稿

    真实生成里 3 轮出现 2 次（`可变关键字参数 **kwargs 详解`、`Python参数传递对象模型`），
    症状一致：那一页整页没有讲稿、下一页只有一条讲稿。所以这里把首尾的分页线清掉，
    让修复的输出对任何分割方式都是**不动点**。
    """
    lines = str(text or "").splitlines()
    while lines and _SEPARATOR_ONLY_LINE.match(lines[0]):
        lines.pop(0)
    while lines and _SEPARATOR_ONLY_LINE.match(lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def _repair_ppt_content(content: str, section_title: str) -> str:
    """修补非致命空槽，降低无意义重试率。

    **放在模块层是为了能被测试直接调**：原先它嵌在 `generate_ppt_parallel` 里，
    只能靠真发一次模型调用才覆盖得到，而它做的是纯文本改写（只吃文本、只吐文本），
    跟调用方没有任何耦合。
    """
    normalized = str(content or "").strip()
    if not normalized:
        return normalized
    # 出现在正文里的 `</think>` 是模型的思考段接缝：它之前的整段是草稿，不是要给学生看的正文。
    # 调用方（`_normalize_ppt_content`）已经丢过一次并记了日志；这里再兜一次，是因为
    # 测试和别的调用点会直接调本函数。
    normalized, _ = _drop_leaked_reasoning(normalized)
    if not normalized:
        return normalized
    logger.info(
        "[PPT-讲稿] 修复前 section=%s 页数=%d",
        section_title, len([s for s in re.split(r"\n\s*---+\s*\n", normalized) if s.strip()]),
    )

    def _repair_line(line: str) -> str:
        match = re.match(r"^(\s*(?:[-*+]|\d+[.)、])\s*)([^：:]{1,12})[：:]\s*(.*)$", line)
        if not match:
            return line
        prefix, label, body = match.group(1), match.group(2).strip(), match.group(3).strip()
        if _ppt_content_len(body) >= 8:
            return line
        fallback = (
            f"围绕「{section_title}」补充具体说明：说明本步骤要解决的问题、"
            "使用时需要满足的条件，以及学习者可以立即检查的结果。"
        )
        return f"{prefix}{label}：{fallback}"

    def _strip_quote_prefix(text: str) -> str:
        """把一条引用行还原成讲稿正文：先去 `>`，再去掉可能写了的「讲稿：」标签。

        **标签按「短标签 + 稿 + 冒号」认，不是只认「讲稿」两个字。** 模型会把「讲稿」
        写成同音/形近的变体（实测出现过 讨稿 / 讘稿 / 讥稿 / 讙稿，一轮 12 条里 5 条），
        只认「讲稿」的话剥不干净，成品里会留下 `> 讲稿：讨稿：…` 这样的双标签 —— 学生
        看到两个标签、视频也会连读两遍。
        """
        text = re.sub(r"^\s*>\s*", "", str(text or ""))
        # **要循环剥**：系统自己也会加一个「讲稿：」，被修过的正文里因此可能叠着两层
        # （`> 讲稿：讘稿：…`），只剥一次会剩下里层那个。用真实产物回放时就是这么暴露的 ——
        # 单标签的用例全绿，真数据里 5/13 页还剩双标签。
        label = re.compile(r"^(?:[^\s：:]{1,4}稿|speaker notes?|notes?)\s*[:：]\s*", re.IGNORECASE)
        previous = None
        while previous != text:
            previous = text
            text = label.sub("", text)
        return text.strip()

    labeled_notes = re.compile(r"(?m)^>\s*(?:讲稿|speaker notes?|notes?)\s*[:：].*$", re.IGNORECASE)
    any_quote = re.compile(r"(?m)^>.*$")

    repaired_slides: list[str] = []
    for raw_slide in re.split(r"\n\s*---+\s*\n", normalized):
        slide = raw_slide.strip()
        if not slide:
            continue
        lines = [_repair_line(line) for line in slide.splitlines()]
        repaired = "\n".join(lines).strip()

        # 讲稿：**先认「讲稿：」标签，认不出标签就认这条引用行本身。**
        #
        # 模型经常把讲稿写成不带标签的引用行（`> 记住默认值只在 def 执行那一刻求值一次…`）——
        # 内容是对的，只是没照格式。这里原先只认标签，认不出就当作"这页没写讲稿"，再补一条
        # 占位句；成品于是**两条并存**：模型写的真讲稿 + 系统补的套话。
        # 实测两次真实生成里各有 12/34、11/17 页是这样，而"整页一个字都没写"的是 0 页 ——
        # 兜底句几乎全用错了地方。所以现在只在**整页没有任何引用行**时才用它，且不再写成
        # 对老师的指令（那是套话，学生听了什么也得不到）。
        labeled = labeled_notes.search(repaired)
        if labeled:
            quote_span, quote_line = labeled.span(), labeled.group(0)
        else:
            quotes = list(any_quote.finditer(repaired))
            quote_span = quotes[-1].span() if quotes else None
            quote_line = quotes[-1].group(0) if quotes else ""

        notes_body = _strip_quote_prefix(quote_line) or f"这一页的内容是「{section_title}」。"
        notes_line = f"> 讲稿：{limit_speaker_notes(notes_body)}"
        if quote_span:
            repaired = (repaired[:quote_span[0]] + repaired[quote_span[1]:]).strip()
        # 讲稿补在页尾，所以这一页**不能以分页线收尾** —— 否则补完就多出一页（见上面的说明）。
        repaired = _strip_edge_separator_lines(repaired)
        visible_text = "\n".join(
            line.strip()
            for line in repaired.splitlines()
            if line.strip() and not line.strip().startswith(("<!--", "#", ">"))
        )
        if _ppt_content_len(visible_text) < 60:
            repaired += (
                f"\n- 学习提示：本页用于承接「{section_title}」的核心任务，"
                "至少要说清对象、条件、操作和自查标准，避免只停留在标题式概念。"
            )
        repaired = f"{repaired}\n{notes_line}".strip()
        repaired_slides.append(repaired)
    _log_ppt_pages_without_notes("修复后", section_title, repaired_slides)
    return "\n---\n".join(repaired_slides)


# ═══════════════════════════════════════
#  从 generate_ppt_parallel 里提出来的纯函数
# ═══════════════════════════════════════
#
# 它们原先嵌在那个 800 行的函数里，只能靠**真发一次模型调用**才覆盖得到。提出来的判据
# 是算出来的不是看出来的：这几个函数的自由变量只有内建名字（str/int/len/range/tuple），
# 没有任何外层变量，所以搬出来调用点一个字都不用改。

def _strip_framework(text: str) -> str:
    """剥离所有 markdown 框架标记，只保留正文文字"""
    t = text
    t = re.sub(r'\$\$[\s\S]*?\$\$', '', t)          # 块公式
    t = re.sub(r'\$[^$]*\$', '', t)                  # 行内公式
    t = re.sub(r'```[\s\S]*?```', '', t)             # 代码块
    t = re.sub(r'<!--[^>]*-->', '', t)               # HTML 注释（含 layout）
    t = re.sub(r'^#{1,4}\s+', '', t, flags=re.MULTILINE)  # 标题 #/##/###/####
    t = re.sub(r'^[-*+]\s+', '', t, flags=re.MULTILINE)   # 无序列表
    t = re.sub(r'^\d+[.)]\s+', '', t, flags=re.MULTILINE) # 有序列表
    t = re.sub(r'\*\*([^*]+)\*\*', r'\1', t)         # 加粗
    t = re.sub(r'\*([^*]+)\*', r'\1', t)             # 斜体
    t = re.sub(r'^>\s*', '', t, flags=re.MULTILINE)  # 引用
    t = re.sub(r'\|', ' ', t)                        # 表格竖线
    t = re.sub(r'^[-*_]{3,}\s*$', '', t, flags=re.MULTILINE)  # 分隔线
    t = re.sub(r'!?\[([^\]]*)\]\([^)]+\)', r'\1', t) # 链接/图片
    t = re.sub(r'`([^`]+)`', r'\1', t)               # 行内代码
    return t.strip()


def _limit_section_pages(
    content: str,
    section_title: str,
    max_pages: int = PPT_MAX_PAGES_PER_SECTION,
) -> str:
    """限制单个章节的幻灯片数量，避免模型忽略页数约束生成超长 PPT。"""
    slides = [
        slide.strip()
        for slide in re.split(r"\n\s*---+\s*\n", str(content or "").strip())
        if slide.strip()
    ]
    kept = slides if len(slides) <= max_pages else slides[:max_pages]
    if len(slides) > max_pages:
        logger.warning(
            "[PPT-Gen] 章节页数超限，截取前 %d 页 section=%s original_pages=%d",
            max_pages,
            section_title,
            len(slides),
        )
    missing = _log_ppt_pages_without_notes("限页后", section_title, kept)
    if missing:
        # **把那一刻的原文打出来**：这个分支在推理上不该出现（修复函数保证每页都有讲稿，
        # 而这里只是把同一份文本按同样的分隔符重切一遍）。既然它出现了，就别再猜 ——
        # 真相只在这段字符串里。
        logger.warning(
            "[PPT-讲稿] 证据 进页数=%d 出页数=%d max_pages=%d 长度=%d 传入开头=%r 无讲稿那页=%r",
            len(slides), len(kept), max_pages, len(str(content or "")),
            str(content or "")[:160], kept[missing[0] - 1][:200],
        )
    return "\n---\n".join(kept)


def _trim_section_context(
    full_portrait: str,
    full_lo: str,
    full_guidance: str,
    section_title: str,
    idx: int,
    total_sections: int,
) -> tuple[str, str, str]:
    """根据章节动态裁剪画像/学习目标/指导语，减少重复 token 注入

    首章（含引入页）返回完整内容，后续章节只保留章节定位等精简信息。
    非首章每章可节省约 1100 字 input token。

    Returns:
        (trimmed_portrait, trimmed_lo, trimmed_guidance)
    """
    if idx == 0:
        return full_portrait, full_lo, full_guidance

    # 后续章节：画像压缩为一行定位提示
    trimmed_portrait = (
        f"（用户画像要点见首章引入页。当前第{idx + 1}章「{section_title}」，请参考前文画像信息调整难度与侧重点。）"
        if full_portrait and full_portrait != "暂无画像数据"
        else ""
    )

    # 学习目标压缩为章节定位
    trimmed_lo = (
        f"本课程共{total_sections}章，当前第{idx + 1}章「{section_title}」。"
        f"整体学习目标见首章引入页，本节聚焦该章节核心知识点展开。"
        if full_lo and full_lo != "暂无学习目标数据"
        else ""
    )

    # 指导语截取核心要求（保留前120字）
    if full_guidance:
        trimmed_guidance = full_guidance[:120]
        if len(full_guidance) > 120:
            trimmed_guidance += "…（完整要求见首章）"
    else:
        trimmed_guidance = ""

    return trimmed_portrait, trimmed_lo, trimmed_guidance


def _iter_text_chunks(text: str, chunk_size: int = 12):
    for start in range(0, len(text), chunk_size):
        yield text[start:start + chunk_size]



#  从 generate_ppt_parallel 里提出来的纯函数
# ═══════════════════════════════════════
#
# 它们原先嵌在那个 800 行的函数里，只能靠**真发一次模型调用**才覆盖得到。提出来的判据
# 是算出来的不是看出来的：这几个函数的自由变量只有内建名字（str/int/len/range/tuple），
# 没有任何外层变量，所以搬出来调用点一个字都不用改。




async def generate_ppt_parallel(
    topic: str,
    portrait: str = "",
    kb: str = "",
    guidance: str = "",
    feedback: str = "",
    user_notes: str = "",
    custom_prompts: dict | None = None,
    sections: list[str] | None = None,
    stream_writer=None,
    section_count: int = PPT_DEFAULT_SECTIONS,
    ppt_prompt_key: str = "ppt",
    llm_priority: str = "high",
    user_id: int = 0,
    learning_objectives: str = "",
    skip_review_sections: bool = False,
    ppt_theme_id: str = "",
    rag_mode: str = "reference",
) -> str:
    """按章节并行生成 PPT：大纲（默认{section_count}章节） → N 条线并行（每条默认 1 页，复杂章节最多 2 页），并保留画像学习引入"""
    _t_total = time.perf_counter()
    _push_agent_event(stream_writer, "executor:ppt", "PPT生成智能体", "executor", "running", "正在启动 PPT 生成", resource_type="ppt")
    # 立即通知前端，避免长时间无反馈
    if stream_writer:
        try:
            stream_writer({"type": "stream_start", "file_type": "ppt"})
        except Exception:
            logger.exception("[PPT-Parallel] stream_start 推送异常")

    section_guidance_map: dict[str, str] = {}
    course_plan_text = ""

    if sections is None:
        if stream_writer:
            try:
                _push_agent_event(stream_writer, "executor:ppt", "PPT生成智能体", "executor", "running", "正在规划课程大纲", resource_type="ppt")
                stream_writer({"type": "stream_progress", "file_type": "ppt", "message": "正在规划课程大纲..."})
            except Exception:
                logger.exception("[PPT-Parallel] stream_progress 推送异常")
        outline_task = generate_ppt_outline(topic, kb=kb, guidance=guidance, count=section_count, llm_priority=llm_priority, user_id=user_id)
        formula_task = generate_formula_sheet(topic, kb=kb, guidance=guidance, llm_priority=llm_priority, user_id=user_id)
        outline_result, formula_sheet = await asyncio.gather(outline_task, formula_task)
        sections, section_guidance_map, course_plan_text = outline_result
        if not learning_objectives:
            learning_objectives = course_plan_text
        _push_agent_event(stream_writer, "executor:ppt", "PPT生成智能体", "executor", "running", f"大纲规划完成，共 {len(sections)} 章", resource_type="ppt", total=len(sections))
    else:
        formula_sheet = ""

    # 画像引入置顶（如果画像数据可用）
    has_portrait = portrait and portrait != "暂无画像数据"
    if has_portrait:
        sections = ["学习引入：从你的视角出发"] + list(sections)

    # 构建课程全景描述，让每个章节知道自己在哪里
    outline_lines = [f"第{i+1}章「{s}」" for i, s in enumerate(sections)]
    course_overview = "\n".join(outline_lines)




    def _normalize_ppt_content(raw: str, section_title: str) -> str:
        """兼容外部/结构化 PPT 生成器输出，统一转成现有 PPT Markdown。"""
        # 先丢思考段：一是不能把 `</think>` 交给学生，二是下面要靠开头的 `{`/`[` 认结构化输出，
        # 那截草稿挡在前面会让它认不出来。
        content, dropped = _drop_leaked_reasoning(raw)
        if dropped:
            logger.warning(
                "[PPT-讲稿] 正文里混进了模型的思考段（</think>），已丢弃之前 %d 字 section=%s",
                dropped, section_title,
            )
        content = content.strip()
        content = re.sub(r"^```(?:markdown|md)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
        if not content:
            return ""

        def _as_list(value):
            return value if isinstance(value, list) else []

        def _text(value) -> str:
            return str(value or "").strip()

        def _coerce_slide(item: dict, index: int) -> dict:
            blocks = item.get("blocks") if isinstance(item.get("blocks"), list) else []
            bullet_source = (
                item.get("bullets")
                or item.get("points")
                or item.get("items")
                or item.get("key_points")
                or []
            )
            bullets: list[str] = []
            for block in list(blocks) + _as_list(bullet_source):
                if isinstance(block, dict):
                    text = _text(block.get("text") or block.get("content") or block.get("value"))
                else:
                    text = _text(block)
                if text:
                    bullets.append(text)

            layout = _text(item.get("layout") or item.get("type"))
            layout_alias = {
                "process": "process_steps",
                "steps": "process_steps",
                "formula": "formula_focus",
                "compare": "comparison",
                "cards": "content_cards",
                "concept": "concept_visual",
            }
            layout = layout_alias.get(layout, layout)

            return {
                "index": index,
                "title": _text(item.get("title") or item.get("heading") or f"{section_title} {index + 1}"),
                "layout": layout,
                "theme": _text(item.get("theme") or ppt_theme_id),
                "bullets": bullets,
                "text": "\n".join(bullets) or _text(item.get("text") or item.get("content")),
                "notes": _text(item.get("notes") or item.get("speaker_notes")),
                "visual": item.get("visual") if isinstance(item.get("visual"), dict) else {},
            }

        if content[:1] in "{[":
            try:
                data = parse_llm_json(content)
                raw_slides = data if isinstance(data, list) else (
                    data.get("slides")
                    or data.get("pages")
                    or (data.get("deck") or {}).get("slides")
                    or []
                )
                slides = [
                    _coerce_slide(item, i)
                    for i, item in enumerate(raw_slides)
                    if isinstance(item, dict)
                ]
                if slides:
                    from backend.src.utils.slide_schema import slides_to_markdown
                    return _repair_ppt_content(slides_to_markdown(section_title, slides).strip(), section_title)
            except Exception:
                logger.debug("[PPT-Gen] 结构化输出归一化失败", exc_info=True)

        first_title = re.search(r"(?m)^\s{0,3}#{1,2}\s+\S+", content)
        if first_title and first_title.start() > 0:
            prefix = content[:first_title.start()].strip()
            if not prefix or re.search(r"^(好的|收到|以下|根据|这里是)", prefix):
                content = content[first_title.start():].strip()
        return _repair_ppt_content(content, section_title)


    def _fallback_ppt_section(section_title: str) -> str:
        safe_title = re.sub(r"[#<>`$]", "", section_title or topic).strip() or "核心知识点"
        return (
            f"## {safe_title}：核心概念梳理\n"
            "<!-- layout: content_cards -->\n"
            f"- 本页用于替代未通过质量审核的初稿，先围绕「{safe_title}」建立稳定的概念框架，避免错误公式、残缺推导或渲染标签进入学习材料。\n"
            f"- 学习时先确认本章节讨论的对象、条件和目标，再进入具体例子；这样可以把「{safe_title}」放回完整知识链条中理解。\n"
            "- 对公式密集内容，优先用小规模例子验证含义，再推广到一般情形；每一步都应说明变量来源、运算规则和适用前提。\n"
            "- 如果后续需要更精细的推导，可以重新生成本章节或改用文档资源承载长公式，避免在幻灯片里塞入过长表达式。\n"
            f"> 讲稿：本页先把「{safe_title}」放回完整学习链条中讲清楚。学习者需要先确认对象、条件和目标，再用一个最小例子验证概念含义；如果涉及公式，应优先检查变量来源和适用前提，而不是直接套用结论。\n"
            "\n---\n"
            f"## {safe_title}：应用检查清单\n"
            "<!-- layout: process_steps -->\n"
            "- 第一步：用一句话说清本章节概念解决什么问题，并列出至少两个关键词，检查自己是否只记住了符号而没有理解意义。\n"
            "- 第二步：选择一个最小例子进行手算或口头推演，重点观察每一步为什么成立，而不是直接跳到最后答案。\n"
            "- 第三步：对比常见错误做法，尤其关注符号位置、维度匹配、条件遗漏和把结论套用到不适用场景的问题。\n"
            "- 第四步：完成一道同类型练习后复述解题路径，确认能从题目信息推出所用方法，而不是依赖题目标题提示。\n"
            f"> 讲稿：这一页用于把「{safe_title}」转化成可执行的学习动作。不要只看自己能否记住定义，而要看能否说出使用条件、完成一个最小例子，并解释错误做法为什么不成立；能复述路径，才算真正掌握。\n"
        )









    total = len(sections)
    _results: list[dict] = [{} for _ in range(total)]
    # 审核分散在每个章节的协程里，日志一条条往外冒，单看每一行看不出全貌。
    # 收尾时汇总一行，让"审核阶段到底跑了什么、结果如何"在日志里可读。
    review_stats = {"reviewed": 0, "rejected": 0, "passed": 0, "fallback": 0}
    gen_sem = asyncio.Semaphore(max(1, total))
    review_sem = asyncio.Semaphore(2)
    soft_quick_reasons = {"missing_speaker_notes", "speaker_notes_too_long", "hollow_bullet_or_step", "too_sparse_visible_content"}
    first_pass_done = [False] * total
    first_pass_event = asyncio.Event()

    def _mark_first_pass_done(_idx: int):
        if 0 <= _idx < total and not first_pass_done[_idx]:
            first_pass_done[_idx] = True
            if all(first_pass_done):
                first_pass_event.set()

    def _slide_stream_meta(_idx: int, slide_idx: int, _section_title: str) -> dict:
        return {
            "file_type": "ppt",
            "section_idx": _idx,
            "slide_idx": slide_idx,
            "section_title": _section_title,
            "section_total": total,
        }


    def _push_section(_idx: int, _content: str, _section_title: str = ""):
        """将章节的幻灯片逐页推送给前端"""
        if stream_writer:
            try:
                for slide_idx, slide in enumerate(_content.split("\n---\n")):
                    slide = slide.strip()
                    if slide:
                        if slide.startswith("<!-- layout:"):
                            slide = slide.replace("\n# ", "\n## ", 1)
                        elif slide.startswith("# ") and not slide.startswith("## "):
                            slide = slide.replace("# ", "## ", 1)
                        meta = _slide_stream_meta(_idx, slide_idx, _section_title)
                        stream_writer({
                            "type": "stream_slide_start",
                            **meta,
                        })
                        cursor = 0
                        for delta in _iter_text_chunks(slide):
                            stream_writer({
                                "type": "stream_slide_delta",
                                "delta": delta,
                                "cursor": cursor,
                                **meta,
                            })
                            cursor += len(delta)
                        stream_writer({
                            "type": "stream_slide",
                            "content": slide,
                            **meta,
                        })
                        stream_writer({
                            "type": "stream_slide_done",
                            "content": slide,
                            **meta,
                        })
                done = sum(1 for r in _results if r.get("content"))
                stream_writer({
                    "type": "stream_progress",
                    "file_type": "ppt",
                    "message": f"已生成 {done}/{total} 章节",
                    "current": done,
                    "total": total,
                })
            except Exception:
                logger.exception("[PPT-Parallel] 章节 %d 推送异常", _idx)

    def _push_section_complete(_idx: int, _content: str, _section_title: str = ""):
        """Emit a final PPT section for downstream consumers such as video TTS."""
        if not stream_writer:
            return
        try:
            stream_writer({
                "type": "ppt_section_complete",
                "file_type": "ppt",
                "resource_type": "ppt",
                "section_idx": _idx,
                "section_title": _section_title,
                "section_total": total,
                "content": _content,
            })
        except Exception:
            logger.debug("[PPT-Parallel] 小节完成事件发送失败 idx=%s", _idx, exc_info=True)

    async def _review_ppt_section(content: str, section_title: str, format_checked: bool = False) -> dict:
        """调用 reviewer 审核单个章节，返回 {passed, score, feedback}

        Args:
            format_checked: 若 True，表示格式层（layout/分隔符/公式配对/禁用词/字数）
                已由 _quick_check_ppt 通过，reviewer 只需审核语义质量（prompt 更短）。
        """
        try:
            # 根据是否已做格式预检选择不同模板
            template_key = "agent/reviewer_ppt_semantic" if format_checked else "agent/reviewer_ppt"
            reviewer_prompt = load_prompt(template_key)
            prompt_text = fill_prompt(
                reviewer_prompt,
                content=content[:3000],
                topic=topic,
            )
            async with review_sem:
                response = await llm.ainvoke(prompt_text, priority=llm_priority, user_id=user_id, pool="reviewer")
            return _parse_review_response(response.content)
        except Exception as e:
            logger.exception("[PPT-Review] section=%s 审核异常", section_title)
            return {"passed": True, "score": 0, "feedback": f"审核异常: {e}"}

    async def _gen_section(idx: int, section_title: str) -> None:
        """单章节：先推首轮草稿，再给足 3 次 reviewer 语义审核机会。"""
        section_agent_id = f"executor:ppt:section-{idx}"
        _push_agent_event(
            stream_writer,
            section_agent_id,
            f"PPT第 {idx + 1} 章",
            "executor",
            "running",
            f"正在生成「{section_title}」",
            resource_type="ppt",
            current=idx + 1,
            total=total,
        )
        if stream_writer:
            try:
                stream_writer({
                    "type": "stream_progress", "file_type": "ppt",
                    "message": f"正在生成第 {idx + 1}/{total} 章「{section_title}」...",
                    "current": idx + 1, "total": total,
                })
            except Exception:
                logger.warning("已忽略异常 backend/src/ai_core/resource_ppt.py:751", exc_info=True)

        is_portrait_section = has_portrait and idx == 0

        # 根据章节位置动态裁剪上下文，减少重复 token 注入
        _eff_portrait, _eff_lo, _eff_guidance = _trim_section_context(
            portrait, learning_objectives, guidance,
            section_title, idx, total,
        )
        section_kb = kb
        if not is_portrait_section:
            try:
                section_kb_result = await kb_search(f"{topic} {section_title}", top_k=3, user_id=user_id)
                if section_kb_result and "暂无" not in str(section_kb_result) and "No knowledge" not in str(section_kb_result):
                    section_kb = (
                        f"【本章节知识库检索】\n{section_kb_result}\n\n"
                        f"【课程级知识库检索】\n{kb}"
                    )
            except Exception:
                logger.exception("[PPT-RAG] 小节知识检索失败 idx=%d section=%s", idx, section_title)

        base_prompt = build_resource_prompt(
            ppt_prompt_key, topic, portrait=_eff_portrait, kb=section_kb, guidance=_eff_guidance,
            feedback=feedback, user_notes=user_notes, custom_prompts=custom_prompts,
            section=section_title, learning_objectives=_eff_lo,
            formula_sheet=formula_sheet,
            ppt_theme_id=ppt_theme_id,
            rag_mode=rag_mode,
        )

        if is_portrait_section:
            parts: list[str] = []
            if guidance:
                parts.append(f"\n\n## 学习指导\n{guidance}")
            if kb:
                parts.append(f"\n\n## 知识库参考资料\n{kb}")
            if feedback:
                parts.append(f"\n\n## 额外反馈\n{feedback}")
            prompt_with_context = (
                f"你是一个贴心的学习导师。为课程「{topic}」撰写 1 页学习引入幻灯片；只有画像信息和课程预告无法在一页清晰承载时才增加第 2 页。"
                f"\n\n## 输出格式"
                f"\n直接输出 PPT Markdown，第一个字符必须是 #；如生成第 2 页，用 --- 分隔页面。默认只输出 1 页，每页 4-6 条要点，每条 50-90 字，整页可见正文不低于 320 字。"
                f"\n每页最后必须追加一行 `> 讲稿：...`，讲稿 120-220 个中文字符，用于补足课堂讲解和视频朗读。"
                f"\n\n## 第1页：为什么这门课对你很重要，以及你将学到什么"
                f"\n- 用画像中的具体信息（专业、年级等）解释这门课和你的关联"
                f"\n- 让你感受到'这课是为我准备的'"
                f"\n- 语气亲切自然，像导师在课前和学生面对面聊天"
                f"\n\n## 第2页（仅在需要时）：课程学习地图与收获"
                f"\n- 只有第一页无法同时清楚说明课程关联和学习收获时才输出本页"
                f"\n- 简要预告本课程涵盖的核心内容（参考课程全景，不要展开讲）"
                f"\n- 说明学完后你能收获什么，避免重复第一页"
                f"\n- 保持鼓励和温暖的语气"
                f"\n\n## 用户画像\n{portrait}"
                f"\n\n## 课程全景（供预告参考，不要展开讲）\n{course_overview}"
                f"{''.join(parts)}"
            )
        else:
            prompt_with_context = base_prompt

        section_plan = section_guidance_map.get(section_title, "")
        if section_plan:
            prompt_with_context += (
                f"\n\n## 本章节来自课程地图的下发规划（必须遵守）\n"
                f"{section_plan}\n"
                f"- 本章只讲规划中的核心任务，不要抢讲后续章节，也不要退回泛泛概念介绍。"
            )

        if ppt_theme_id:
            prompt_with_context += (
                f"\n\n## 用户选择的 PPT 模板\n"
                f"用户选择的 PPT 模板为：{ppt_theme_id}。\n"
                f"请生成适配该模板风格的 layout/theme/visual 元数据，并在每页标题后一行加入 `<!-- theme: {ppt_theme_id} -->`。"
            )

        # ── 生成 + 审核循环：第一轮先推草稿，等所有章节首轮完成后再进入 reviewer ──
        MAX_REVIEW_CHECKS = 3
        MAX_GENERATION_ROUNDS = MAX_REVIEW_CHECKS + 2
        content = ""
        review_feedback = ""
        final_passed = False
        draft_pushed = False
        review_checks = 0

        def _push_section_replace(_idx: int, _content: str, _title: str):
            """推送章节替换事件 + 新的幻灯片内容"""
            if stream_writer:
                try:
                    stream_writer({
                        "type": "stream_section_replace",
                        "file_type": "ppt",
                        "section_idx": _idx,
                        "section_title": _title,
                    })
                except Exception:
                    logger.warning("已忽略异常 backend/src/ai_core/resource_ppt.py:845", exc_info=True)
            _push_section(_idx, _content, _title)

        round_idx = 0
        # 上一轮是**哪一种**硬伤（只管格式快检）。见下面"连续两次就收手"那段。
        last_hard_reason: str | None = None
        while round_idx < MAX_GENERATION_ROUNDS and review_checks < MAX_REVIEW_CHECKS:
            is_first_round = (round_idx == 0)

            if stream_writer and not is_first_round:
                try:
                    _push_agent_event(
                        stream_writer,
                        section_agent_id,
                        f"PPT第 {idx + 1} 章",
                        "executor",
                        "retrying",
                        f"「{section_title}」审核未通过，正在重写",
                        resource_type="ppt",
                        current=idx + 1,
                        total=total,
                    )
                    stream_writer({
                        "type": "stream_progress", "file_type": "ppt",
                        "message": f"「{section_title}」审核未通过，正在修改...（第{round_idx + 1}轮）",
                        "current": idx + 1, "total": total,
                    })
                except Exception:
                    logger.warning("已忽略异常 backend/src/ai_core/resource_ppt.py:873", exc_info=True)

            # 拼接审核反馈到 prompt
            if not is_first_round and review_feedback:
                prompt_with_context = (
                    f"{prompt_with_context}\n\n"
                    f"## 上一轮审核未通过，请根据以下意见修改\n"
                    f"{review_feedback}\n\n"
                    f"请重新生成完整内容。"
                )

            # Step A: 生成（连接错误重试一次）
            t0 = time.perf_counter()
            gen_ok = False
            for attempt in range(2):
                try:
                    async with gen_sem:
                        async with _PPT_GLOBAL_GEN_SEM:
                            response = await llm.ainvoke(prompt_with_context, priority=llm_priority, user_id=user_id, pool="ppt")
                    content = _limit_section_pages(
                        _normalize_ppt_content(response.content, section_title),
                        section_title,
                    )
                    gen_ok = True
                    break
                except Exception as e:
                    elapsed = time.perf_counter() - t0
                    is_conn_error = "RemoteProtocolError" in type(e).__name__ or "ConnectError" in type(e).__name__ or "Timeout" in type(e).__name__ or "timeout" in str(e).lower() or "incomplete" in str(e).lower()
                    if attempt == 0 and is_conn_error:
                        logger.warning("[PPT-Gen] idx=%d section=%s 连接异常，重试中... err=%s", idx, section_title, str(e)[:120])
                        await asyncio.sleep(1.5)
                        continue
                    logger.exception("[PPT-Gen] idx=%d section=%s 生成失败 耗时=%.2fs", idx, section_title, elapsed)
                    fallback_content = _fallback_ppt_section(section_title)
                    _results[idx] = {"idx": idx, "content": fallback_content}
                    if is_first_round:
                        _mark_first_pass_done(idx)
                    _push_agent_event(
                        stream_writer,
                        section_agent_id,
                        f"PPT第 {idx + 1} 章",
                        "executor",
                        "done",
                        f"「{section_title}」使用兜底内容",
                        resource_type="ppt",
                        current=idx + 1,
                        total=total,
                    )
                    _push_section(idx, fallback_content, section_title)
                    _push_section_complete(idx, fallback_content, section_title)
                    return

            if not gen_ok:
                fallback_content = _fallback_ppt_section(section_title)
                _results[idx] = {"idx": idx, "content": fallback_content}
                if is_first_round:
                    _mark_first_pass_done(idx)
                _push_agent_event(
                    stream_writer,
                    section_agent_id,
                    f"PPT第 {idx + 1} 章",
                    "executor",
                    "done",
                    f"「{section_title}」使用兜底内容",
                    resource_type="ppt",
                    current=idx + 1,
                    total=total,
                )
                _push_section(idx, fallback_content, section_title)
                _push_section_complete(idx, fallback_content, section_title)
                return

            elapsed = time.perf_counter() - t0

            if skip_review_sections:
                _results[idx] = {"idx": idx, "content": content}
                if is_first_round:
                    _mark_first_pass_done(idx)
                _push_section(idx, content, section_title)
                _push_section_complete(idx, content, section_title)
                _push_agent_event(
                    stream_writer,
                    section_agent_id,
                    f"PPT第 {idx + 1} 章",
                    "executor",
                    "done",
                    f"「{section_title}」已生成",
                    resource_type="ppt",
                    current=idx + 1,
                    total=total,
                    elapsed_ms=int(elapsed * 1000),
                )
                return

            # Step B: 快检
            quick_ok = False
            quick_reason = ""
            if not is_portrait_section:
                quick_ok, quick_reason = _quick_check_ppt(content)
                logger.info("[PPT-Gen] idx=%d section=%s round=%d %s reason=%s 耗时=%.2fs",
                            idx, section_title, round_idx + 1, "快检通过" if quick_ok else "快检未通过", quick_reason or "-", elapsed)
            format_safe = quick_ok or quick_reason in soft_quick_reasons

            if is_first_round and format_safe and not draft_pushed:
                draft_pushed = True
                _results[idx] = {"idx": idx, "content": content, "draft": True}
                _push_section(idx, content, section_title)
            elif is_first_round and not format_safe and not is_portrait_section and not draft_pushed:
                fallback_draft = _fallback_ppt_section(section_title)
                draft_pushed = True
                _results[idx] = {"idx": idx, "content": fallback_draft, "draft": True}
                _push_section(idx, fallback_draft, section_title)

            # 画像引入页不走严格章节 reviewer，但仍只在生成完成后推送。
            if is_portrait_section:
                _results[idx] = {"idx": idx, "content": content}
                if is_first_round:
                    _mark_first_pass_done(idx)
                _push_section(idx, content, section_title)
                _push_agent_event(
                    stream_writer,
                    section_agent_id,
                    f"PPT第 {idx + 1} 章",
                    "executor",
                    "done",
                    f"「{section_title}」已生成",
                    resource_type="ppt",
                    current=idx + 1,
                    total=total,
                )
                _push_section_complete(idx, content, section_title)
                return

            if is_first_round:
                _mark_first_pass_done(idx)
                await first_pass_event.wait()

            if not format_safe:
                # **同一处机械硬伤连续拒两次就收手。**
                # 格式检查是机械的，反馈也是照着这条检查写的；第一次改不掉，后面几轮基本也
                # 改不掉 —— 而每多跑一轮就是一次完整生成（实测单次 9–40 秒）。实测有一节连生
                # 5 轮全被同一个理由拒掉（约 106 秒），最后照样走兜底：多出来的 3 轮是纯浪费。
                # 语义审核（reviewer）不走这条 —— 那是内容判断，多给几次机会是值得的。
                if quick_reason == last_hard_reason:
                    logger.warning(
                        "[PPT-Gen] idx=%d section=%s 同一格式问题（%s）连续两次没改好，停止重写直接兜底",
                        idx, section_title, quick_reason,
                    )
                    break
                last_hard_reason = quick_reason
                _push_agent_event(
                    stream_writer,
                    section_agent_id,
                    f"PPT第 {idx + 1} 章",
                    "reviewer",
                    "reviewing",
                    f"「{section_title}」格式快检未通过，准备重写",
                    resource_type="ppt",
                    current=idx + 1,
                    total=total,
                )
                review_result = {
                    "passed": False,
                    "score": 0,
                    "feedback": f"系统格式快检未通过（{quick_reason or 'format_error'}）：请输出完整 PPT Markdown，修复结构、公式闭合、空公式块、HTML/KaTeX 标签泄漏、省略占位、空要点或缺少 `> 讲稿：...` 的问题。每条要点冒号后必须有实质内容。",
                }
            else:
                # 真的送审了 —— 上面那个"连续同一硬伤"的计数从这里断开（必须相邻才算）。
                last_hard_reason = None
                review_checks += 1
                _push_agent_event(
                    stream_writer,
                    section_agent_id,
                    f"PPT第 {idx + 1} 章",
                    "reviewer",
                    "reviewing",
                    f"正在审核「{section_title}」（第 {review_checks}/{MAX_REVIEW_CHECKS} 次）",
                    resource_type="ppt",
                    current=idx + 1,
                    total=total,
                )
                review_result = await _review_ppt_section(content, section_title, format_checked=True)
                review_stats["reviewed"] += 1
            if review_result.get("passed"):
                final_passed = True
                review_stats["passed"] += 1
                _results[idx] = {"idx": idx, "content": content}
                if draft_pushed:
                    _push_section_replace(idx, content, section_title)
                else:
                    _push_section(idx, content, section_title)
                _push_section_complete(idx, content, section_title)
                _push_agent_event(
                    stream_writer,
                    section_agent_id,
                    f"PPT第 {idx + 1} 章",
                    "reviewer",
                    "done",
                    f"「{section_title}」审核通过",
                    resource_type="ppt",
                    current=idx + 1,
                    total=total,
                    score=review_result.get("score"),
                )
                logger.info("[PPT-Review] idx=%d section=%s round=%d 审核通过 score=%s",
                            idx, section_title, round_idx + 1, review_result.get("score"))
                break

            review_feedback = review_result.get("feedback", "")
            # 截断反馈防止多轮累积导致 prompt 膨胀
            if len(review_feedback) > 400:
                review_feedback = review_feedback[:400] + "…"
            review_stats["rejected"] += 1
            # 日志打完整的 400 字，不再二次截到 120 —— 这行日志的全部价值就在于说清
            # "到底哪里不对"，截断之后结论往往正好被切掉（实测会断在"建议根"这种地方）。
            logger.warning("[PPT-Review] idx=%d section=%s round=%d 审核未通过: %s",
                           idx, section_title, round_idx + 1, review_feedback)
            round_idx += 1

        if not final_passed and not is_portrait_section:
            review_stats["fallback"] += 1
            fallback_content = _fallback_ppt_section(section_title)
            _results[idx] = {"idx": idx, "content": fallback_content}
            if draft_pushed:
                _push_section_replace(idx, fallback_content, section_title)
            else:
                _push_section(idx, fallback_content, section_title)
            _push_section_complete(idx, fallback_content, section_title)
            logger.warning("[PPT-Review] idx=%d section=%s 达最大审核次数 %d/生成轮次 %d，使用安全兜底版本",
                           idx, section_title, review_checks, round_idx)
            _push_agent_event(
                stream_writer,
                section_agent_id,
                f"PPT第 {idx + 1} 章",
                "reviewer",
                "done",
                f"「{section_title}」使用兜底内容",
                resource_type="ppt",
                current=idx + 1,
                total=total,
            )

    # ── 所有章节同时启动（asyncio.gather 天然并行）──
    await asyncio.gather(*[_gen_section(i, s) for i, s in enumerate(sections)])
    logger.info("[PPT-Review] 审核汇总 章节=%d 送审=%d次 未通过=%d次 达标=%d章 兜底=%d章",
                total, review_stats["reviewed"], review_stats["rejected"],
                review_stats["passed"], review_stats["fallback"])
    _push_agent_event(stream_writer, "executor:ppt", "PPT生成智能体", "executor", "done", "PPT 内容生成完成", resource_type="ppt", current=total, total=total, elapsed_ms=int((time.perf_counter() - _t_total) * 1000))

    # ═══════════════════════════════════
    #  组装最终结果
    # ═══════════════════════════════════
    parts: list[str] = []
    for r in _results:
        for slide in (r.get("content", "") or "").split("\n---\n"):
            slide = slide.strip()
            if not slide:
                continue
            if slide.startswith("<!-- layout:"):
                slide = slide.replace("\n# ", "\n## ", 1)
            elif slide.startswith("# ") and not slide.startswith("## "):
                slide = slide.replace("# ", "## ", 1)
            parts.append(slide)

    if len(parts) > PPT_MAX_PAGES_PER_DECK:
        logger.warning(
            "[PPT-Parallel] 总页数超限，截取前 %d 页 original_pages=%d",
            PPT_MAX_PAGES_PER_DECK,
            len(parts),
        )
        parts = parts[:PPT_MAX_PAGES_PER_DECK]

    _log_ppt_pages_without_notes("拼装成册后", topic, parts)
    combined = "\n---\n".join(parts)
    logger.info("[PPT-Parallel] 章节生成完成 章节数=%d 总页数≈%d 耗时=%.1fs", len(sections), len(parts), time.perf_counter() - _t_total)

    logger.info("[PPT-Parallel] 完成 全程耗时=%.1fs", time.perf_counter() - _t_total)
    return combined
