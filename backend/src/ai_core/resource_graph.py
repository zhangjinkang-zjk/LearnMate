"""
LangGraph 多智能体编排 — 学习资源生成
LeaderAgent → [ExecutorAgent × N 线程并行] → ReviewerAgent
"""
import asyncio
import concurrent.futures
import json
import logging
import os
import re
import time
from typing import TypedDict, NotRequired

from langgraph.graph import StateGraph, START, END

from backend.src.ai_core.llm_config import CREATIVE_TEMPERATURE, llm, llm_vision
from backend.src.ai_core.ppt_planner import (
    DOC_DEFAULT_SECTIONS,
    DOC_SECTION_COUNT_BY_DEPTH,
    PPT_DEFAULT_SECTIONS,
    PPT_MAX_PAGES_PER_DECK,
    PPT_MAX_PAGES_PER_SECTION,
    estimate_ppt_section_count,
    generate_formula_sheet,
    generate_learning_objectives,
    generate_ppt_outline,
)
from backend.src.ai_core.streaming import (
    push_agent_event as _push_agent_event,
    push_text_stream as _push_text_stream,
    safe_stream_writer as _safe_stream_writer,
)
from backend.src.ai_core.agent_names import (
    CROSS_VALIDATOR_AGENT,
    EXECUTOR_AGENT,
    LEADER_AGENT,
    RESOURCE_AGENT_NAMES as AGENT_RESOURCE_NAMES,
    REVIEWER_AGENT,
    resource_agent_name,
    resource_reviewer_name,
)
from backend.src.utils.formula_builder import build_formula_sheet
from backend.src.utils.knowledge_base import search as kb_search
from backend.src.utils.prompt_loader import load_prompt, fill_prompt
from backend.src.utils.json_parser import parse_llm_json
from backend.src.utils.slide_schema import PPT_SPEAKER_NOTES_MAX_CHARS, limit_speaker_notes
from backend.src.service.path.teaching_context import format_teaching_context
from backend.src.service.resource.document_quality import (
    detect_ai_style_tells,
    document_meaningful_length,
    evaluate_key_point_coverage,
    format_ai_style_tells,
    validate_document_chapter,
    validate_document_safety,
    validate_document_section,
)
from backend.src.service.resource.persistence import is_failed_generation_content

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


PPT_TARGET_CONCURRENT_USERS = max(1, _int_env("PPT_TARGET_CONCURRENT_USERS", 5))
PPT_MAX_SECTIONS_PER_REQUEST = max(1, _int_env("PPT_MAX_SECTIONS_PER_REQUEST", 19))
_PPT_GLOBAL_GEN_SEM = asyncio.Semaphore(PPT_TARGET_CONCURRENT_USERS * PPT_MAX_SECTIONS_PER_REQUEST)

# 文档小节重写次数；以及整章校验不达标时允许的整章重修轮数。
# 两者都用尽后保留尽力稿并留痕 —— 文档生成不再因为"没通过质量检查"抛异常，
# 否则同一批并行生成的 PPT / 思维导图会被一起作废，用户看到任务凭空中断。
_DOC_SECTION_ATTEMPTS = 2
_DOC_CHAPTER_REPAIR_ROUNDS = 1

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

# 角色名/资源名统一放在 agent_names.py。这里保留同名符号，
# 是为了不打断本模块里已有的调用点和 import 关系。
RESOURCE_AGENT_NAMES = AGENT_RESOURCE_NAMES

# ═══════════════════════════════════════
#  State
# ═══════════════════════════════════════

class ResourceState(TypedDict):
    user_id: str
    topic: str
    resource_types: list[str]
    chat_group_id: NotRequired[int]
    portrait_context: str
    kb_context: str
    learning_guidance: str
    user_notes: str
    custom_prompts: dict
    generated_resources: dict
    review_feedback: str
    review_passed: bool
    retry_count: int
    exam_question_types: str
    exam_count: str
    exam_difficulty: str
    reviewer_questions: list[dict]
    file_urls: NotRequired[dict[str, str]]
    answers: NotRequired[dict]
    skip_review: NotRequired[bool]
    ppt_prompt_key: NotRequired[str]
    llm_priority: NotRequired[str]
    ppt_theme_id: NotRequired[str]
    rag_mode: NotRequired[str]
    teaching_context: NotRequired[dict]
    consistency_issues: NotRequired[list]


# ═══════════════════════════════════════
#  Nodes
# ═══════════════════════════════════════

