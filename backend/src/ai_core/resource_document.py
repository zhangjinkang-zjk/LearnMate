# -*- coding: utf-8 -*-
"""文档那条链：大纲 → 逐节并行生成 → 分节质检 → 整章重修 → 跨章节一致性。

`split_document_sections` 和 `_CONSISTENCY_*` 也住在这一层：交叉验证必须在文档**被推送、
被落库之前**跑，否则它的结论改变不了产物。所以它挂在 `generate_document_parallel` 内部，
而不是图的末端节点上（见 `resource_graph.build_graph` 里那段注释）。
"""
import asyncio
import json
import logging
import re
import time

from backend.src.ai_core.agent_names import CROSS_VALIDATOR_AGENT
from backend.src.ai_core.llm_config import CREATIVE_TEMPERATURE, llm
from backend.src.ai_core.ppt_planner import DOC_DEFAULT_SECTIONS
from backend.src.ai_core.streaming import (
    push_agent_event as _push_agent_event,
    push_text_stream as _push_text_stream,
)
from backend.src.utils.formula_builder import build_formula_sheet
from backend.src.utils.knowledge_base import search as kb_search
from backend.src.utils.prompt_loader import load_prompt, fill_prompt
from backend.src.utils.json_parser import parse_llm_json
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
from backend.src.ai_core.resource_prompts import build_resource_prompt, _format_kb_context


logger = logging.getLogger(__name__)


# 文档小节重写次数；以及整章校验不达标时允许的整章重修轮数。
# 两者都用尽后保留尽力稿并留痕 —— 文档生成不再因为"没通过质量检查"抛异常，
# 否则同一批并行生成的 PPT / 思维导图会被一起作废，用户看到任务凭空中断。
_DOC_SECTION_ATTEMPTS = 2


_DOC_CHAPTER_REPAIR_ROUNDS = 1


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
                logger.warning("已忽略异常 backend/src/ai_core/resource_document.py:333", exc_info=True)

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
            logger.warning("已忽略异常 backend/src/ai_core/resource_document.py:634", exc_info=True)

    return combined


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
