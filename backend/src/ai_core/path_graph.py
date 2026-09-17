"""
LangGraph 多智能体编排 — 个性化学习路径生成
LeaderAgent(规划大纲) → ExecutorAgent(并行分组生成节点) → ReviewerAgent(审核)
"""
import asyncio
import json
import logging
import time
from typing import TypedDict, NotRequired

from langgraph.graph import StateGraph, START, END

from backend.src.ai_core.llm_config import llm
from backend.src.service.path.teaching_context import (
    PATH_DEFAULT_RESOURCE_TYPES,
    attach_teaching_specs,
)
from backend.src.service.path.difficulty import (
    clamp_difficulty_score,
    derive_difficulty_score,
)
from backend.src.utils.prompt_loader import load_prompt, fill_prompt
from backend.src.utils.json_parser import parse_llm_json

logger = logging.getLogger(__name__)

# 每组最多生成的节点数（并行分组）
_GROUP_SIZE = 4
# 每组一次 LLM 调用，而一次调用的首字延迟就是二十几到三十几秒 —— 波数直接决定学生等多久。
# 原来只给 2 路：20 个节点分 5 组要跑 3 波，光这一项就 2 分钟起，学生在前端那 5 分钟超时上
# 反复踩线（"确认画像之后迟迟进不去"）。
#
# 4 路是照每用户并发池定的：`llm_config._PER_USER["path"] = 8`，而入口路径生成和后台那条
# 「其余科目」的生成会同时跑，两边各占 4 路刚好用满，再高就会互相对撞（谁先排队看谁先到）。
_MAX_GROUP_CONCURRENCY = 4
_GROUP_RETRY_ATTEMPTS = 2
# 规划器重试次数。实测一次规划要 105-185 秒，所以这里只给两次 —— 再多用户等不起，
# 而一次重试已经足以吃掉"瞬时失败"这一类。
_LEADER_ATTEMPTS = 2


_COGNITIVE_LEVELS = ["记忆", "理解", "应用", "分析", "评价", "创造"]


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _outline_rejection_reason(raw) -> str:
    """`topic_outline` 被整份丢掉时，说清是**哪一种**丢法。

    原来这里只有一句"topic_outline 为空" —— 分不清"模型没给"、"字段名不对"、
    "给了字符串数组"、"topic 全是空的"。20 条路径里 11 条主题是模板货这件事，
    因此只能靠人肉查库才发现（见 `_normalize_topic_outline` 的注释）。
    """
    if raw is None:
        return "没有 topic_outline（调用失败，或返回里没有这个字段）"
    if not isinstance(raw, list):
        return f"topic_outline 不是数组（{type(raw).__name__}）"
    if not raw:
        return "topic_outline 是空数组"
    usable = [item for item in raw if isinstance(item, (dict, str))]
    if not usable:
        return f"{len(raw)} 项全是无法识别的类型"
    no_topic = [
        item
        for item in usable
        if isinstance(item, dict) and not str(item.get("topic") or item.get("title") or "").strip()
    ]
    if no_topic:
        return f"{len(no_topic)}/{len(raw)} 项没有 topic/title"
    return f"{len(raw)} 项的主题全部重复或为空"


