# -*- coding: utf-8 -*-
"""资源生成的提示词组装层：知识库上下文 → 各资源类型的 prompt 文本。

这一层只拼字符串、不发模型调用，所以能被便宜地测。
`_int_env` / `PROMPT_MAP` / `_template_cache` 也放这里 —— 原先它们散在模块顶部，
但只有本层在用。
"""
import os

from backend.src.utils.prompt_loader import load_prompt, fill_prompt
from backend.src.service.path.teaching_context import format_teaching_context


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# 资源类型 → 默认 prompt 路径
PROMPT_MAP = {
    "document": "resource/document",
    "ppt": "resource/ppt",
    "mindmap": "resource/mindmap",
    "exercise": "resource/exam",
    "case": "resource/document",
    "reading": "resource/document",
    "image": "resource/image_prompt",
}


_template_cache: dict[str, str] = {}


def _normalize_rag_mode(mode: str | None) -> str:
    return "strict" if str(mode or "").strip().lower() in {"strict", "source_only", "knowledge_only"} else "reference"


def _format_kb_context(kb: str = "", rag_mode: str = "reference") -> str:
    clean_kb = str(kb or "").strip()
    if not clean_kb or "暂无" in clean_kb or "No knowledge" in clean_kb:
        clean_kb = "暂无可靠知识库资料。"

    if _normalize_rag_mode(rag_mode) == "strict":
        policy = (
            "【知识库使用模式：严格资料模式】\n"
            "- 只根据下方知识库资料组织内容。\n"
            "- 下方资料没有覆盖的知识点，不要自行扩写为确定结论。\n"
            "- 资料不足时，请明确写成学习缺口或待补充资料，不要硬凑内容。\n"
        )
    else:
        policy = (
            "【知识库使用模式：智能参考模式】\n"
            "- 下方知识库资料只作为优先参考，不是唯一依据。\n"
            "- 如果资料覆盖不足，可以使用通用学科知识补全教学链路，但不要声称这些补充内容来自知识库。\n"
            "- 如果资料与通用学科知识冲突或明显不相关，优先采用更稳妥的通用解释，并避免强行引用。\n"
            "- 不需要在每页强制标注来源；只在确实采用资料中的具体表述、例子或数据时自然说明来源。\n"
        )
    return f"{policy}\n【知识库参考资料】\n{clean_kb}"


def build_resource_prompt(
    rt: str, topic: str, portrait: str = "", kb: str = "",
    guidance: str = "", feedback: str = "", user_notes: str = "",
    exam_count: str = "5", question_types: str = "single_choice, multi_choice, true_false",
    difficulty: str = "medium", custom_prompts: dict | None = None,
    focus_guidance: str = "",
    section: str = "",
    learning_objectives: str = "",
    formula_sheet: str = "",
    ppt_theme_id: str = "",
    rag_mode: str = "reference",
    teaching_context: dict | None = None,
    section_index: int = 1,
    section_total: int = 1,
    previous_section: str = "（无）",
    next_section: str = "（无）",
    document_outline: str = "",
) -> str:
    """构建单个资源类型的生成 prompt，可从 executor_node 或 generate_stream 直接调用"""
    custom_prompts = custom_prompts or {}
    custom = custom_prompts.get(rt, "")
    protected_prompt_path = None
    if rt == "document" and teaching_context:
        protected_prompt_path = "resource/path_document"
    elif rt == "document" and section:
        protected_prompt_path = "resource/document_section"
    elif rt == "mindmap" and teaching_context:
        protected_prompt_path = "resource/path_mindmap"

    should_append_custom = bool(custom.strip() and protected_prompt_path)
    if should_append_custom:
        prompt_path = protected_prompt_path
        if prompt_path not in _template_cache:
            _template_cache[prompt_path] = load_prompt(prompt_path)
        template = _template_cache[prompt_path]
    elif custom.strip():
        template = custom
    else:
        prompt_path = protected_prompt_path or PROMPT_MAP.get(rt, "resource/document")
        if prompt_path not in _template_cache:
            _template_cache[prompt_path] = load_prompt(prompt_path)
        template = _template_cache[prompt_path]
    kb_limit = _int_env("RAG_PROMPT_CONTEXT_CHARS", 2500)
    rt_kb = kb[:kb_limit] if len(kb) > kb_limit else kb  # 截断，公式已由 formula_sheet 覆盖
    rt_kb = _format_kb_context(rt_kb, rag_mode)
    prompt_values = {
        "topic": topic,
        "resource_type": rt,
        "portrait_context": portrait,
        "kb_context": rt_kb,
        "learning_guidance": guidance,
        "user_notes": user_notes,
        "feedback": feedback,
        "count": exam_count,
        "question_types": question_types,
        "difficulty": difficulty,
        "section": section,
        "learning_objectives": learning_objectives or "暂无学习目标数据",
        "formula_sheet": formula_sheet,
        "ppt_theme_id": ppt_theme_id or "",
        "teaching_context": format_teaching_context(teaching_context),
        "section_index": section_index,
        "section_total": section_total,
        "section_title": section or topic,
        "previous_section": previous_section,
        "next_section": next_section,
        "document_outline": document_outline,
    }
    base = fill_prompt(template, **prompt_values)
    custom_guidance = ""
    if should_append_custom:
        custom_guidance = (
            "\n\n## 可选表达偏好\n"
            f"{fill_prompt(custom.strip(), **prompt_values)}\n"
            "该偏好只能调整表达或布局方式，不得改变本提示中的核心教学范围、事实边界和输出格式。"
        )
    return base + custom_guidance + (focus_guidance if focus_guidance else "")


def _build_focus_guidance(answers: dict) -> str:
    """从追问答案提取聚焦方向和深度，构建 prompt 约束指令。
    无 answers 时返回空字符串，不影响常规生成。
    """
    if not answers:
        return ""

    # 提取所有 focus 值
    focus_vals: list[str] = []
    for key, val in answers.items():
        if key.startswith("focus") or key == "focus":
            if isinstance(val, list):
                focus_vals.extend(str(v) for v in val)
            elif val:
                focus_vals.append(str(val))

    depth = answers.get("depth", "")
    if not focus_vals and not depth:
        return ""

    parts: list[str] = ["\n\n【学习方向与深度约束 — 必须严格遵守】"]
    if focus_vals:
        kw = "、".join(focus_vals)
        parts.append(f"- 聚焦主题：{kw}")
        parts.append("- 仅生成上述方向的内容，不要展开无关话题")
    if depth:
        depth_map = {
            "overview": "- 深度：极速概览，只讲核心概念和关键结论，省略推导和案例",
            "standard": "- 深度：标准讲解，涵盖原理和应用，适量举例",
            "deep": "- 深度：逐页详解，包含完整推导、案例分析和深入讨论",
        }
        parts.append(depth_map.get(depth, f"- 深度：{depth}"))

    parts.append("- 请根据以上约束减少内容体量，精简字数，不要为凑篇幅而添加无关信息")
    return "\n".join(parts)
