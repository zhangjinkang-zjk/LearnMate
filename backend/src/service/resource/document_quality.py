"""Deterministic safety checks for generated learning documents."""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from typing import Any


_FAILURE_LINE_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:[-*+]\s*)?"
    r"(?:生成失败|内容生成失败|generation failed|failed to generate)"
    r"\s*[。.!！]?\s*$"
)
_PLACEHOLDER_MARKER_RE = re.compile(
    r"(?i)^(?P<marker>TODO|TBD|待补充|此处补充|lorem ipsum)(?P<remainder>.*)$"
)
_PLACEHOLDER_ONLY_RE = re.compile(
    r"(?i)^(?:TODO|TBD|待补充|此处补充|lorem ipsum)\s*[。.!！…]*$"
)
_PLACEHOLDER_ACTION_RE = re.compile(
    r"(?i)^(?:请|需要|需|应当|应该|稍后|后续|之后|未来|再)?\s*"
    r"(?:补充|完善|填写|添加|插入|撰写|编写|生成|更新|替换|完成|扩展|核实|确认|"
    r"add|write|fill|complete|update|replace|insert|provide)"
)
_PLACEHOLDER_OBJECT_RE = re.compile(
    r"(?i)^(?:本节|本段|这里|此处)?\s*"
    r"(?:内容|示例|案例|说明|细节|数据|资料|引用|代码|图片|图表|章节|段落|答案|"
    r"content|example|details?|code|data)\s*[。.!！…]*$"
)
_PLACEHOLDER_SUFFIX_RE = re.compile(
    r"(?i)^(?:本节|本段|这里|此处)?\s*"
    r"(?:内容|示例|案例|说明|细节|数据|资料|引用|代码|图片|图表|章节|段落|答案)"
    r"\s*(?:仍|尚|还)?\s*(?:待补充|待完善|待填写)\s*[。.!！…]*$"
)
_EXPLANATION_PREFIX_RE = re.compile(
    r"(?i)^(?:是|表示|指|意味着|用于|可以|可用于|并非|不是|作为|与|和|"
    r"驱动|管理|状态|标记|实践|教程|入门|指南|模式|机制|方法|策略|"
    r"is\b|means?\b|refers?\b|represents?\b)"
)
_COURSE_TOPIC_RE = re.compile(
    r"(?:原理|方法|策略|实践|管理|教程|入门|指南|模式|机制|区别|比较|影响|分析|"
    r"设计|治理|工作流|开发|基础|进阶|含义|是什么|为什么|如何)"
)
_OMISSION_END_RE = re.compile(
    r"(?:依此类推|类似可得|不再赘述|过程略|步骤略)\s*[。.!！…]*$"
)
_FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
_MARKDOWN_PREFIX_RE = re.compile(
    r"^\s*(?:(?:>\s*)+)?(?:#{1,6}\s+|(?:[-*+]\s+)|(?:\d+[.)]\s+))?"
    r"(?:\[[ xX]\]\s*)?"
)
_MEANINGFUL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_MAX_PLACEHOLDER_LENGTH = 40

# 关键点覆盖是「建议性」度量：关键点是否命中取决于措辞，而生成用的 prompt 里
# 本来就带着同一批关键点，重生成不会让措辞更接近。所以它不用来否决文档，只用来提示。
# 词元拆分让复合关键点（括号注释、斜杠、顿号、并列连词）也能被比对。
_PARENTHETICAL_RE = re.compile(r"[（(]([^）)]*)[）)]")
_TERM_SPLIT_RE = re.compile(r"[/、·与和及]")
_GENERIC_SUFFIX_RE = re.compile(
    r"(作用|定义|本质|意义|原则|方法|机制|特点|优势|流程|步骤|区别|关系|影响|"
    r"思路|策略|原理|价值|边界|限制)$"
)
_COVERAGE_RATIO = 0.6


def _meaningful_length(content: str) -> int:
    return len(_MEANINGFUL_RE.findall(content or ""))


def _iter_non_code_lines(content: str) -> Iterator[str]:
    """Yield Markdown lines that are not part of fenced or indented code blocks."""
    fence_char = ""
    fence_length = 0
    for line in str(content or "").splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_char:
            if (
                fence_match
                and fence_match.group("fence")[0] == fence_char
                and len(fence_match.group("fence")) >= fence_length
            ):
                fence_char = ""
                fence_length = 0
            continue
        if fence_match:
            fence = fence_match.group("fence")
            fence_char = fence[0]
            fence_length = len(fence)
            continue
        if line.startswith("    ") or line.startswith("\t"):
            continue
        yield line


def _normalize_markdown_line(line: str) -> str:
    candidate = _MARKDOWN_PREFIX_RE.sub("", str(line or ""), count=1).strip()
    for marker in ("**", "__", "~~", "*", "_"):
        if candidate.startswith(marker) and candidate.endswith(marker):
            candidate = candidate[len(marker):-len(marker)].strip()
    return candidate