def _normalize_topic_outline(raw, subject: str, node_count: int = 0) -> list[dict]:
    if not isinstance(raw, list):
        return []

    normalized: list[dict] = []
    seen: set[str] = set()
    total_nodes = max(len(raw), node_count, 1)
    for index, item in enumerate(raw, 1):
        if isinstance(item, str):
            # 模型有时直接给主题名数组。内容是能用的，别丢 —— 原来这一条会让整份大纲
            # 归零、然后整条路径的节点主题都换成本地模板。
            item = {"topic": item}
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or item.get("title") or "").strip()
        if not topic or topic in seen:
            continue
        seen.add(topic)
        level = str(item.get("cognitive_level") or _COGNITIVE_LEVELS[min(index - 1, len(_COGNITIVE_LEVELS) - 1)])
        key_points = item.get("key_points") if isinstance(item.get("key_points"), list) else [topic]
        prerequisite_topics = item.get("prerequisite_topics") if isinstance(item.get("prerequisite_topics"), list) else []
        difficulty_score = 1.0 if index == 1 else clamp_difficulty_score(item.get("difficulty_score"))
        if difficulty_score is None:
            difficulty_score = derive_difficulty_score(
                order_index=index,
                total_nodes=total_nodes,
                cognitive_level=level,
                module=str(item.get("module") or item.get("category") or subject),
                key_points_count=len(key_points),
                prerequisite_count=len(prerequisite_topics),
            )
        normalized.append({
            "topic": topic,
            "module": str(item.get("module") or item.get("category") or subject).strip(),
            "cognitive_level": level,
            "learning_goal": str(item.get("learning_goal") or f"理解并掌握{topic}").strip(),
            "prerequisite_topics": prerequisite_topics,
            "key_points": key_points,
            "micro_example": str(item.get("micro_example") or f"完成一个关于{topic}的小练习").strip(),
            "difficulty_score": difficulty_score,
        })
        if node_count and len(normalized) >= node_count:
            break
    return normalized


# 模板只有 12 条，而目标可以更高：循环到第二轮之后要换名字。
# 原来是直接 `templates[index % len(templates)]`，于是目标 18 时第 13-18 个节点
# 和第 1-6 个**同名** —— 实测 65 条路径里 10 条带着重复的节点主题（path 68 就是：
# 「LangChain 编排与服务部署：学习目标与知识地图」出现了两次）。
_FALLBACK_ROUND_SUFFIX = ("", "进阶", "拓展", "深化")


def _fallback_topic_outline(subject: str, node_count: int = 0) -> list[dict]:
    requested = _safe_int(node_count, 12) or 12
    target = max(8, min(18, requested))
    if requested > target:
        # 这是个一直存在但没人看见的天花板：规划器完全失败时最多只能给出 18 个节点，
        # 目标再高也没用。不记这条的话，"为什么加了目标数还是 18"又只能靠人肉查库。
        logger.warning(
            "[PathLeader] 兜底大纲封顶 %s 个节点（目标 %s），超出部分不会生成 subject=%s",
            target,
            requested,
            subject,
        )
    templates = [
        ("学习目标与知识地图", "概念奠基"),
        ("核心概念与基本术语", "概念奠基"),
        ("基础结构与表示方法", "概念奠基"),
        ("基本规则与操作流程", "方法操作"),
        ("典型方法一：基础应用", "方法操作"),
        ("典型方法二：组合应用", "方法操作"),
        ("关键例题与解题步骤", "案例应用"),
        ("常见错误与辨析", "误区辨析"),
        ("小型综合任务", "综合迁移"),
        ("阶段复盘与知识迁移", "综合迁移"),
        ("进阶应用场景", "案例应用"),
        ("最终综合练习", "综合迁移"),
    ]
    outline = []
    for index in range(target):
        name, module = templates[index % len(templates)]
        round_index = index // len(templates)
        if round_index:
            suffix = (
                _FALLBACK_ROUND_SUFFIX[round_index]
                if round_index < len(_FALLBACK_ROUND_SUFFIX)
                else f"第{round_index + 1}轮"
            )
            name = f"{name}（{suffix}）"
        topic = f"{subject}：{name}"
        outline.append({
            "topic": topic,
            "module": module,
            "cognitive_level": _COGNITIVE_LEVELS[min(index, len(_COGNITIVE_LEVELS) - 1)],
            "learning_goal": f"围绕「{subject}」掌握{name}，并能完成对应检查任务",
            "prerequisite_topics": [outline[-1]["topic"]] if outline else [],
            "key_points": [subject, name, module],
            "micro_example": f"用一个小例子检查「{name}」是否掌握",
            "difficulty_score": 1.0 if index == 0 else derive_difficulty_score(
                order_index=index + 1,
                total_nodes=target,
                cognitive_level=_COGNITIVE_LEVELS[min(index, len(_COGNITIVE_LEVELS) - 1)],
                module=module,
                key_points_count=3,
                prerequisite_count=1 if outline else 0,
            ),
        })
    return outline