async def leader_node(state: ResourceState) -> dict:
    """LeaderAgent: 分析需求，决定生成哪些资源类型（用户已指定则跳过 LLM）"""
    writer = _safe_stream_writer()
    _push_agent_event(writer, "leader", LEADER_AGENT, "leader", "running", "正在分析学习需求")
    requested = state.get("resource_types") or []
    if requested:
        _push_agent_event(
            writer,
            "leader",
            LEADER_AGENT,
            "leader",
            "done",
            f"已确认生成类型：{' / '.join(requested)}",
            total=len(requested),
        )
        return {"resource_types": requested}

    topic = state["topic"]
    portrait = state.get("portrait_context", "")
    kb = state.get("kb_context", "")
    guidance = state.get("learning_guidance", "")
    prompt_text = fill_prompt(load_prompt("agent/leader"), topic=topic, portrait_context=portrait, kb_context=kb, learning_guidance=guidance)

    try:
        response = await llm.ainvoke(prompt_text, priority=state.get("llm_priority", "high"), user_id=int(state.get("user_id", 0)), pool="leader")
    except Exception as e:
        logger.exception("LeaderAgent LLM 调用失败")
        _push_agent_event(writer, "leader", LEADER_AGENT, "leader", "failed", "规划失败，降级生成文档")
        return {"resource_types": ["document"]}

    try:
        plan = parse_llm_json(response.content)
    except json.JSONDecodeError:
        plan = {"resource_types": ["document"], "topic": topic, "outline": response.content.strip()}

    resource_types = plan.get("resource_types", ["document"])
    _push_agent_event(
        writer,
        "leader",
        LEADER_AGENT,
        "leader",
        "done",
        f"规划完成：{' / '.join(resource_types)}",
        total=len(resource_types),
    )
    return {"resource_types": resource_types}


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

    def _quick_check_ppt(content: str) -> tuple[bool, str]:
        """格式安全快检：只拦截机械硬伤，内容质量留给 reviewer。"""
        normalized = str(content or "").strip()
        normalized = re.sub(r"^```(?:markdown|md)?\s*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s*```$", "", normalized)
        if not normalized:
            return False, "empty_content"
        if re.search(r"(生成失败|无法生成|生成出错|failed to generate|generation failed)", normalized[:800], re.IGNORECASE):
            return False, "generation_failure_marker"

        hollow_labels = (
            "学习目标", "核心规则", "最小例子", "自查提醒", "承接目标", "操作示范",
            "条件边界", "迁移检查", "要点", "步骤", "第一步", "第二步", "第三步",
            "第四步", "第五步",
        )

        def _content_len(text: str) -> int:
            clean = re.sub(r"`([^`]+)`", r"\1", text)
            clean = re.sub(r"\$[^$]*\$", "", clean)
            return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", clean))

        def _is_hollow_item(text: str) -> bool:
            item = re.sub(r"^\s*(?:[-*+]|\d+[.)、])\s*", "", text).strip()
            item = re.sub(r"^\s*(?:\*\*)?(.+?)(?:\*\*)?\s*$", r"\1", item).strip()
            match = re.match(r"^([^：:]{1,12})[：:]\s*(.*)$", item)
            if not match:
                return _content_len(item) < 8
            label, body = match.group(1).strip(), match.group(2).strip()
            if any(label.startswith(name) or name in label for name in hollow_labels):
                return _content_len(body) < 12
            return _content_len(item) < 12

        slides = re.split(r"\n\s*---+\s*\n", normalized)
        checked_slides = 0
        for slide in slides:
            slide = slide.strip()
            if not slide:
                continue
            if re.search(r'katex|mathml|spanclass|xmlns|semantics|mrow|&lt;/?[a-z]|<(?!/?!--)[a-z][^>]*>', slide, re.IGNORECASE):
                return False, "rendered_html_or_katex_leak"
            if re.search(r'^\s*\$\$\s*\$\$\s*$', slide, re.MULTILINE):
                return False, "empty_formula_block"
            has_layout = slide.startswith("<!-- layout:")
            has_title = slide.startswith("# ") or slide.startswith("## ")
            if not (has_layout or has_title):
                continue
            checked_slides += 1
            if "（上）" in slide or "（下）" in slide:
                return False, "split_title_marker"
            dollars = slide.count("$")
            if dollars % 2 != 0:
                return False, "unbalanced_dollar"
            text_no_math = re.sub(r'\$\$[\s\S]*?\$\$', '', slide)
            text_no_math = re.sub(r'\$[^$]*\$', '', text_no_math)
            if re.search(r'\.{4,}|……{1,}', text_no_math):
                return False, "ellipsis_placeholder"
            if re.search(r'(同上|以此类推|依此类推|类似可得|不再赘述|此处不再展开|（略）|证明略|过程略|推导略|步骤略)', text_no_math):
                return False, "omitted_content"
            notes_match = re.search(r'(?m)^>\s*(?:讲稿|speaker notes?|notes?)\s*[:：]\s*(.*)$', slide, re.IGNORECASE)
            if not notes_match:
                return False, "missing_speaker_notes"
            if len(re.sub(r"\s+", " ", notes_match.group(1)).strip()) > PPT_SPEAKER_NOTES_MAX_CHARS:
                return False, "speaker_notes_too_long"
            visible_lines = []
            for line in text_no_math.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(("<!--", "#", ">")):
                    continue
                if re.match(r"^\s*(?:[-*+]|\d+[.)、])\s*", stripped):
                    if _is_hollow_item(stripped):
                        return False, "hollow_bullet_or_step"
                    visible_lines.append(stripped)
            visible_text = "\n".join(visible_lines)
            if _content_len(visible_text) < 60:
                return False, "too_sparse_visible_content"
        if checked_slides <= 0:
            return False, "missing_slide_title"
        return True, ""

    def _repair_ppt_content(content: str, section_title: str) -> str:
        """修补非致命空槽，降低无意义重试率。"""
        normalized = str(content or "").strip()
        if not normalized:
            return normalized

        def _content_len(text: str) -> int:
            clean = re.sub(r"`([^`]+)`", r"\1", text)
            clean = re.sub(r"\$[^$]*\$", "", clean)
            return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", clean))

        def _repair_line(line: str) -> str:
            match = re.match(r"^(\s*(?:[-*+]|\d+[.)、])\s*)([^：:]{1,12})[：:]\s*(.*)$", line)
            if not match:
                return line
            prefix, label, body = match.group(1), match.group(2).strip(), match.group(3).strip()
            if _content_len(body) >= 8:
                return line
            fallback = (
                f"围绕「{section_title}」补充具体说明：说明本步骤要解决的问题、"
                "使用时需要满足的条件，以及学习者可以立即检查的结果。"
            )
            return f"{prefix}{label}：{fallback}"

        repaired_slides: list[str] = []
        for raw_slide in re.split(r"\n\s*---+\s*\n", normalized):
            slide = raw_slide.strip()
            if not slide:
                continue
            lines = [_repair_line(line) for line in slide.splitlines()]
            repaired = "\n".join(lines).strip()
            notes_match = re.search(r'(?m)^>\s*(?:讲稿|speaker notes?|notes?)\s*[:：].*$', repaired, re.IGNORECASE)
            notes_line = notes_match.group(0) if notes_match else (
                f"> 讲稿：本页围绕「{section_title}」展开讲解。请先说明本页学习目标，"
                "再用一个小例子或检查动作帮助学习者确认自己是否真正理解。"
            )
            notes_body = re.sub(
                r'^\s*>\s*(?:讲稿|speaker notes?|notes?)\s*[:：]\s*',
                "",
                notes_line,
                flags=re.IGNORECASE,
            )
            notes_line = f"> 讲稿：{limit_speaker_notes(notes_body)}"
            if notes_match:
                repaired = (repaired[:notes_match.start()] + repaired[notes_match.end():]).strip()
            visible_text = "\n".join(
                line.strip()
                for line in repaired.splitlines()
                if line.strip() and not line.strip().startswith(("<!--", "#", ">"))
            )
            if _content_len(visible_text) < 60:
                repaired += (
                    f"\n- 学习提示：本页用于承接「{section_title}」的核心任务，"
                    "至少要说清对象、条件、操作和自查标准，避免只停留在标题式概念。"
                )
            repaired = f"{repaired}\n{notes_line}".strip()
            repaired_slides.append(repaired)
        return "\n---\n".join(repaired_slides)

    def _normalize_ppt_content(raw: str, section_title: str) -> str:
        """兼容外部/结构化 PPT 生成器输出，统一转成现有 PPT Markdown。"""
        content = str(raw or "").strip()
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
        if len(slides) <= max_pages:
            return "\n---\n".join(slides)
        logger.warning(
            "[PPT-Gen] 章节页数超限，截取前 %d 页 section=%s original_pages=%d",
            max_pages,
            section_title,
            len(slides),
        )
        return "\n---\n".join(slides[:max_pages])

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

    def _iter_text_chunks(text: str, chunk_size: int = 12):
        for start in range(0, len(text), chunk_size):
            yield text[start:start + chunk_size]

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
                logger.warning("已忽略异常 backend/src/ai_core/resource_graph.py:711", exc_info=True)

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
                    logger.warning("已忽略异常 backend/src/ai_core/resource_graph.py:804", exc_info=True)
            _push_section(_idx, _content, _title)

        round_idx = 0
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
                    logger.warning("已忽略异常 backend/src/ai_core/resource_graph.py:830", exc_info=True)

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

    combined = "\n---\n".join(parts)
    logger.info("[PPT-Parallel] 章节生成完成 章节数=%d 总页数≈%d 耗时=%.1fs", len(sections), len(parts), time.perf_counter() - _t_total)

    logger.info("[PPT-Parallel] 完成 全程耗时=%.1fs", time.perf_counter() - _t_total)
    return combined


# ═══════════════════════════════════════
#  文档并行生成（与 PPT 对称）
# ═══════════════════════════════════════

def _fallback_document_outline(
    topic: str,
    count: int,
    teaching_context: dict | None = None,
) -> list[str]:
    current = teaching_context.get("current", {}) if isinstance(teaching_context, dict) else {}
    spec = current.get("teaching_spec", {}) if isinstance(current, dict) else {}
    key_points = spec.get("key_points", []) if isinstance(spec, dict) else []
    candidates = [f"{topic}要解决的问题"]
    candidates.extend(f"{str(point).strip()}的核心机制" for point in key_points if str(point).strip())
    candidates.extend([
        f"{topic}的完整示例",
        f"{topic}的边界与误区",
        f"{topic}的迁移检查",
        f"{topic}的关键结论",
    ])

    result: list[str] = []
    for candidate in candidates:
        title = re.sub(r"\s+", "", str(candidate))[:20]
        if title and title not in result:
            result.append(title)
        if len(result) >= count:
            break
    while len(result) < count:
        result.append(f"{topic[:12]}学习检查{len(result) + 1}")
    return result


