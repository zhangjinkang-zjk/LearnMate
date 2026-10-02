"""
LangGraph 多智能体编排 — 学习资源生成
LeaderAgent → [ExecutorAgent × N 线程并行] → ReviewerAgent

这个文件只留**编排**：状态、三个节点、路由、建图。

两条生成链各自搬到了兄弟模块 —— 它们各自都有几百行，混在一起时这个文件有 2600 行，
改一次要在一屏装不下的跨度里来回找：

    resource_prompts.py   两条链共用的提示词组装（+ `_int_env` / `PROMPT_MAP`）
    resource_common.py    两边共用的小解析器
    resource_ppt.py       PPT：大纲 → 逐节生成 → 快检/修补 → 分节审核
    resource_document.py  文档：大纲 → 逐节生成 → 质检 → 整章重修 → 跨章节一致性

**这里不再转出（re-export）搬走的名字。** 谁要用就去新模块 import —— 转出会让
`monkeypatch.setattr(resource_graph, "llm", …)` 这类补丁看着成功、实际打空：
函数读的是自己模块的 `llm`，于是测试会去打真实接口（付费），而且不报错。
"""
import asyncio
import concurrent.futures
import json
import logging
import time
from typing import TypedDict, NotRequired

from langgraph.graph import StateGraph, START, END

from backend.src.ai_core.llm_config import llm, llm_vision
from backend.src.ai_core.ppt_planner import (
    DOC_DEFAULT_SECTIONS,
    DOC_SECTION_COUNT_BY_DEPTH,
    estimate_ppt_section_count,
)
from backend.src.ai_core.streaming import (
    push_agent_event as _push_agent_event,
    push_text_stream as _push_text_stream,
    safe_stream_writer as _safe_stream_writer,
)
from backend.src.ai_core.agent_names import (
    EXECUTOR_AGENT,
    LEADER_AGENT,
    RESOURCE_AGENT_NAMES as AGENT_RESOURCE_NAMES,
    REVIEWER_AGENT,
    resource_agent_name,
    resource_reviewer_name,
)
from backend.src.ai_core.resource_common import _parse_review_response
from backend.src.ai_core.resource_prompts import (
    _build_focus_guidance,
    _normalize_rag_mode,
    build_resource_prompt,
)
from backend.src.ai_core.resource_ppt import generate_ppt_parallel
from backend.src.ai_core.resource_document import generate_document_parallel
from backend.src.utils.prompt_loader import load_prompt, fill_prompt
from backend.src.utils.json_parser import parse_llm_json
from backend.src.service.resource.persistence import is_failed_generation_content


logger = logging.getLogger(__name__)


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
    review_failed_types: NotRequired[list[str]]
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


async def executor_node(state: ResourceState) -> dict:
    """并行生成所有资源类型，PPT 通过 get_stream_writer 逐页流式推送"""
    topic = state["topic"]
    resource_types = state.get("resource_types", ["document"])
    # 这一轮实际要生成哪些类型。首次生成=全部；重试轮=只有没通过全局审核的那些，
    # 其余沿用上一轮的结果（它们已经过了自己那条审核）。见 `_types_to_regenerate`。
    active_types = _types_to_regenerate(resource_types, state.get("review_failed_types"))
    active_set = set(active_types)
    previous_generated = state.get("generated_resources") or {}
    previous_urls = state.get("file_urls") or {}
    kept_generated = {rt: v for rt, v in previous_generated.items() if rt not in active_set}
    kept_urls = {rt: v for rt, v in previous_urls.items() if rt not in active_set}
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
        f"正在并行调度：{' / '.join(active_types)}",
        total=len(active_types),
    )

    # 章节数：根据追问答案的 depth 决定
    answers = state.get("answers", {}) or {}
    depth = answers.get("depth", "standard")
    ppt_section_count = estimate_ppt_section_count(topic, depth)
    doc_section_count = DOC_SECTION_COUNT_BY_DEPTH.get(depth, DOC_DEFAULT_SECTIONS)

    # PPT / 文档 / 图片 / 视频 → 异步；其余 → 线程池
    has_ppt = "ppt" in active_types
    has_doc = "document" in active_types or "case" in active_types or "reading" in active_types
    has_image = "image" in active_types
    has_video = "video" in active_types
    thread_types = [rt for rt in active_types if rt not in ("ppt", "document", "case", "reading", "image", "video")]

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

    logger.info("[Executor] 全部生成完成 并行总耗时=%.2fs types=%s", time.perf_counter() - t_gen_start, active_types)
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
        # 重试轮里没重做的类型沿用上一轮的结果 —— 它们已经过了自己那条审核。
        "generated_resources": {**kept_generated, **generated},
        "file_urls": {**kept_urls, **file_urls},
        "retry_count": retry,
        "review_feedback": "",
        "review_failed_types": [],
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
        return {"review_passed": True, "review_feedback": "", "review_failed_types": []}

    results = await asyncio.gather(*tasks)

    # 汇总
    feedback_parts = []
    all_passed = True
    question_results = []
    # 哪些类型没过 —— 重试时**只重做这些**（见 `_types_to_regenerate`）。
    failed_types: list[str] = []
    for (rt, _), result in zip(generated.items(), results):
        passed = result.get("passed", False)
        if isinstance(passed, str):
            passed = passed.lower() in ("true", "yes", "1", "是", "pass")
        if not passed:
            all_passed = False
            failed_types.append(rt)
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
        "review_failed_types": failed_types,
        "reviewer_questions": question_results,
    }


# ═══════════════════════════════════════
#  Router
# ═══════════════════════════════════════

def _types_to_regenerate(requested: list[str], failed_types: list[str] | None) -> list[str]:
    """重试轮里**只重做没通过全局审核的类型**。

    ## 为什么必须这样

    图是 `executor → reviewer →（没过就回 executor）`，重试粒度原本是**整张图**。
    但全局审核实际上只判了 mindmap / exercise 这类没有内置审核的类型 ——
    ppt / document / case / reading 在生成阶段已经逐章节审过，全局审核直接给
    `passed=True, score=100` 跳过（见 `reviewer_node`）。

    于是一个脑图不达标，会把**已经判过"通过"的文档和 PPT 一起重做**；而重做时它们
    又拿不到任何反馈（`review_feedback` 只喂给失败的那个类型），**等于原样重抽一遍**。
    实测第 2 轮就是这样：一次重试让整轮从 326 秒涨到 678 秒，其中文档和 PPT 那段是纯浪费。

    `failed_types` 为空（首次生成、或审核没报出类型）时保持旧行为：全量生成。
    """
    if not failed_types:
        return list(requested)
    failed = set(failed_types)
    selected = [rt for rt in requested if rt in failed]
    # 一个都没挑出来就退回全量 —— 宁可多花钱，不能什么都不生成。
    return selected or list(requested)


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