def _fallback_group_nodes(group: list[dict], group_start: int) -> list[dict]:
    nodes: list[dict] = []
    for index, item in enumerate(group):
        order_index = group_start + index
        topic = str(item.get("topic") or f"学习节点 {order_index}").strip()
        key_points = item.get("key_points") if isinstance(item.get("key_points"), list) else [topic]
        nodes.append({
            "topic": topic,
            "order_index": order_index,
            "knowledge_tags": key_points[:5],
            "prerequisites": [group_start + index - 1] if order_index > 1 else [],
            "resource_types": list(PATH_DEFAULT_RESOURCE_TYPES),
            "quiz_config": {"count": 5, "threshold": 0.7},
            "description": str(item.get("learning_goal") or f"掌握{topic}的核心概念、典型应用和常见误区").strip(),
            "difficulty_score": 1.0 if order_index == 1 else clamp_difficulty_score(
                item.get("difficulty_score"),
                derive_difficulty_score(
                    order_index=order_index,
                    total_nodes=max(len(group), order_index),
                    cognitive_level=str(item.get("cognitive_level") or ""),
                    module=str(item.get("module") or ""),
                    key_points_count=len(key_points),
                    prerequisite_count=1 if order_index > 1 else 0,
                ),
            ),
        })
    return nodes


def _merge_with_fallback(group: list[dict], produced: list[dict], group_start: int) -> list[dict]:
    """把智能体给的节点和"计划里有、它没给"的那些 topic 的本地兜底节点合起来。

    补的是**大纲里本来就规划好的主题**，不是凭空编内容 —— 只是这些节点的详情走模板
    （和整组生成失败时的兜底是同一份）。只补齐、不删减，所以智能体给多了也不受影响。

    为什么不能只是"返回空才兜底"：提示词明确告诉它这一组是第 X 到第 Y 个、共几个，
    它少给几个（实测一组要 4 个只回 1 个）时返回的仍是合法列表，原来会被直接采纳 ——
    于是"建议节点数"就在这一步再被削一次，而且不留任何痕迹。
    """
    merged = [item for item in produced if isinstance(item, dict)]
    covered = {str(item.get("topic") or "").strip() for item in merged}
    for node in _fallback_group_nodes(group, group_start):
        if str(node.get("topic") or "").strip() not in covered:
            merged.append(node)
    merged.sort(key=lambda node: node.get("order_index", 0))
    return merged


async def _expand_topic_outline(
    outline: list[dict],
    subject: str,
    difficulty: str,
    target: int,
    state: dict,
) -> list[dict]:
    """大纲不足目标数时，再问规划器要差额。

    **不是塞 filler**：把已有的主题名给它，让它补出**不重复**的新主题，补出来的仍然
    过 `_normalize_topic_outline`，所以认知层级、难度分、前置关系都由同一套规则算。

    失败就按现有长度返回 —— 短一点也比卡死强，调用方会记下差额。
    """
    missing = target - len(outline)
    if missing <= 0 or not outline:
        return outline

    existing = json.dumps([str(item.get("topic") or "") for item in outline], ensure_ascii=False)
    prompt = (
        "你是课程架构师，正在为一条学习路径补全大纲。\n"
        f"学科：{subject}\n难度：{difficulty}\n"
        f"已有节点主题（不要重复、不要改写、不要复述）：{existing}\n"
        f"请再补 {missing} 个**新的**节点主题，延续从基础到综合的递进，"
        "与已有主题不重复、不重叠，每个都是可独立学习的知识领域。\n"
        "严格只输出 JSON，不要解释、不要 markdown 代码块："
        '{"topic_outline":[{"topic":"...","module":"...","cognitive_level":"理解",'
        '"learning_goal":"...","key_points":["..."],"micro_example":"..."}]}'
    )
    user_id_int = _safe_int(state.get("user_id"), 0)
    llm_priority = state.get("llm_priority", "high")
    try:
        response = await llm.ainvoke(prompt, priority=llm_priority, user_id=user_id_int, pool="path")
        parsed = parse_llm_json(response.content)
        extra_raw = parsed.get("topic_outline") if isinstance(parsed, dict) else parsed
    except Exception:
        logger.exception("[PathLeader] 补全大纲失败 subject=%s 缺 %s 个", subject, missing)
        return outline

    if not isinstance(extra_raw, list) or not extra_raw:
        logger.warning("[PathLeader] 补全大纲返回空 subject=%s 缺 %s 个", subject, missing)
        return outline

    # 和已有的一起重新归一化：新节点会按**最终序号**算难度分。
    # 单独归一化新那批的话，第一个新节点的 index 会是 1 而被当成"路径首节点"。
    combined = _normalize_topic_outline([*outline, *extra_raw], subject, target)
    logger.info(
        "[PathLeader] 大纲已补全 subject=%s %s → %s（目标 %s）",
        subject,
        len(outline),
        len(combined),
        target,
    )
    return combined