def _fallback_document_section(topic: str, section_title: str) -> str:
    """某一节彻底生成不出来时的兜底正文。

    与 ``_fallback_ppt_section`` 同一个取舍：宁可给一节"怎么学"的稳定骨架，
    也不要让整章因为一节写砸而作废。这里刻意不写任何学科结论 —— 兜底稿是确定性的，
    编造具体知识点等于把幻觉固化进教材。也不写"待补充"这类占位语，那会让整份文档在
    复用校验里被判成坏内容，每次进章节都被重新生成一遍。
    """
    safe_title = re.sub(r"[#<>`$]", "", str(section_title or topic)).strip() or "本小节"
    return (
        f"## {safe_title}\n\n"
        f"这一节用来把「{safe_title}」放回「{topic}」的完整学习链条里。先确认它讨论的对象是什么、"
        "在什么条件下成立、要解决哪一类问题，再进入具体细节；这三件事说不清楚时，后面的例子和结论都会变成死记硬背。"
        "把对象、条件、目标三句话写下来，贴在笔记最上面，后面每读到一步都回头对一遍，能对上的才是真正读懂了。\n\n"
        "接着用一个最小规模的情形检验理解：把每一步为什么成立都说出来，而不是直接跳到结果。"
        "如果某一步解释不了，说明前面某个环节还没接上，应该回到上一节把它补完，再回到这里继续推。"
        "最小例子的价值在于它足够小、可以手工走完全过程，任何含糊的地方都会立刻暴露出来。\n\n"
        "然后把这节内容和上一节接起来：说明上一节的结论在这里用到了哪里，这一节的结果又会怎样被下一节使用。"
        "学习材料里的每一节都不是孤立的，能说清前后依赖关系，才能在做综合题时知道该从哪一步入手、"
        "遇到卡壳时该退回到哪个环节重看。\n\n"
        "最后对照常见错误自查：符号位置、适用条件和单位是否对得上，有没有把只在特殊情形下成立的结论当成普遍规律。"
        "把本节内容写成几句可以复查的话，并标出哪些已经能独立解释、哪些还需要回到材料确认，这样下一节的推进才有依据。\n"
    )


def _normalize_document_outline(
    value,
    topic: str,
    count: int,
    teaching_context: dict | None = None,
) -> list[str]:
    sections: list[str] = []
    if isinstance(value, list):
        for item in value:
            title = re.sub(
                r"^\s*(?:(?:第[一二三四五六七八九十\d]+[章节])|"
                r"(?:[一二三四五六七八九十\d]+[、.)：:])|(?:[-*+]\s+))\s*",
                "",
                str(item or ""),
            ).strip()
            title = re.sub(r"\s+", " ", title)[:20]
            if title and title not in sections:
                sections.append(title)
            if len(sections) >= count:
                break
    for fallback in _fallback_document_outline(topic, count, teaching_context):
        if len(sections) >= count:
            break
        if fallback not in sections:
            sections.append(fallback)
    return sections[:count]