def _is_placeholder_line(line: str) -> bool:
    is_heading = bool(re.match(r"^\s*(?:(?:>\s*)+)?#{1,6}\s+", str(line or "")))
    candidate = _normalize_markdown_line(line)
    if not candidate or _meaningful_length(candidate) > _MAX_PLACEHOLDER_LENGTH:
        return False
    if _PLACEHOLDER_ONLY_RE.fullmatch(candidate):
        return True
    if _PLACEHOLDER_SUFFIX_RE.fullmatch(candidate):
        return True
    if _OMISSION_END_RE.search(candidate):
        return True

    marker_match = _PLACEHOLDER_MARKER_RE.match(candidate)
    if not marker_match:
        return False
    remainder = marker_match.group("remainder").strip()
    has_separator = bool(re.match(r"^[:：\-—]", remainder))
    remainder = re.sub(r"^[:：\-—]\s*", "", remainder).strip()
    remainder = remainder.strip("()[]{}（）【】").strip()
    if not remainder:
        return True
    if _EXPLANATION_PREFIX_RE.match(remainder):
        return False
    if _PLACEHOLDER_ACTION_RE.match(remainder):
        return True
    if _PLACEHOLDER_OBJECT_RE.fullmatch(remainder):
        return True
    if is_heading or _COURSE_TOPIC_RE.search(remainder):
        return False
    return has_separator


def _contains_placeholder_text(content: str) -> bool:
    return any(_is_placeholder_line(line) for line in _iter_non_code_lines(content))


def validate_document_section(content: str, section_title: str) -> list[str]:
    """Return hard failures that should trigger a section retry."""
    text = str(content or "").strip()
    errors: list[str] = []
    if not text:
        return ["小节内容为空"]
    if _FAILURE_LINE_RE.search(text):
        errors.append("包含生成失败占位正文")
    if _contains_placeholder_text(text):
        errors.append("包含省略或待补充占位语")
    if _meaningful_length(text) < 180:
        errors.append("小节有效内容不足 180 字符")
    if not re.search(r"(?m)^#{2,3}\s+\S+", text):
        errors.append("缺少 Markdown 小节标题")
    if text.count("```") % 2:
        errors.append("代码块未闭合")
    if section_title and section_title not in text[:160]:
        errors.append("小节标题与规划不一致")
    return errors


def _expected_key_points(teaching_context: dict | None) -> list[str]:
    if not isinstance(teaching_context, dict):
        return []
    current = teaching_context.get("current")
    if not isinstance(current, dict):
        return []
    spec = current.get("teaching_spec")
    if not isinstance(spec, dict):
        return []
    values = spec.get("key_points")
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()][:8]


def validate_document_chapter(
    content: str,
    teaching_context: dict | None = None,
) -> list[str]:
    """Reject structurally incomplete chapter-shaped documents.

    Only deterministic defects belong here.  Key-point coverage is wording
    dependent and lives in ``evaluate_key_point_coverage`` as an advisory
    signal, because a hard failure on it never converges.
    """
    text = str(content or "").strip()
    errors: list[str] = []
    if not text:
        return ["文档内容为空"]
    if _FAILURE_LINE_RE.search(text):
        errors.append("文档包含生成失败占位正文")
    if _contains_placeholder_text(text):
        errors.append("文档包含省略或待补充占位语")
    if text.count("```") % 2:
        errors.append("文档代码块未闭合")

    is_path_chapter = bool(teaching_context)
    minimum_length = 900 if is_path_chapter else 500
    if _meaningful_length(text) < minimum_length:
        errors.append(f"文档有效内容不足 {minimum_length} 字符")
    if is_path_chapter and not re.match(r"^#\s+\S+", text):
        errors.append("路径节点文档缺少一级章节标题")
    if is_path_chapter and len(re.findall(r"(?m)^##\s+\S+", text)) < 3:
        errors.append("路径节点文档至少需要三个完整小节")

    return errors


def _coverage_terms(key_point: str) -> list[str]:
    """Split one key point into independently matchable terms."""
    text = str(key_point or "").strip()
    if not text:
        return []

    candidates: list[str] = []
    for group in _PARENTHETICAL_RE.findall(text):
        candidates.extend(_TERM_SPLIT_RE.split(group))
    candidates.extend(_TERM_SPLIT_RE.split(_PARENTHETICAL_RE.sub("", text)))

    terms: list[str] = []
    for candidate in candidates:
        term = candidate.strip()
        if not term:
            continue
        # 关键点常写成「概念 + 泛指后缀」（如「虚拟环境作用」），正文只会写概念本身。
        # 后缀表以 $ 锚定，所以基词一定是原词的前缀；用基词「替换」而不是「追加」，
        # 否则分母被撑大（「虚拟环境」命中仍算 1/2）会把覆盖良好的文档误报成未覆盖。
        base = _GENERIC_SUFFIX_RE.sub("", term)
        canonical = base if len(base) >= 2 else term
        if canonical not in terms:
            terms.append(canonical)
    return terms


def evaluate_key_point_coverage(
    content: str,
    teaching_context: dict | None = None,
) -> list[str]:
    """Advisory only: key points the document does not appear to cover.

    This must never block generation or reuse.  Whether a key point shows up is
    a matter of wording, and the generating prompt already carries the same key
    points, so rejecting a document on this signal makes regeneration repeat
    forever instead of converging.  ``validate_document_chapter`` keeps the
    deterministic structural checks; this one only reports.
    """
    key_points = _expected_key_points(teaching_context)
    if not key_points:
        return []

    haystack = str(content or "").casefold()
    missed: list[str] = []
    for point in key_points:
        terms = _coverage_terms(point)
        if not terms:
            continue
        hits = sum(1 for term in terms if term.casefold() in haystack)
        if hits < max(1, math.ceil(len(terms) * _COVERAGE_RATIO)):
            missed.append(f"{point}（{hits}/{len(terms)}）")
    return missed