async def parse_or_repair_leader_result(raw_text: str, state: dict, *, retry_llm: bool = True) -> dict:
    """Parse Path Leader JSON; repair once, then fall back to a stable outline."""
    subject = str(state.get("subject") or "通用学习")
    requested_count = _safe_int(state.get("node_count"), 0)
    difficulty = str(state.get("difficulty") or "medium")
    user_id_int = _safe_int(state.get("user_id"), 0)
    llm_priority = state.get("llm_priority", "high")

    try:
        result = parse_llm_json(raw_text)
        if not isinstance(result, dict):
            result = {}
    except Exception as parse_error:
        logger.warning("[PathLeader] JSON 解析失败，尝试修复: %s", parse_error)
        result = {}
        if retry_llm:
            repair_prompt = (
                "你是 JSON 修复器。请只修复下面内容为合法 JSON，不要新增解释文字，不要使用 markdown。\n"
                "要求：第一个字符必须是 {，最后一个字符必须是 }；保留原有 topic_outline 结构；无法确定的字段用合理短文本补齐。\n\n"
                f"原始内容：\n{str(raw_text or '')[:6000]}"
            )
            try:
                repaired = await llm.ainvoke(repair_prompt, priority=llm_priority, user_id=user_id_int, pool="path")
                parsed = parse_llm_json(repaired.content)
                if isinstance(parsed, dict):
                    result = parsed
            except Exception:
                logger.exception("[PathLeader] JSON 修复失败，使用本地兜底大纲")

    raw_outline = result.get("topic_outline")
    topic_outline = _normalize_topic_outline(raw_outline, subject, requested_count)
    outline_source = "agent"
    if not topic_outline:
        # 带上原因和原始片段：这是"整条路径的节点主题变成模板货"的唯一现场，
        # 不记下来的话下次还是只能靠查库反推。
        outline_source = "fallback"
        logger.warning(
            "[PathLeader] topic_outline 不可用（%s），使用本地兜底大纲 subject=%s raw=%s",
            _outline_rejection_reason(raw_outline),
            subject,
            str(raw_outline)[:200],
        )
        topic_outline = _fallback_topic_outline(subject, requested_count)
    elif requested_count > 0 and len(topic_outline) < requested_count:
        # 服务端给了目标数就只有"建议"两个字顶着，模型少给几个就直接少 —— 这里补足。
        topic_outline = await _expand_topic_outline(
            topic_outline, subject, difficulty, requested_count, state
        )

    if requested_count > 0:
        # 有目标时目标就是上限：不足的上面补过了，多了按目标截断。
        node_count = min(requested_count, len(topic_outline))
        if len(topic_outline) < requested_count:
            logger.warning(
                "[PathLeader] 大纲补不齐 subject=%s 目标=%s 实际=%s",
                subject,
                requested_count,
                len(topic_outline),
            )
    else:
        # 没有服务端目标（自动模式）时沿用原来的语义：由模型自报，再按大纲长度夹紧。
        node_count = _safe_int(result.get("node_count"), len(topic_outline)) or len(topic_outline)
        node_count = max(1, min(node_count, len(topic_outline)))
    return {
        "topic_outline": topic_outline[:node_count],
        "node_count": node_count,
        "difficulty": str(result.get("difficulty") or difficulty),
        # "agent" = 用了规划器的大纲，"fallback" = 整份换成了本地模板。
        # 调用方靠它决定要不要重试 —— 不区分的话，一次瞬时失败就等于接受模板货。
        "outline_source": outline_source,
    }