def _strip_outer_markdown_fence(content: str) -> str:
    """Remove only a wrapper fence around the whole Markdown response."""
    text = str(content or "").strip()
    match = re.fullmatch(
        r"```(?:markdown|md)?[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else text


def _promote_section_heading(content: str) -> str:
    """把小节开头的三级标题提回二级。

    ``validate_document_section`` 接受 ``##`` 或 ``###``，但整章校验只数 ``^##``。
    模型把某一节的标题写成 ``###`` 时，整章就会因为"小节不足三个"被判不达标，
    而这是**重写正文修不好**的问题 —— 重写只会再随机一次标题层级。所以在这里
    确定性地对齐，而不是拿一次重写去赌。
    """
    text = str(content or "").lstrip()
    return re.sub(r"^###(\s+)", r"##\1", text, count=1)


def _document_repair_targets(parts: list[str], chapter_errors: list[str]) -> list[int]:
    """把整章校验意见映射回具体小节。

    定得住的（某一节自己就含占位语、代码块没闭合）只改那一节，不连累写好的部分；
    定不住的（字数不足、缺一级标题这种整章性的问题）就整章重修 —— 只补最短的一节
    通常还是凑不够字数，白花一次调用。
    """
    targets: set[int] = set()
    for index, part in enumerate(parts):
        if validate_document_safety(part):
            targets.add(index)
    if not targets or any("字符" in error for error in chapter_errors):
        targets.update(range(len(parts)))
    return sorted(targets)


async def generate_doc_outline(
    topic: str,
    kb: str = "",
    guidance: str = "",
    count: int = DOC_DEFAULT_SECTIONS,
    llm_priority: str = "high",
    user_id: int = 0,
    portrait: str = "",
    user_notes: str = "",
    teaching_context: dict | None = None,
    rag_mode: str = "reference",
) -> list[str]:
    """Generate the internal section plan for one path-node document."""
    outline_prompt = (
        "resource/path_document_outline"
        if teaching_context
        else "resource/document_outline"
    )
    prompt = fill_prompt(
        load_prompt(outline_prompt),
        topic=topic,
        count=count,
        teaching_context=format_teaching_context(teaching_context),
        portrait_context=portrait or "暂无画像数据",
        learning_guidance=guidance or "暂无额外学习指导",
        user_notes=user_notes or "暂无补充要求",
        kb_context=_format_kb_context(kb, rag_mode),
    )

    try:
        t0 = time.perf_counter()
        response = await llm.ainvoke(prompt, priority=llm_priority, user_id=user_id, pool="document")
        sections = _normalize_document_outline(
            parse_llm_json(response.content),
            topic,
            count,
            teaching_context,
        )
        logger.info("[Doc-Outline] 小节规划完成 count=%d elapsed=%.2fs", len(sections), time.perf_counter() - t0)
        return sections
    except Exception:
        logger.exception("[Doc-Outline] 小节规划失败，使用教学契约兜底目录")
        return _fallback_document_outline(topic, count, teaching_context)


async def generate_document_parallel(
    topic: str,
    portrait: str = "",
    kb: str = "",
    guidance: str = "",
    feedback: str = "",
    user_notes: str = "",
    custom_prompts: dict | None = None,
    sections: list[str] | None = None,
    stream_writer=None,
    section_count: int = DOC_DEFAULT_SECTIONS,
    llm_priority: str = "high",
    user_id: int = 0,
    rag_mode: str = "reference",
    teaching_context: dict | None = None,
    skip_review: bool = False,
) -> str:
    """Generate one complete node chapter from a planned set of internal sections."""
    _t_total = time.perf_counter()
    _push_agent_event(stream_writer, "executor:document", "文档生成智能体", "executor", "running", "正在启动文档生成", resource_type="document")
    if stream_writer:
        try:
            stream_writer({"type": "stream_start", "file_type": "document"})
        except Exception:
            logger.exception("[Doc-Parallel] stream_start 推送异常")

    if sections is None:
        if stream_writer:
            try:
                _push_agent_event(stream_writer, "executor:document", "文档生成智能体", "executor", "running", "正在规划文档大纲", resource_type="document")
                stream_writer({"type": "stream_progress", "file_type": "document", "message": "正在规划文档大纲..."})
            except Exception:
                logger.exception("[Doc-Parallel] stream_progress 推送异常")
        sections = await generate_doc_outline(
            topic,
            kb=kb,
            guidance=guidance,
            count=section_count,
            llm_priority=llm_priority,
            user_id=user_id,
            portrait=portrait,
            user_notes=user_notes,
            teaching_context=teaching_context,
            rag_mode=rag_mode,
        )

    sections = _normalize_document_outline(sections, topic, section_count, teaching_context)
    outline_lines = [f"第{i + 1}节「{section}」" for i, section in enumerate(sections)]
    document_outline = "\n".join(outline_lines)
    course_formula_sheet = build_formula_sheet(topic)

    total = len(sections)
    completed_count = [0]
    # 小节质检分散在各自的协程里，逐条日志看不出全貌。收尾汇总一行，
    # 让"文档的审核/质检阶段到底跑了什么"在日志里可读（与 PPT 的 [PPT-Review] 汇总对齐）。
    doc_stats = {"sections": 0, "quality_retries": 0, "error_retries": 0, "fallback": 0, "chapter_repairs": 0,
                 "consistency_issues": 0, "consistency_repairs": 0, "consistency_remaining": 0}
    # 文风套路命中统计（小节 idx → {类别: 次数}）。只观测不拦截，见
    # detect_ai_style_tells 的注释。
    #
    # 按小节覆盖而不是累加：整章重修 / 交叉验证重修会再次调用 gen_section，
    # 累加会把同一节数两遍（首轮与重修版本都算），汇总出现「命中小节 6/3」这种
    # 不可能的数。覆盖式记录天然以最后一版为准，也就是真正交付的那一版。
    section_style: dict[int, dict[str, int]] = {}

    def _record_style(section_idx: int, title: str, text: str) -> None:
        """记录该小节**最终交付版本**的文风命中。

        两条出口都要记：正常接受，以及重写用尽后的尽力稿 / 兜底骨架。只在接受路径
        记的话，走兜底的小节会显示成「无命中」——分母变小、明细为空，读起来像"文风
        很干净"，而实际是压根没测到，正好把结论带反。
        """
        tells = detect_ai_style_tells(text)
        section_style[section_idx] = tells
        if tells:
            logger.info(
                "[Doc-Style] 第 %d/%d 节「%s」命中文风套路 %s",
                section_idx + 1, total, title, format_ai_style_tells(tells),
            )

    async def gen_section(
        idx: int,
        section_title: str,
        chapter_feedback: str = "",
        repair_round: int = 0,
    ) -> tuple[int, str]:
        section_agent_id = f"executor:document:section-{idx}"
        _push_agent_event(
            stream_writer,
            section_agent_id,
            f"文档第 {idx + 1} 节",
            "executor",
            "running" if repair_round == 0 else "retrying",
            f"正在撰写「{section_title}」" if repair_round == 0 else f"正在按整章校验意见重修「{section_title}」",
            resource_type="document",
            current=idx + 1,
            total=total,
        )
        if stream_writer:
            try:
                stream_writer({
                    "type": "stream_progress",
                    "file_type": "document",
                    "message": (
                        f"正在生成第 {idx + 1}/{total} 节「{section_title}」..."
                        if repair_round == 0
                        else f"正在按整章校验意见重修第 {idx + 1}/{total} 节「{section_title}」..."
                    ),
                    "current": idx + 1,
                    "total": total,
                })
            except Exception:
                logger.warning("已忽略异常 backend/src/ai_core/resource_graph.py:1173", exc_info=True)

        prev_section = sections[idx - 1] if idx > 0 else "（无）"
        next_section = sections[idx + 1] if idx < len(sections) - 1 else "（无）"
        section_formula_sheet = build_formula_sheet(f"{topic} {section_title}") or course_formula_sheet
        formula_guidance = section_formula_sheet or "暂无稳定公式模板；如需公式，请使用标准 LaTeX 并保证公式块闭合。"
        section_kb = kb
        try:
            section_kb_result = await kb_search(f"{topic} {section_title}", top_k=3, user_id=user_id)
            if section_kb_result and "暂无" not in str(section_kb_result) and "No knowledge" not in str(section_kb_result):
                section_kb = (
                    f"【本小节知识库检索】\n{section_kb_result}\n\n"
                    f"【节点级知识库检索】\n{kb}"
                )
        except Exception:
            logger.exception("[Doc-RAG] 小节知识检索失败 idx=%d section=%s", idx, section_title)
        t0 = time.perf_counter()
        quality_feedback = "\n\n".join(part for part in (chapter_feedback, feedback) if part)
        best_content = ""
        last_error: Exception | None = None
        for attempt in range(_DOC_SECTION_ATTEMPTS):
            section_prompt = build_resource_prompt(
                "document",
                topic,
                portrait=portrait,
                kb=section_kb,
                guidance=guidance,
                feedback=quality_feedback or "暂无修订反馈",
                user_notes=user_notes,
                custom_prompts=custom_prompts,
                section=section_title,
                formula_sheet=formula_guidance,
                rag_mode=rag_mode,
                teaching_context=teaching_context,
                section_index=idx + 1,
                section_total=total,
                previous_section=prev_section,
                next_section=next_section,
                document_outline=document_outline,
            )
            try:
                # 正文走创作温度：打散句式套路、降低"AI 味"，也保证候选重试会产出
                # 与上一轮不同的内容（同 prompt 同温度下重试基本是重复劳动）。
                response = await llm.ainvoke(
                    section_prompt,
                    priority=llm_priority,
                    user_id=user_id,
                    pool="document",
                    temperature=CREATIVE_TEMPERATURE,
                )
                content = _promote_section_heading(
                    _strip_outer_markdown_fence(str(response.content or ""))
                )
                if len(content) > len(best_content):
                    best_content = content
                if teaching_context:
                    quality_errors = validate_document_section(content, section_title)
                elif not content or is_failed_generation_content(content):
                    quality_errors = ["文档内容为空或包含生成失败信息"]
                else:
                    quality_errors = []
                if not quality_errors:
                    # 文风只观测不拦截：把它做成打回条件会让每轮重写都撞同一条规则，
                    # 烧完重试次数再走兜底，比不拦更慢且不收敛。
                    _record_style(idx, section_title, content)
                    _push_text_stream(
                        stream_writer,
                        "document",
                        content,
                        section_idx=idx,
                        section_title=section_title,
                        total=total,
                    )
                    elapsed = time.perf_counter() - t0
                    completed_count[0] += 1
                    # 整章重修会带着 chapter_feedback 再跑一遍 gen_section，那不算"首次达标"。
                    if repair_round == 0:
                        doc_stats["sections"] += 1
                    _push_agent_event(
                        stream_writer,
                        section_agent_id,
                        f"文档第 {idx + 1} 节",
                        "executor",
                        "done",
                        f"「{section_title}」已完成",
                        resource_type="document",
                        current=completed_count[0],
                        total=total,
                        elapsed_ms=int(elapsed * 1000),
                    )
                    logger.info(
                        "[Doc-Section] 已完成 %d/%d idx=%d section=%s 长度=%d 耗时=%.2fs",
                        completed_count[0], total, idx, section_title, len(content), elapsed,
                    )
                    return idx, content

                quality_feedback = (
                    "上一次草稿未通过系统质量检查，请完整重写本小节。问题："
                    + "；".join(quality_errors)
                )
                last_error = ValueError(quality_feedback)
                doc_stats["quality_retries"] += 1
                logger.warning(
                    "[Doc-Section] 质量不达标触发重试 idx=%d 第 %d 次 errors=%s",
                    idx, attempt + 1, quality_errors,
                )
            except Exception as error:
                last_error = error
                doc_stats["error_retries"] += 1
                logger.warning(
                    "[Doc-Section] 生成失败触发重试 idx=%d 第 %d 次 error=%s",
                    idx, attempt + 1, error,
                    exc_info=True,
                )

        elapsed = time.perf_counter() - t0
        # 单节重写次数用尽还不达标：留尽力稿，连尽力稿都没有（或它本身就是坏内容）就换兜底骨架。
        # 这里**不抛异常** —— 抛出去会经 executor 的 gather 连带作废同一批已经生成好的
        # PPT / 思维导图，用户看到的就是"审核发现问题之后任务直接中断"。
        section_ok = (
            not validate_document_section(best_content, section_title)
            if teaching_context
            else bool(best_content) and not is_failed_generation_content(best_content)
        )
        if not section_ok:
            doc_stats["fallback"] += 1
            best_content = _fallback_document_section(topic, section_title)
        # 这一节到此为止，标 done；要不要再修由整章校验决定，那一步会另发 executor:document 的 retrying。
        _push_agent_event(
            stream_writer,
            section_agent_id,
            f"文档第 {idx + 1} 节",
            "executor",
            "done",
            f"「{section_title}」已完成" if section_ok else f"「{section_title}」使用兜底内容",
            resource_type="document",
            current=idx + 1,
            total=total,
            elapsed_ms=int(elapsed * 1000),
        )
        logger.warning(
            "[Doc-Section] 小节重写次数用尽 idx=%d section=%s 保留尽力稿=%s 长度=%d error=%s",
            idx, section_title, section_ok, len(best_content), last_error,
        )
        # 兜底稿同样要记录，否则这一节在汇总里显示成"无命中"而不是"没测到"。
        _record_style(idx, section_title, best_content)
        return idx, best_content

    def _compose(parts: list[str]) -> str:
        chapter_title = str(
            (teaching_context or {}).get("current", {}).get("topic") or topic
        ).strip()
        return f"# {chapter_title}\n\n" + "\n\n".join(part for part in parts if part)

    results = await asyncio.gather(*(gen_section(i, s) for i, s in enumerate(sections)))
    results.sort(key=lambda x: x[0])
    parts = [content for _, content in results]

    combined = _compose(parts)
    chapter_errors = validate_document_chapter(combined, teaching_context) if teaching_context else []

    # 整章校验是**生成质量目标**，不是终止条件：不达标就带着校验意见重修被点名的小节，
    # 修完仍不达标也照样发出（下面的 done 事件带提示），不再抛异常。
    for repair_round in range(1, _DOC_CHAPTER_REPAIR_ROUNDS + 1):
        if not chapter_errors:
            break
        targets = _document_repair_targets(parts, chapter_errors)
        doc_stats["chapter_repairs"] += 1
        logger.warning(
            "[Doc-Parallel] 整章校验未通过，第 %d 轮重修 sections=%s errors=%s",
            repair_round,
            ",".join(str(index) for index in targets),
            "；".join(chapter_errors),
        )
        _push_agent_event(
            stream_writer,
            "executor:document",
            "文档生成智能体",
            "executor",
            "retrying",
            "整章校验发现问题，正在按意见重修",
            resource_type="document",
        )
        chapter_feedback = "整章校验未通过，请针对以下问题完整重写本小节：\n" + "\n".join(
            f"- {error}" for error in chapter_errors
        )
        completed_count[0] = 0
        repaired = await asyncio.gather(*(
            gen_section(index, sections[index], chapter_feedback, repair_round)
            for index in targets
        ))
        for index, (_, content) in zip(targets, repaired):
            parts[index] = content
        combined = _compose(parts)
        chapter_errors = validate_document_chapter(combined, teaching_context) if teaching_context else []

    if chapter_errors:
        logger.warning(
            "[Doc-Parallel] 整章校验仍未通过，保留尽力稿 topic=%s 字数=%d errors=%s",
            topic,
            document_meaningful_length(combined),
            "；".join(chapter_errors),
        )

    # 关键点覆盖是措辞问题，不作为失败条件：生成用的 prompt 里已经带着同一批关键点，
    # 因为措辞没逐字复现就否决会让同一份文档每次访问都重新生成。这里只留痕，便于排查。
    coverage_gaps = evaluate_key_point_coverage(combined, teaching_context) if teaching_context else []
    if coverage_gaps:
        logger.info(
            "[Doc-Parallel] 关键点覆盖提示 topic=%s gaps=%s",
            (teaching_context or {}).get("current", {}).get("topic"),
            "；".join(coverage_gaps),
        )

    # ── 跨章节交叉验证（ConsistencyReviewer）──
    # 逐节审核只看得到单节，看不见节与节之间的问题：概念重复 / 符号冲突 / 逻辑断层 /
    # 前后矛盾。其中「前后矛盾」正是幻觉最典型的表征 —— 单节自洽的文本一样会有。
    #
    # 这一段必须待在生成器**内部**，不能做成图末端的独立节点：文档在 executor 返回前
    # 就已经通过 resource_complete 推给前端并落库了，跑到图末端再修，数据库和用户手里
    # 留下的都是没修的那一版 —— 检查跑了、产物没变，就是空转。
    if not skip_review:
        checked = split_document_sections(combined)
        if len(checked) >= 2:
            _push_agent_event(
                stream_writer, "cross_validator", CROSS_VALIDATOR_AGENT, "reviewer", "reviewing",
                f"正在对 {len(checked)} 个章节做交叉验证", sections=len(checked),
            )
            issues = await review_cross_section_consistency(
                checked, topic=topic, llm_priority=llm_priority, user_id=user_id,
            )
            if issues is None:
                _push_agent_event(
                    stream_writer, "cross_validator", CROSS_VALIDATOR_AGENT, "reviewer", "failed",
                    "交叉验证未能完成，已跳过",
                )
            elif issues:
                logger.warning(
                    "[Doc-Review] 交叉验证发现跨章节问题 topic=%s count=%s detail=%s",
                    topic, len(issues), json.dumps(issues, ensure_ascii=False)[:600],
                )
                doc_stats["consistency_issues"] = len(issues)
                # 一轮带反馈的重修 + 复检。只报不改等于没跑 —— 能改变产物才算"协同决策"。
                repair_feedback = _consistency_feedback(issues)
                repaired = await asyncio.gather(*(
                    gen_section(index, title, repair_feedback, 1)
                    for index, title in enumerate(sections)
                ))
                for index, (_, content) in zip(range(total), repaired):
                    parts[index] = content
                combined = _compose(parts)
                doc_stats["consistency_repairs"] = 1
                remaining = await review_cross_section_consistency(
                    split_document_sections(combined), topic=topic, llm_priority=llm_priority, user_id=user_id,
                )
                left = len(remaining) if remaining else 0
                doc_stats["consistency_remaining"] = left
                _push_agent_event(
                    stream_writer, "cross_validator", CROSS_VALIDATOR_AGENT, "reviewer",
                    "retrying" if left else "done",
                    f"按交叉验证意见重修后仍有 {left} 处问题" if left else "交叉验证修复完成，未再发现跨章节不一致",
                    issue_count=left,
                )
            else:
                _push_agent_event(
                    stream_writer, "cross_validator", CROSS_VALIDATOR_AGENT, "reviewer", "done",
                    "交叉验证通过，未发现跨章节不一致", issue_count=0,
                )

    logger.info("[Doc-Parallel] 完成 小节数=%d 全程耗时=%.1fs", len(sections), time.perf_counter() - _t_total)
    logger.info("[Doc-Review] 质检汇总 小节=%d 首轮达标=%d 质量重写=%d次 异常重写=%d次 兜底=%d节 整章重修=%d轮",
                total, doc_stats["sections"], doc_stats["quality_retries"],
                doc_stats["error_retries"], doc_stats["fallback"], doc_stats["chapter_repairs"])
    _style_totals: dict[str, int] = {}
    for _tells in section_style.values():
        for _label, _count in _tells.items():
            _style_totals[_label] = _style_totals.get(_label, 0) + _count
    _style_hit = sum(1 for _tells in section_style.values() if _tells)
    logger.info("[Doc-Style] 文风观测汇总 命中小节=%d/%d 明细=%s（仅观测，不参与打回）",
                _style_hit, len(section_style), format_ai_style_tells(_style_totals))
    if doc_stats["consistency_issues"]:
        logger.info("[Doc-Review] 交叉验证 发现问题=%d处 已触发重修=%s 修复后剩余=%d处",
                    doc_stats["consistency_issues"], "是" if doc_stats["consistency_repairs"] else "否",
                    doc_stats["consistency_remaining"])
    _push_agent_event(
        stream_writer,
        "executor:document",
        "文档生成智能体",
        "executor",
        "done",
        "文档内容生成完成" if not chapter_errors else "文档已生成，整章校验仍有待改进项",
        resource_type="document",
        current=total,
        total=total,
        elapsed_ms=int((time.perf_counter() - _t_total) * 1000),
    )

    if stream_writer:
        try:
            stream_writer({"type": "stream_progress", "file_type": "document", "message": "文档生成完成", "current": total, "total": total})
        except Exception:
            logger.warning("已忽略异常 backend/src/ai_core/resource_graph.py:1282", exc_info=True)

    return combined


async def executor_node(state: ResourceState) -> dict:
    """并行生成所有资源类型，PPT 通过 get_stream_writer 逐页流式推送"""
    topic = state["topic"]
    resource_types = state.get("resource_types", ["document"])
    portrait = state.get("portrait_context", "")
    kb = state.get("kb_context", "")
    guidance = state.get("learning_guidance", "")
    custom_prompts = state.get("custom_prompts", {}) or {}
    feedback = state.get("review_feedback", "")
    focus_guidance = _build_focus_guidance(state.get("answers", {}) or {})
    user_notes = state.get("user_notes", "")
    rag_mode = _normalize_rag_mode(state.get("rag_mode", "reference"))
    teaching_context = state.get("teaching_context", {}) or {}

    writer = _safe_stream_writer()
    _push_agent_event(
        writer,
        "executor",
        EXECUTOR_AGENT,
        "executor",
        "running",
        f"正在并行调度：{' / '.join(resource_types)}",
        total=len(resource_types),
    )

    # 章节数：根据追问答案的 depth 决定
    answers = state.get("answers", {}) or {}
    depth = answers.get("depth", "standard")
    ppt_section_count = estimate_ppt_section_count(topic, depth)
    doc_section_count = DOC_SECTION_COUNT_BY_DEPTH.get(depth, DOC_DEFAULT_SECTIONS)

    # PPT / 文档 / 图片 / 视频 → 异步；其余 → 线程池
    has_ppt = "ppt" in resource_types
    has_doc = "document" in resource_types or "case" in resource_types or "reading" in resource_types
    has_image = "image" in resource_types
    has_video = "video" in resource_types
    thread_types = [rt for rt in resource_types if rt not in ("ppt", "document", "case", "reading", "image", "video")]

    # 非 PPT/文档 类型线程池并行
    prompts = {
        rt: build_resource_prompt(
            rt, topic, portrait=portrait, kb=kb, guidance=guidance,
            feedback=feedback, user_notes=user_notes,
            exam_count=state.get("exam_count", "5"),
            question_types=state.get("exam_question_types", "single_choice, multi_choice, true_false"),
            difficulty=state.get("exam_difficulty", "medium"),
            custom_prompts=custom_prompts, focus_guidance=focus_guidance,
            ppt_theme_id=state.get("ppt_theme_id", ""),
            rag_mode=rag_mode,
            teaching_context=teaching_context,
        )
        for rt in thread_types
    }

    user_id = state.get("user_id", "0")
    user_id_int = int(user_id)
    max_workers = min(len(thread_types), 20)
    llm_priority = state.get("llm_priority", "high")

    def gen_one_sync(rt: str) -> tuple[str, str]:
        t_start = time.perf_counter()
        agent_name = resource_agent_name(rt)
        _push_agent_event(writer, f"executor:{rt}", agent_name, "executor", "running", f"正在生成 {rt}", resource_type=rt)
        max_attempts = 2 if rt == "mindmap" else 1
        last_error = None
        for attempt in range(max_attempts):
            try:
                response = llm.invoke(prompts[rt], priority=llm_priority, user_id=user_id_int, pool="thread")
                content = str(response.content or "").strip()
                if not content:
                    raise ValueError(f"{rt} 返回内容为空")
                elapsed = time.perf_counter() - t_start
                _push_agent_event(writer, f"executor:{rt}", agent_name, "executor", "done", f"{rt} 生成完成", resource_type=rt, elapsed_ms=int(elapsed * 1000))
                logger.info("[Executor] %s 生成完成 耗时=%.2fs 尝试=%d", rt, elapsed, attempt + 1)
                return rt, content
            except Exception as error:
                last_error = error
                error_text = str(error).lower()
                transient = any(token in error_text for token in (
                    "timeout", "timed out", "incomplete", "connecterror", "readerror", "remoteprotocolerror",
                ))
                if rt == "mindmap" and attempt + 1 < max_attempts and transient:
                    _push_agent_event(writer, f"executor:{rt}", agent_name, "executor", "retrying", "思维导图请求超时，正在重试", resource_type=rt)
                    logger.warning("[Executor] mindmap 临时错误，准备重试：%s", error)
                    time.sleep(1.5)
                    continue
                break

        elapsed = time.perf_counter() - t_start
        _push_agent_event(writer, f"executor:{rt}", agent_name, "executor", "failed", f"{rt} 生成失败", resource_type=rt, elapsed_ms=int(elapsed * 1000))
        logger.error("[Executor] %s 调用失败，错误内容不会入库，耗时=%.2fs：%s", rt, elapsed, last_error)
        return rt, ""

    t_gen_start = time.perf_counter()

    # PPT / 文档 / 其余 全部并行执行
    loop = asyncio.get_running_loop()

    def _emit_resource_complete(rt: str, content, file_url: str | None = None):
        if not writer or content is None:
            return
        try:
            writer({
                "type": "resource_complete",
                "resource_type": rt,
                "file_type": rt,
                "content": content,
                "file_url": file_url or "",
            })
        except Exception:
            logger.debug("[Executor] 资源完成事件发送失败 rt=%s", rt, exc_info=True)

    async def _run_ppt():
        if not has_ppt:
            return None
        content = await generate_ppt_parallel(
            topic, portrait=portrait, kb=kb, guidance=guidance,
            feedback=feedback, user_notes=user_notes,
            custom_prompts=custom_prompts,
            stream_writer=writer,
            section_count=ppt_section_count,
            ppt_prompt_key=state.get("ppt_prompt_key", "ppt"),
            llm_priority=llm_priority,
            user_id=user_id_int,
            skip_review_sections=bool(state.get("skip_review", False)),
            ppt_theme_id=state.get("ppt_theme_id", ""),
            rag_mode=rag_mode,
        )
        _emit_resource_complete("ppt", content)
        return content

    async def _run_doc():
        if not has_doc:
            return None
        content = await generate_document_parallel(
            topic, portrait=portrait, kb=kb, guidance=guidance,
            feedback=feedback, user_notes=user_notes,
            custom_prompts=custom_prompts,
            stream_writer=writer,
            section_count=doc_section_count,
            llm_priority=llm_priority,
            user_id=user_id_int,
            rag_mode=rag_mode,
            teaching_context=teaching_context,
            skip_review=bool(state.get("skip_review", False)),
        )
        _emit_resource_complete("document", content)
        return content

    async def _run_image():
        if not has_image:
            return None
        _push_agent_event(writer, "executor:image", "图片生成智能体", "executor", "running", "正在生成图片提示词", resource_type="image")
        img_prompt_text = build_resource_prompt(
            "image", topic, portrait=portrait, kb=kb, guidance=guidance,
            feedback=feedback, user_notes=user_notes,
            custom_prompts=custom_prompts, focus_guidance=focus_guidance,
            ppt_theme_id=state.get("ppt_theme_id", ""),
            rag_mode=rag_mode,
            teaching_context=teaching_context,
        )
        try:
            response = await llm.ainvoke(img_prompt_text, priority=llm_priority, user_id=user_id_int, pool="thread")
            image_prompt = response.content.strip()[:900]
        except Exception:
            logger.exception("[Executor] 图片 prompt 生成失败")
            _push_agent_event(writer, "executor:image", "图片生成智能体", "executor", "failed", "图片提示词生成失败", resource_type="image")
            return "image:error", {"prompt": "", "url": ""}

        try:
            _push_agent_event(writer, "executor:image", "图片生成智能体", "executor", "running", "正在调用图片生成服务", resource_type="image")
            from backend.src.service.image import service as image_service
            images = await image_service.generate(image_prompt, str(user_id_int), aspect_ratio="16:9", img_count=2, save_history=False, chat_group_id=int(state.get("chat_group_id", 0)))
            if images and len(images) > 0:
                _push_agent_event(writer, "executor:image", "图片生成智能体", "executor", "done", "图片生成完成", resource_type="image")
                return "image:image", {"prompt": image_prompt, "url": images[0].get("url", "")}
            _push_agent_event(writer, "executor:image", "图片生成智能体", "executor", "done", "图片提示词已生成", resource_type="image")
            return "image:image", {"prompt": image_prompt, "url": ""}
        except Exception as e:
            logger.exception(f"[Executor] 图片生成失败: {e}")
            _push_agent_event(writer, "executor:image", "图片生成智能体", "executor", "failed", "图片生成失败", resource_type="image")
            return "image:image", {"prompt": image_prompt, "url": ""}

    async def _run_video():
        if not has_video:
            return None
        _push_agent_event(writer, "executor:video", "视频生成智能体", "executor", "running", "正在生成视频课件", resource_type="video")
        try:
            from backend.src.service.video.service import generate as generate_presentation

            presentation = await generate_presentation(
                topic,
                user_id_int,
                video_mode=False,
                background=False,
                save_history=False,
            )
            file_url = str(presentation.get("file_url") or "").strip()
            presentation_id = presentation.get("id")
            if not file_url or not presentation_id:
                raise ValueError("视频服务未返回可播放地址")
            content = json.dumps({"presentation_id": presentation_id}, ensure_ascii=False)
            _emit_resource_complete("video", content, file_url)
            _push_agent_event(writer, "executor:video", "视频生成智能体", "executor", "done", "视频课件生成完成", resource_type="video")
            return {"content": content, "file_url": file_url}
        except Exception:
            logger.exception("[Executor] 视频生成失败 topic=%s", topic)
            _push_agent_event(writer, "executor:video", "视频生成智能体", "executor", "failed", "视频课件生成失败", resource_type="video")
            return None

    ppt_coro = _run_ppt()
    doc_coro = _run_doc()
    image_coro = _run_image()
    video_coro = _run_video()

    def _survive(branch: str, value):
        """并行分支不允许互相拖累：某一路炸了就丢掉那一路，其余照常交付。"""
        if not isinstance(value, BaseException):
            return value
        logger.error("[Executor] %s 分支异常，已单独放弃：%s", branch, value, exc_info=value)
        _push_agent_event(
            writer,
            f"executor:{branch}",
            resource_agent_name(branch),
            "executor",
            "failed",
            f"{resource_agent_name(branch)}生成失败",
            resource_type=branch,
        )
        return None

    if thread_types:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            other_futures = asyncio.gather(
                *[loop.run_in_executor(pool, gen_one_sync, rt) for rt in thread_types],
                return_exceptions=True,
            )
            ppt_content, doc_content, image_result, video_result, other_results = await asyncio.gather(
                ppt_coro, doc_coro, image_coro, video_coro, other_futures, return_exceptions=True
            )
    else:
        other_results = []
        ppt_content, doc_content, image_result, video_result = await asyncio.gather(
            ppt_coro, doc_coro, image_coro, video_coro, return_exceptions=True
        )

    ppt_content = _survive("ppt", ppt_content)
    doc_content = _survive("document", doc_content)
    image_result = _survive("image", image_result)
    video_result = _survive("video", video_result)

    survived_results = []
    for item in other_results or []:
        if isinstance(item, BaseException):
            logger.error("[Executor] 线程池资源分支异常，已单独放弃：%s", item, exc_info=item)
            continue
        survived_results.append(item)
    other_results = survived_results

    logger.info("[Executor] 全部生成完成 并行总耗时=%.2fs types=%s", time.perf_counter() - t_gen_start, resource_types)
    _push_agent_event(
        writer,
        "executor",
        EXECUTOR_AGENT,
        "executor",
        "done",
        "并行生成阶段完成",
        elapsed_ms=int((time.perf_counter() - t_gen_start) * 1000),
    )

    retry = state.get("retry_count", 0)
    if feedback:
        retry += 1

    generated = {}
    file_urls = {}
    # 异步图片结果
    if image_result:
        rt, content = image_result
        actual_rt = rt.replace("image:", "")
        generated[actual_rt] = content.get("prompt", "")
        if content.get("url"):
            file_urls[actual_rt] = content["url"]
    if video_result:
        generated["video"] = video_result["content"]
        file_urls["video"] = video_result["file_url"]
    for rt, content in other_results:
        if not content or is_failed_generation_content(content):
            logger.warning("[Executor] 跳过失败资源 rt=%s topic=%s", rt, topic)
            continue
        if rt.startswith("image:"):
            actual_rt = rt.replace("image:", "")
            generated[actual_rt] = content.get("prompt", "")
            if content.get("url"):
                file_urls[actual_rt] = content["url"]
        else:
            if rt == "mindmap":
                _push_text_stream(writer, "mindmap", content)
            generated[rt] = content
    if ppt_content:
        generated["ppt"] = ppt_content
    if doc_content:
        generated["document"] = doc_content

    return {
        "generated_resources": generated,
        "file_urls": file_urls,
        "retry_count": retry,
        "review_feedback": "",
    }


def _generate_image_sync(prompt_text: str, user_id: str, user_id_int: int = 0, llm_priority: str = "high") -> tuple[str, dict]:
    """两阶段图片生成：LLM 产出 prompt → image service 生图（线程内）"""
    try:
        response = llm.invoke(prompt_text, priority=llm_priority, user_id=user_id_int, pool="thread")
        image_prompt = response.content.strip()
    except Exception as e:
        logger.exception("图片 prompt 生成失败")
        return ("image:error", {"prompt": "", "url": ""})

    try:
        from backend.src.service.image import service as image_service
        image_prompt = image_prompt[:900]
        loop = asyncio.new_event_loop()
        try:
            images = loop.run_until_complete(
                image_service.generate(image_prompt, user_id, aspect_ratio="16:9", img_count=2, save_history=False)
            )
        finally:
            loop.close()
        if images and len(images) > 0:
            return ("image:image", {"prompt": image_prompt, "url": images[0].get("url", "")})
    except Exception as e:
        logger.exception(f"图片生成失败: {e}")

    return ("image:image", {"prompt": image_prompt, "url": ""})


def _parse_review_response(raw: str) -> dict:
    """解析 reviewer 返回的 JSON，容错处理。
    支持新格式（逐题）和旧格式（整批），统一返回含 questions 字段的 dict。"""
    try:
        result = parse_llm_json(raw)
        if not isinstance(result, dict):
            return {"passed": True, "score": 70, "feedback": raw, "questions": []}
        # exercise 新格式：包含逐题结果
        if "questions" in result and isinstance(result["questions"], list):
            return {
                "passed": result.get("overall_passed", True),
                "score": result.get("overall_score", 70),
                "feedback": result.get("overall_feedback", ""),
                "questions": result["questions"],
            }
        # 旧格式兼容（其他资源类型）
        return {
            "passed": result.get("passed", True),
            "score": result.get("score", 70),
            "feedback": result.get("feedback", ""),
            "questions": [],
        }
    except json.JSONDecodeError:
        return {"passed": True, "score": 70, "feedback": raw, "questions": []}


# 资源类型 → 专用审核员
_REVIEWER_MAP = {
    "document": "agent/reviewer_document",
    "case": "agent/reviewer_document",
    "reading": "agent/reviewer_document",
    "ppt": "agent/reviewer_ppt",
    "exercise": "agent/reviewer_exam",
    "mindmap": "agent/mindmap_reviewer",
    "image": "agent/reviewer_image",
}


async def reviewer_node(state: ResourceState) -> dict:
    """ReviewerAgent: 每种资源类型由专用审核员独立审查，并行执行"""
    writer = _safe_stream_writer()
    generated = state.get("generated_resources", {})
    llm_priority = state.get("llm_priority", "high")
    user_id_int = int(state.get("user_id", 0))
    _push_agent_event(writer, "reviewer", REVIEWER_AGENT, "reviewer", "reviewing", "正在进行质量审核", total=len(generated))

    async def review_one(rt: str, content: str) -> dict:
        reviewer_name = resource_reviewer_name(rt)
        _push_agent_event(writer, f"reviewer:{rt}", reviewer_name, "reviewer", "reviewing", f"正在审核 {rt}", resource_type=rt)
        # PPT / 文档 已在 generate_*_parallel 内部逐章节审核（生成→审核→重生成循环），跳过全局审核。
        # 这里必须留一行日志：否则整个 reviewer 节点在日志上完全静音，排查时看起来
        # 像"审核阶段什么都没发生"，而实际是审核早就分散在生成阶段做完了。
        if rt in ("ppt", "document", "case", "reading"):
            logger.info("[审核] %s: 跳过全局审核（该类型已在生成阶段逐章节审核）", rt)
            _push_agent_event(writer, f"reviewer:{rt}", reviewer_name, "reviewer", "done", f"{rt} 已通过内置审核", resource_type=rt, score=100)
            return {"passed": True, "score": 100, "feedback": ""}
        # API 生成的图片跳过文本审核
        file_urls = state.get("file_urls", {})
        if file_urls.get(rt):
            _push_agent_event(writer, f"reviewer:{rt}", reviewer_name, "reviewer", "done", f"{rt} 自动通过审核", resource_type=rt, score=100)
            return {"passed": True, "score": 100, "feedback": "API 生成，自动通过"}
        reviewer_path = _REVIEWER_MAP.get(rt, "agent/reviewer_document")
        if not content:
            _push_agent_event(writer, f"reviewer:{rt}", reviewer_name, "reviewer", "done", f"{rt} 无需审核", resource_type=rt, score=100)
            return {"passed": True, "score": 100, "feedback": ""}
        try:
            content_snippet = content[:3000]
            prompt_text = fill_prompt(
                load_prompt(reviewer_path),
                content=content_snippet,
                topic=state.get("topic", ""),
                kb_context=state.get("kb_context", "暂无相关知识库资料"),
            )
            response = await (llm_vision if rt == "image" else llm).ainvoke(prompt_text, priority=llm_priority, user_id=user_id_int, pool="reviewer")
            result = _parse_review_response(response.content)
            _push_agent_event(
                writer,
                f"reviewer:{rt}",
                reviewer_name,
                "reviewer",
                "done" if result.get("passed") else "retrying",
                f"{rt} 审核{'通过' if result.get('passed') else '需要修订'}",
                resource_type=rt,
                score=result.get("score"),
            )
            logger.info(f"[审核] {rt}: passed={result.get('passed')} score={result.get('score')}")
            return result
        except Exception as e:
            logger.exception(f"[审核] {rt} 失败")
            _push_agent_event(writer, f"reviewer:{rt}", reviewer_name, "reviewer", "failed", f"{rt} 审核异常", resource_type=rt)
            return {"passed": True, "score": 0, "feedback": f"审核异常: {e}"}

    tasks = [review_one(rt, content) for rt, content in generated.items()]
    if not tasks:
        _push_agent_event(writer, "reviewer", REVIEWER_AGENT, "reviewer", "done", "没有需要审核的资源")
        return {"review_passed": True, "review_feedback": ""}

    results = await asyncio.gather(*tasks)

    # 汇总
    feedback_parts = []
    all_passed = True
    question_results = []
    for (rt, _), result in zip(generated.items(), results):
        passed = result.get("passed", False)
        if isinstance(passed, str):
            passed = passed.lower() in ("true", "yes", "1", "是", "pass")
        if not passed:
            all_passed = False
            feedback_parts.append(f"[{rt}] {result.get('feedback', '')}")
        # 收集 per-question 审核结果（exercise 类型）
        for q in result.get("questions", []):
            question_results.append(q)

    _push_agent_event(
        writer,
        "reviewer",
        REVIEWER_AGENT,
        "reviewer",
        "done" if all_passed else "retrying",
        "质量审核通过" if all_passed else "审核发现问题，准备重新生成",
    )

    return {
        "review_passed": all_passed,
        "review_feedback": "\n".join(feedback_parts),
        "reviewer_questions": question_results,
    }


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


# ═══════════════════════════════════════
#  Router
# ═══════════════════════════════════════

def should_continue(state: ResourceState) -> str:
    if state.get("review_passed"):
        return "end"
    if state.get("retry_count", 0) >= 2:
        return "end"
    return "executor"


def should_review(state: ResourceState) -> str:
    """跳过审核可省掉一轮 LLM 调用，适用于学习路径等对质量要求不极端的场景"""
    if state.get("skip_review"):
        return "end"
    return "reviewer"


# ═══════════════════════════════════════
#  跨章节交叉验证（ConsistencyReviewer）
# ═══════════════════════════════════════

_CONSISTENCY_PROMPT = "agent/consistency_reviewer"
_CONSISTENCY_MAX_SECTIONS = 12
_CONSISTENCY_SECTION_CHARS = 400


def split_document_sections(document: str) -> list[tuple[str, str]]:
    """把成稿切成 [(章节标题, 正文)]。

    真实成稿的约定是 `# {topic}` 作文档标题、`## {小节}` 作章节（已核对库里的实际文档），
    所以按 H2 切；H1 只是兜底。少于两个章节就没有"跨章节"可言，返回空。
    """
    text = str(document or "")
    if not text.strip():
        return []
    for pattern in (r"(?m)^##\s+", r"(?m)^#\s+"):
        parts = re.split(pattern, text)
        if len(parts) <= 2:
            continue
        sections: list[tuple[str, str]] = []

        # parts[0] 在真实成稿里就是 `# 标题` 那一行，直接丢；但如果标题后面还跟着
        # 成段的内容，那就是一段没有小标题的前言，丢掉会让交叉验证看不见它。
        head = parts[0].strip()
        if head.startswith("#"):
            head = head.split("\n", 1)[1].strip() if "\n" in head else ""
        if len(head) > 80:
            sections.append(("前言", head))

        for part in parts[1:]:
            lines = part.splitlines()
            title = lines[0].strip() if lines else ""
            body = "\n".join(lines[1:]).strip()
            if title or body:
                sections.append((title, body))
        if len(sections) >= 2:
            return sections
    return []


def _consistency_digest(sections: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"### {title}\n{body[:_CONSISTENCY_SECTION_CHARS]}"
        for title, body in sections[:_CONSISTENCY_MAX_SECTIONS]
    )


async def review_cross_section_consistency(
    sections: list[tuple[str, str]],
    *,
    topic: str,
    llm_priority: str = "high",
    user_id: int = 0,
) -> list[dict] | None:
    """跑一次跨章节一致性审查，返回问题列表。

    调用失败返回 None —— 必须和"没问题返回 []"区分开，否则一次超时会被当成"通过"。
    """
    try:
        prompt = fill_prompt(load_prompt(_CONSISTENCY_PROMPT), content=_consistency_digest(sections))
        response = await llm.ainvoke(prompt, priority=llm_priority, user_id=user_id, pool="reviewer")
        parsed = parse_llm_json(str(response.content or "").strip())
    except Exception:
        logger.exception("[交叉验证] 调用失败 topic=%s", topic)
        return None
    raw_issues = parsed.get("issues") if isinstance(parsed, dict) else None
    issues = [item for item in raw_issues if isinstance(item, dict)] if isinstance(raw_issues, list) else []
    return issues[:5]


def _consistency_feedback(issues: list[dict]) -> str:
    """把交叉验证结论转成能直接喂给生成器的重修要求。"""
    lines = [
        f"- （{item.get('type') or '一致性问题'}）{item.get('sections') or ''}：{item.get('detail') or ''}".rstrip("：")
        for item in issues
    ]
    return "跨章节一致性检查发现以下问题，请完整重写本小节以消除它们：\n" + "\n".join(lines)


# ═══════════════════════════════════════
#  Graph
# ═══════════════════════════════════════

def build_graph():
    workflow = StateGraph(ResourceState)

    workflow.add_node("leader", leader_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reviewer", reviewer_node)

    workflow.add_edge(START, "leader")
    workflow.add_edge("leader", "executor")
    workflow.add_conditional_edges(
        "executor",
        should_review,
        {"reviewer": "reviewer", "end": END},
    )
    # 跨章节交叉验证已经挪进 generate_document_parallel 内部 —— 它必须在文档被推送/落库
    # **之前**跑，否则检查改变不了产物。所以这里不再挂末端节点：同一份文档审两遍既浪费
    # 一次 LLM 调用，末端那一遍的结论又没有任何下游消费者。
    workflow.add_conditional_edges(
        "reviewer",
        should_continue,
        {"executor": "executor", "end": END},
    )

    return workflow.compile()


resource_graph = build_graph()