# ═══════════════════════════════════════
#  State
# ═══════════════════════════════════════

class PathState(TypedDict):
    user_id: str
    subject: str
    difficulty: str
    node_count: int
    portrait_context: str
    mastery_context: str
    kb_context: str
    learning_guidance: str
    # Leader 输出
    topic_outline: NotRequired[list[dict]]
    # Executor 输出
    nodes: NotRequired[list[dict]]
    # Reviewer 输出
    review_passed: NotRequired[bool]
    review_feedback: NotRequired[str]
    # 审核结论的来源："llm" 正常审核 / "error" 调用异常兜底放行 / "skipped" 无节点可审。
    # review_passed=True 在 "error" 时是故障放行而非真的通过，消费方需要能区分这两者。
    review_source: NotRequired[str]
    retry_count: NotRequired[int]
    llm_priority: NotRequired[str]


# ═══════════════════════════════════════
#  Leader — 路径大纲规划
# ═══════════════════════════════════════

async def leader_node(state: PathState) -> dict:
    """分析画像 + 学科 → 产出 topic_outline"""
    t0 = time.perf_counter()
    prompt_text = fill_prompt(
        load_prompt("path/leader"),
        subject=state["subject"],
        difficulty=state.get("difficulty", "medium"),
        node_count=str(state.get("node_count", 0)),
        portrait_context=state.get("portrait_context", "暂无画像数据"),
        mastery_context=state.get("mastery_context", "暂无掌握度数据"),
        kb_context=state.get("kb_context", "暂无相关知识库"),
        learning_guidance=state.get("learning_guidance", ""),
    )

    user_id_int = int(state.get("user_id", 0))
    llm_priority = state.get("llm_priority", "high")

    # 规划器原来**一次都不重试**（executor 那边有 _GROUP_RETRY_ATTEMPTS=2）：
    # 一次瞬时失败就直接接受本地模板大纲，整条路径的节点主题全变成模板货。
    # 现在重试，而且"退到模板"也算没完成 —— 那正是需要重试的那种结果。
    result = None
    for attempt in range(1, _LEADER_ATTEMPTS + 1):
        try:
            response = await llm.ainvoke(prompt_text, priority=llm_priority, user_id=user_id_int, pool="path")
            candidate = await parse_or_repair_leader_result(response.content, state)
        except Exception:
            logger.exception("[PathLeader] LLM 调用失败（第 %s 次尝试）", attempt)
            candidate = None
        if candidate is not None and candidate.get("outline_source") == "agent":
            result = candidate
            break
        result = candidate or result
        if attempt < _LEADER_ATTEMPTS:
            logger.warning("[PathLeader] 第 %s 次尝试没拿到可用大纲，重试 subject=%s", attempt, state["subject"])
            await asyncio.sleep(1.2 * attempt)

    if result is None:
        result = await parse_or_repair_leader_result("", state, retry_llm=False)

    topic_outline = result.get("topic_outline", [])
    node_count = result.get("node_count", len(topic_outline))
    difficulty = result.get("difficulty", state.get("difficulty", "medium"))

    logger.info(
        "[PathLeader] 规划完成 目标=%s 大纲=%s 耗时=%.1fs",
        _safe_int(state.get("node_count"), 0) or "自动",
        len(topic_outline),
        time.perf_counter() - t0,
    )
    return {
        "topic_outline": topic_outline,
        "node_count": node_count,
        "difficulty": difficulty,
        # 往上带一层：调用方据此知道这份大纲是规划器给的还是本地模板顶上的。
        "outline_source": result.get("outline_source", "agent"),
    }


# ═══════════════════════════════════════
#  Executor — 并行分组生成节点详情
# ═══════════════════════════════════════

async def executor_node(state: PathState) -> dict:
    """将 topic_outline 分组，并行调用 LLM 生成每组的节点详情"""
    t0 = time.perf_counter()
    topic_outline = state.get("topic_outline", [])
    if not topic_outline:
        logger.warning("[PathExecutor] topic_outline 为空")
        return {"nodes": []}

    subject = state["subject"]
    difficulty = state.get("difficulty", "medium")
    portrait_context = state.get("portrait_context", "")
    feedback = state.get("review_feedback", "")
    total_nodes = len(topic_outline)
    user_id_int = int(state.get("user_id", 0))
    llm_priority = state.get("llm_priority", "high")

    # 将 topic_outline 分成每组最多 _GROUP_SIZE 个
    groups: list[list[dict]] = []
    for i in range(0, total_nodes, _GROUP_SIZE):
        groups.append(topic_outline[i:i + _GROUP_SIZE])

    group_sem = asyncio.Semaphore(_MAX_GROUP_CONCURRENCY)

    async def generate_group(group_idx: int, group: list[dict]) -> list[dict]:
        """为某一组节点生成详细信息"""
        group_start = group_idx * _GROUP_SIZE + 1
        group_end = group_start + len(group) - 1
        group_topics = json.dumps(
            [
                {
                    **n,
                    "order_index": group_start + j,
                    "topic": n["topic"],
                    "cognitive_level": n.get("cognitive_level", "理解"),
                }
                for j, n in enumerate(group)
            ],
            ensure_ascii=False,
        )
        outline_json = json.dumps(topic_outline, ensure_ascii=False)

        prompt_text = fill_prompt(
            load_prompt("path/executor"),
            subject=subject,
            difficulty=difficulty,
            group_start=str(group_start),
            group_end=str(group_end),
            total_nodes=str(total_nodes),
            topic_outline=outline_json,
            group_topics=group_topics,
            portrait_context=portrait_context,
            feedback=feedback,
        )

        # 这一组该产出几个。提示词里写明了 group_start..group_end，所以这是模型的义务，
        # 不是"给几个算几个"。
        expected = len(group)
        best: list[dict] = []
        async with group_sem:
            for attempt in range(1, _GROUP_RETRY_ATTEMPTS + 1):
                try:
                    response = await llm.ainvoke(prompt_text, priority=llm_priority, user_id=user_id_int, pool="path")
                    nodes = parse_llm_json(response.content)
                    if isinstance(nodes, list) and len(nodes) >= expected:
                        logger.info("[PathExecutor] 第 %s 组生成了 %s 个节点（第 %s 次尝试）", group_idx + 1, len(nodes), attempt)
                        return nodes
                    # 少给也算"没完成"：原来只判"是不是非空列表"，于是一组要 4 个只回 1 个
                    # 会被直接采纳 —— "建议节点数"在这一步再被削一次且不留痕迹。
                    if isinstance(nodes, list) and len(nodes) > len(best):
                        best = nodes
                    logger.warning(
                        "[PathExecutor] 第 %s 组只返回 %s/%s 个节点（第 %s 次尝试）",
                        group_idx + 1,
                        len(nodes) if isinstance(nodes, list) else f"非法数据({type(nodes).__name__})",
                        expected,
                        attempt,
                    )
                except Exception:
                    logger.exception("[PathExecutor] 第 %s 组第 %s 次尝试失败", group_idx + 1, attempt)
                if attempt < _GROUP_RETRY_ATTEMPTS:
                    await asyncio.sleep(0.8 * attempt)

        merged = _merge_with_fallback(group, best, group_start)
        logger.warning(
            "[PathExecutor] 第 %s 组补足到 %s 个节点（智能体给了 %s 个，其余走本地兜底）",
            group_idx + 1,
            len(merged),
            len(best),
        )
        return merged

    # 并行执行所有分组
    results = await asyncio.gather(*[
        generate_group(i, g) for i, g in enumerate(groups)
    ])

    # 合并所有节点，按 order_index 排序
    all_nodes: list[dict] = []
    for group_nodes in results:
        all_nodes.extend(group_nodes)
    all_nodes.sort(key=lambda n: n.get("order_index", 0))
    all_nodes = attach_teaching_specs(all_nodes, topic_outline)
    outline_by_topic = {str(item.get("topic") or "").strip(): item for item in topic_outline}
    for index, node in enumerate(all_nodes, 1):
        planned = outline_by_topic.get(str(node.get("topic") or "").strip()) or {}
        node["difficulty_score"] = 1.0 if index == 1 else clamp_difficulty_score(
            node.get("difficulty_score"),
            clamp_difficulty_score(planned.get("difficulty_score"), 1.0),
        )

    logger.info(
        "[PathExecutor] 全部节点生成完成 计划=%s 实际=%s 耗时=%.1fs",
        total_nodes,
        len(all_nodes),
        time.perf_counter() - t0,
    )
    if len(all_nodes) < total_nodes:
        # 走到这里说明有组补完兜底仍然缺 —— 落库的 node_count 是实际值，
        # 所以不留这条日志的话，"生成了几个"这件事只能靠人肉查库才发现。
        logger.warning(
            "[PathExecutor] 实际节点数少于大纲 planned=%s achieved=%s subject=%s",
            total_nodes,
            len(all_nodes),
            subject,
        )
    return {"nodes": all_nodes}


# ═══════════════════════════════════════
#  Reviewer — 路径质量审核
# ═══════════════════════════════════════

async def reviewer_node(state: PathState) -> dict:
    """审核完整路径的连贯性、前置依赖、知识点覆盖"""
    t0 = time.perf_counter()
    nodes = state.get("nodes", [])
    if not nodes:
        return {"review_passed": True, "review_feedback": "", "review_source": "skipped"}

    subject = state["subject"]
    difficulty = state.get("difficulty", "medium")
    user_id_int = int(state.get("user_id", 0))
    llm_priority = state.get("llm_priority", "high")
    nodes_json = json.dumps(nodes, ensure_ascii=False)

    prompt_text = fill_prompt(
        load_prompt("path/reviewer"),
        subject=subject,
        difficulty=difficulty,
        nodes_json=nodes_json,
    )

    try:
        response = await llm.ainvoke(prompt_text, priority=llm_priority, user_id=user_id_int, pool="path")
        result = parse_llm_json(response.content)
        if not isinstance(result, dict):
            result = {}
    except Exception:
        # 审核不可用时不拦路径生成（review_passed 仍为 True，判定不变），
        # 但必须留下 review_source="error"：否则调用方无法把"故障放行"和"审核通过"分开。
        logger.exception("[PathReviewer] LLM 调用失败，放行路径 subject=%s", subject)
        return {"review_passed": True, "review_feedback": "", "review_source": "error"}

    passed = result.get("passed", False)
    if isinstance(passed, str):
        passed = passed.lower() in ("true", "yes", "1", "是", "pass")
    score = result.get("score", 0)
    feedback = result.get("feedback", "")
    issues = result.get("issues", [])

    retry_count = state.get("retry_count", 0)
    next_retry_count = retry_count if passed else retry_count + 1
    logger.info(f"[PathReviewer] passed={passed} source=llm score={score} issues={len(issues)} retry={next_retry_count} 耗时={time.perf_counter() - t0:.1f}s")
    return {
        "review_passed": passed,
        "review_feedback": feedback if not passed else "",
        "review_source": "llm",
        "retry_count": next_retry_count,
    }


# ═══════════════════════════════════════
#  Router
# ═══════════════════════════════════════

def should_continue(state: PathState) -> str:
    if state.get("review_passed"):
        return "end"
    if state.get("retry_count", 0) >= 2:
        logger.info("[PathGraph] 已达最大重试次数，强制结束")
        return "end"
    return "executor"


# ═══════════════════════════════════════
#  Graph
# ═══════════════════════════════════════

def build_path_graph():
    workflow = StateGraph(PathState)

    workflow.add_node("leader", leader_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reviewer", reviewer_node)

    workflow.add_edge(START, "leader")
    workflow.add_edge("leader", "executor")
    workflow.add_edge("executor", "reviewer")
    workflow.add_conditional_edges(
        "reviewer",
        should_continue,
        {"executor": "executor", "end": END},
    )

    return workflow.compile()


path_graph = build_path_graph()
