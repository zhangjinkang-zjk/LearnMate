"""Build and persist milestone-based advanced practice tasks."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.src.service.advanced.practice_service import PHASE_SETS

logger = logging.getLogger(__name__)


def practice_stages(kind: str, *, active_index: int = 0) -> list[dict]:
    """某个任务类型的阶段骨架，形状是任务字典里那份（带 status、不带 hint）。

    唯一出处是 `practice_service.PHASE_SETS`：会话的账本按同一套 id 记账，前端也只
    渲染服务端下发的阶段列表。这里曾经另写了一份 `context/plan/verify/review`，谁也
    不认识它 —— 落进 `completed_phases` 会被账本当未知值丢掉。
    """
    phases = PHASE_SETS[kind]
    return [
        {"id": pid, "label": label, "status": "active" if index == active_index else "pending"}
        for index, (pid, label, _hint) in enumerate(phases)
    ]

ADVANCED_MILESTONE_SIZE = 10
ADVANCED_UNLOCK_NODES = 10
# 对齐 LLM 客户端自己的 request_timeout（llm_config.py，120s）。原值 40s 每次必挂：
# 提示词 3k+ 字符、要输出 3 个任务 × 4 阶段的大 JSON。现在它在后台作业里跑，
# 不再占用请求时间，所以可以给足。
ADVANCED_AGENT_TIMEOUT_SECONDS = 120
# 兜底快照多久之后允许重试。太低会把页面变成"每次进来都打一发可能失败的生成"。
ADVANCED_FALLBACK_RETRY_SECONDS = 120

# 智能体还没返回时页面上显示的那句话。它必须说清两件事：这份任务是临时的、以及它
# 也建立在已完成节点上 —— 否则用户只会看到一段模板文案，以为页面是写死的。
_PENDING_SUMMARY = "正在按你已完成的节点生成实践任务，先给出临时入口，稍后会自动更新。"

GOAL_MODES = (
    (("就业", "岗位", "求职", "实习", "职业"), "job"),
    (("比赛", "竞赛", "答辩"), "competition"),
    (("考试", "考研", "证书", "认证"), "exam"),
    (("转行", "转入", "转型", "新方向"), "transition"),
    (("项目", "作品", "交付", "实现"), "project"),
    (("系统化知识基础", "建立知识体系", "补基础", "夯实基础"), "foundation"),
)


TASK_TEMPLATES = {
    "job": {
        "title": "完成一次{topic}岗位情境任务",
        "brief": "从实际岗位问题出发，说明你的判断、处理方案和验证方法。",
        "deliverables": ["问题定位记录", "处理方案与技术说明", "验证结果"],
        "criteria": ["判断能够对应岗位情境", "方案说明关键取舍", "结果包含可复查的验证证据"],
    },
    "competition": {
        "title": "完成一次{topic}赛题方案推演",
        "brief": "围绕赛题目标提出方案，明确创新点、实验设计和答辩依据。",
        "deliverables": ["赛题问题拆解", "方案与创新点说明", "实验或指标对比"],
        "criteria": ["方案紧扣赛题目标", "创新点有清晰对照", "结论由实验或指标支撑"],
    },
    "exam": {
        "title": "完成一次{topic}综合应用挑战",
        "brief": "把多个知识点放进同一问题中，展示推理过程并校验易错环节。",
        "deliverables": ["完整解题过程", "关键概念说明", "易错点复盘"],
        "criteria": ["推理过程完整", "概念使用准确", "能够解释错误选项或错误路径"],
    },
    "transition": {
        "title": "完成一次{topic}能力迁移任务",
        "brief": "将已有经验映射到新方向，补齐关键差距并形成可展示成果。",
        "deliverables": ["能力迁移说明", "差距补齐方案", "可展示的任务成果"],
        "criteria": ["说明已有能力如何迁移", "补强内容对应真实差距", "成果能够独立展示"],
    },
    "project": {
        "title": "完成一次{topic}项目阶段交付",
        "brief": "围绕当前项目目标完成方案设计，并用材料或运行结果验证可行性。",
        "deliverables": ["需求与问题分析", "项目方案及关键取舍", "测试或运行证据"],
        "criteria": ["方案覆盖明确需求", "关键决策有依据", "结果可复现或可验证"],
    },
    "foundation": {
        "title": "完成一次{topic}跨知识点综合任务",
        "brief": "连接已经学过的概念，在具体情境中选择方法并解释为什么。",
        "deliverables": ["知识关系梳理", "情境分析与方案", "结论与复盘"],
        "criteria": ["知识点之间关系清楚", "方法选择符合情境", "结论能够回到学习目标"],
    },
    "custom": {
        "title": "围绕“{topic}”完成一次目标验证",
        "brief": "从你设定的目标反推任务、成果和验证方式，形成一次完整交付。",
        "deliverables": ["目标与问题拆解", "行动方案与过程记录", "目标达成证据"],
        "criteria": ["任务与自定义目标直接相关", "过程记录能够说明关键判断", "结果能够证明目标是否达成"],
    },
}


def classify_goal(goal: str) -> str:
    """Map free-form onboarding goals to a stable advanced-task mode."""
    text = str(goal or "")
    for keywords, mode in GOAL_MODES:
        if any(keyword in text for keyword in keywords):
            return mode
    return "custom"


def _percent(value: Any) -> int:
    number = float(value or 0)
    return round(number * 100) if number <= 1 else round(number)


def _normalise_mastery_records(records: Iterable[Any] | None) -> list[dict]:
    """Convert mastery rows and diagnosis snapshots to one small read model."""
    result = []
    for record in records or []:
        if isinstance(record, dict):
            tag = record.get("knowledge_tag") or record.get("tag")
            attempts = record.get("total_attempts", 0)
            accuracy = record.get("accuracy")
            correct = record.get("correct_count", 0)
        else:
            tag = getattr(record, "knowledge_tag", None)
            attempts = getattr(record, "total_attempts", 0)
            accuracy = getattr(record, "accuracy", None)
            correct = getattr(record, "correct_count", 0)
        if not tag:
            continue
        try:
            attempts = int(attempts or 0)
        except (TypeError, ValueError):
            attempts = 0
        if accuracy is None:
            accuracy = float(correct or 0) / max(attempts, 1)
        try:
            accuracy = max(0.0, min(1.0, float(accuracy)))
        except (TypeError, ValueError):
            accuracy = 0.0
        result.append({
            "tag": str(tag),
            "accuracy": accuracy,
            "attempts": attempts,
            "level": record.get("mastery_level") if isinstance(record, dict) else getattr(record, "mastery_level", "beginner"),
        })
    return result


def _status_label(status: str) -> str:
    return {
        "completed": "已完成",
        "in_progress": "学习中",
        "unlocked": "已解锁",
        "locked": "待解锁",
    }.get(status, "待开始")


def _node_tags(node: dict) -> list[str]:
    return [str(tag) for tag in (node.get("knowledge_tags") or []) if tag]


def completed_nodes(path: dict) -> list[dict]:
    """已完成节点（原始字典），按路径顺序。

    顺序直接用 payload 的顺序：`PathService.get_current_path` 建列表前已经按
    `node.order_index` 排过（path/service.py 里 `progresses.sort(...)`），而 payload
    里的节点并不总是带 order_index，再排一次反而会把顺序弄错。
    """
    return [
        node
        for node in (path.get("nodes") or [])
        if isinstance(node, dict) and node.get("status") == "completed"
    ]


def _focus_node(path: dict) -> dict:
    """生成依据的锚点：**最近完成**的那个节点。

    以前这里是 `_current_node(path)`，取的 `current_node_id` —— 实测那个节点常常还是
    locked（待解锁），于是整页任务围绕一个学习者还没学过的节点生成，而已经学完的
    节点只被当成一个数字（"已完成 N 个路径节点"）。一个都没完成时才退回当前节点，
    那种情况下页面本来也不该有任务，只是不想让上下文出现空值。
    """
    done = completed_nodes(path)
    return done[-1] if done else _current_node(path)


def completed_scope(path: dict) -> list[dict]:
    """已完成节点的读模型，给提示词和文案用。"""
    return [
        {
            "order_index": node.get("order_index"),
            "title": node.get("title") or node.get("topic") or "",
            "knowledge_tags": _node_tags(node),
            "summary": node.get("summary") or "",
        }
        for node in completed_nodes(path)
    ]


def completed_scope_tags(path: dict) -> list[str]:
    """已完成范围内的全部知识标签，按出现顺序去重。"""
    seen: list[str] = []
    for node in completed_nodes(path):
        for tag in _node_tags(node):
            if tag not in seen:
                seen.append(tag)
    return seen


def _find_focus(
    tags: list[str],
    diagnosis: dict,
    mastery_records: list[dict],
    fallback: str,
    prefer: list[str] | None = None,
) -> tuple[str, dict | None]:
    """在**已完成范围**内挑最弱的知识点。

    候选范围原来是"当前节点的标签"。当前节点可能是待解锁的、学习者根本没接触过，
    于是"重点能力"经常显示成一个没学过的标签（实测就是：截图里的重点能力来自那个
    待解锁的节点）。改成在已完成范围内挑，选出来的才是真的练过、真的弱。

    `prefer` 是"没有任何掌握度证据时该拿哪个标签当代表"——传最近完成的那个节点的标签。
    不传的话会落到已完成范围内**最靠前**的标签，那是整条路径最早的内容，读起来像
    "重点能力：课程目标与知识地图概览"，跟当前进度完全脱节。
    """
    scoped = [item for item in mastery_records if item["tag"] in tags]
    weak_scoped = [item for item in scoped if item["accuracy"] < 0.7]
    weak_global = _normalise_mastery_records(diagnosis.get("weak_points"))
    weak_global_scoped = [item for item in weak_global if item["tag"] in tags and item["accuracy"] < 0.7]
    weak_candidates = weak_scoped or weak_global_scoped
    if not weak_candidates and not tags:
        weak_candidates = [item for item in weak_global if item["accuracy"] < 0.7]
    if weak_candidates:
        selected = min(weak_candidates, key=lambda item: item["accuracy"])
        return selected["tag"], selected
    if scoped:
        selected = min(scoped, key=lambda item: item["accuracy"])
        return selected["tag"], selected
    for candidate in (prefer or []) + tags:
        if candidate:
            return candidate, None
    return fallback or "当前知识点", None


def _build_learning_context(
    node: dict,
    focus: str,
    mastery: dict | None,
    scope: list[dict],
    total_count: int,
) -> dict:
    """描述"这次任务建立在什么基础上"。

    这里的字段前端「推荐依据」卡片直接用（`task.context.node_title` /
    `node_status_label` / `resource_label` / `reason`），所以锚点换成已完成节点后，
    它们描述的是**已完成范围 + 该范围内最近完成的那个节点**，不能再是"当前节点"。
    """
    status = node.get("status") or "locked"
    mastery_percent = _percent(mastery["accuracy"]) if mastery is not None else None
    resource_count = len(node.get("resources") or [])
    resources_viewed = bool(node.get("resources_viewed") or node.get("total_views"))
    completed_count = len(scope)
    if mastery is None:
        evidence = "尚无基础测试记录"
        mastery_label = "暂无测验证据"
    elif mastery.get("attempts", 0) > 0:
        evidence = f"基础测试已记录 {mastery.get('attempts', 0)} 次作答"
        mastery_label = f"掌握度 {mastery_percent}%"
    else:
        evidence = "基础诊断已记录该能力表现"
        mastery_label = f"诊断掌握度 {mastery_percent}%"
    resource_label = "已打开学习材料" if resources_viewed else (f"有 {resource_count} 份关联材料" if resource_count else "尚未关联学习材料")
    node_title = node.get("title") or node.get("topic") or "当前学习节点"
    status_text = _status_label(status)
    scope_label = f"已完成 {completed_count} / {total_count} 个节点" if completed_count else "尚无已完成节点"
    if completed_count:
        scope_copy = f"你已经完成 {completed_count} 个基础节点（最近：{node_title}）"
    else:
        scope_copy = f"你还没有完成的节点，当前节点“{node_title}”处于{status_text}"
    if mastery_percent is None:
        reason = f"{scope_copy}，但“{focus}”还没有应用证据，先用案例把判断过程走一遍。"
    elif mastery_percent < 60:
        reason = f"{scope_copy}；基础测试显示“{focus}”掌握度为 {mastery_percent}%，先处理一个带边界的案例。"
    elif status == "completed" or mastery_percent >= 80:
        reason = f"{scope_copy}；“{focus}”基础测试达到 {mastery_percent}%，已具备基础证据，可以进入开放交付。"
    else:
        reason = f"{scope_copy}；“{focus}”基础测试达到 {mastery_percent}%，换一个情境检查能否迁移。"
    return {
        "node_title": node_title,
        "node_status": status,
        "node_status_label": status_text,
        "knowledge_tags": _node_tags(node),
        "focus": focus,
        "mastery_percent": mastery_percent,
        "mastery_label": mastery_label,
        "evidence": evidence,
        "resource_label": resource_label,
        "resource_count": resource_count,
        "resources_viewed": resources_viewed,
        # 已完成范围：前端「推荐依据」用来显示这次任务到底站在什么基础上
        "completed_count": completed_count,
        "completed_scope_label": scope_label,
        "completed_scope_titles": [item["title"] for item in scope],
        "path_progress": {"completed": completed_count, "total": total_count},
        "reason": reason,
    }


def _recommended_kind(context: dict) -> str:
    """Choose the next practice mode from current evidence, not a fixed card."""
    mastery_percent = context.get("mastery_percent")
    if context.get("node_status") == "completed" or (mastery_percent is not None and mastery_percent >= 80):
        return "project"
    if mastery_percent is not None and mastery_percent >= 60:
        return "transfer"
    return "case"


def completed_node_count(path: dict) -> tuple[int, int]:
    """Return completed and total nodes from the server-owned path snapshot."""
    nodes = path.get("nodes") or []
    return sum(1 for node in nodes if node.get("status") == "completed"), len(nodes)


def advanced_milestone(completed_nodes: int) -> int:
    """Return the ten-node milestone that owns the current task snapshot."""
    completed = max(0, int(completed_nodes or 0))
    return completed // ADVANCED_MILESTONE_SIZE if completed >= ADVANCED_UNLOCK_NODES else 0


def effective_unlock_nodes(total_nodes: int) -> int:
    """路径节点数不足默认门槛时按实际节点数解锁。

    否则任何节点数少于 ADVANCED_UNLOCK_NODES 的路径，其用户即使全部学完也达不到
    门槛，将永远无法进入进阶学习。
    """
    total = max(0, int(total_nodes or 0))
    return min(ADVANCED_UNLOCK_NODES, total) if total else ADVANCED_UNLOCK_NODES


def _agent_context(profile: dict, path: dict, mastery_records: Iterable[Any], milestone: int) -> dict:
    completed, total = completed_node_count(path)
    node = _focus_node(path)
    next_node = _current_node(path)
    resources = [
        {
            "id": resource.get("id"),
            "title": resource.get("title"),
            "resource_type": resource.get("resource_type"),
        }
        for resource in (node.get("resources") or [])
        if isinstance(resource, dict)
    ]
    return {
        "milestone": milestone,
        "completed_nodes": completed,
        "total_nodes": total,
        # 生成依据：已完成的整段范围（标题 + 知识标签 + 摘要）。智能体要综合这些出题，
        # 而不是只围绕锚点那一个节点 —— 否则"综合实践"退化成一个知识点的练习题。
        "completed_scope": completed_scope(path),
        "profile": profile,
        "path": {
            "path_id": path.get("path_id"),
            "goal": path.get("goal"),
            "stage": path.get("stage"),
            "focus_node": {
                "id": node.get("id"),
                "title": node.get("title") or node.get("topic"),
                "summary": node.get("summary"),
                "status": node.get("status"),
                "knowledge_tags": _node_tags(node),
                "resources": resources,
                "resources_viewed": bool(node.get("resources_viewed") or node.get("total_views")),
                "time_spent": node.get("time_spent", 0),
            },
            # 保留原名（提示词里已有引用），但语义是"下一步参考"：它可能还没解锁，
            # 不能让智能体围着它出题。
            "current_node": {
                "id": next_node.get("id"),
                "title": next_node.get("title") or next_node.get("topic"),
                "status": next_node.get("status"),
                "note": "仅作下一步参考，可能尚未解锁；不要围绕它出题",
            },
        },
        "mastery": _normalise_mastery_records(mastery_records),
    }


def _clean_text(value: Any, fallback: str = "", limit: int = 140) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] if text else fallback


def _clean_list(value: Any, fallback: list[str], limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return fallback[:limit]
    cleaned = [_clean_text(item, limit=100) for item in value]
    cleaned = [item for item in cleaned if item]
    return cleaned[:limit] or fallback[:limit]


def _merge_agent_stages(raw_stages: Any, fallback_stages: list[dict]) -> list[dict]:
    """把智能体写的阶段文案套在服务端的阶段骨架上。

    **id 和顺序一律取服务端那份。** 以前这里是"智能体给了 id 就用它的"，于是生成器
    一直在写 `context/plan/verify/review` —— 而会话的账本只认它自己那套（案例诊断是
    `clues/fault/...`），两个词汇只共用一个 `verify`。那些 id 落进 `completed_phases`
    之后会被 `_clean_phases` 当未知值静默丢掉：用户的进度会莫名其妙清零，日志里却
    什么都不显。文案（label/hint）可以让智能体改，骨架不行。
    """
    fallback_stages = fallback_stages if isinstance(fallback_stages, list) else []
    if not isinstance(raw_stages, list) or len(raw_stages) != len(fallback_stages):
        return fallback_stages
    merged = []
    for index, stage in enumerate(raw_stages):
        base = fallback_stages[index]
        if not isinstance(stage, dict):
            return fallback_stages
        merged.append({
            "id": base["id"],
            "label": _clean_text(stage.get("label"), base.get("label", ""), 24),
            "hint": _clean_text(stage.get("hint"), base.get("hint", ""), 48),
            "status": base.get("status", "pending"),
        })
    return merged


def _normalise_agent_tasks(payload: Any, fallback_tasks: list[dict]) -> tuple[list[dict], str] | None:
    """Validate the agent contract while preserving server-owned IDs and context."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        return None
    raw_by_kind = {
        item.get("kind"): item for item in payload["tasks"] if isinstance(item, dict) and item.get("kind")
    }
    normalised = []
    for fallback in fallback_tasks:
        raw = raw_by_kind.get(fallback["kind"])
        if not isinstance(raw, dict):
            return None
        item = {**fallback}
        item["title"] = _clean_text(raw.get("title"), fallback["title"], 42)
        item["brief"] = _clean_text(raw.get("brief"), fallback["brief"])
        item["scenario"] = _clean_text(raw.get("scenario"), fallback.get("scenario", fallback["problem"]))
        item["problem"] = _clean_text(raw.get("problem"), fallback["problem"])
        item["why"] = _clean_text(raw.get("why"), fallback.get("why", fallback["brief"]))
        item["focus"] = fallback["context"]["focus"]
        item["deliverables"] = [
            {"id": f"deliverable-{index}", "label": label, "completed": False}
            for index, label in enumerate(
                _clean_list(raw.get("deliverables"), [entry["label"] for entry in fallback["deliverables"]]),
                start=1,
            )
        ]
        item["criteria"] = _clean_list(raw.get("criteria"), fallback["criteria"])
        item["constraints"] = _clean_list(raw.get("constraints"), fallback["constraints"])
        item["stages"] = _merge_agent_stages(raw.get("stages"), fallback["stages"])
        normalised.append(item)

    # The agent can propose a mode, but the server owns the progression gate.
    # This prevents a low-evidence learner from jumping directly to project work.
    recommended = next((item["kind"] for item in fallback_tasks if item.get("is_recommended")), "case")
    if payload.get("recommended_kind") != recommended:
        logger.info(
            "进阶任务推荐已收敛 requested=%s applied=%s",
            payload.get("recommended_kind"),
            recommended,
        )
    for item in normalised:
        item["status"] = "active" if item["kind"] == recommended else "available"
        item["is_recommended"] = item["kind"] == recommended
        if item["is_recommended"]:
            item["difficulty_label"] = "建议先做"
    return normalised, _clean_text(payload.get("summary"), "本次实践任务已根据当前学习里程碑更新。", 100)


def _build_agent_prompt(context: dict) -> str:
    from backend.src.utils.prompt_loader import fill_prompt, load_prompt

    return fill_prompt(
        load_prompt("advanced/task_generator"),
        profile_json=json.dumps(context["profile"], ensure_ascii=False),
        milestone_json=json.dumps({key: context[key] for key in ("milestone", "completed_nodes", "total_nodes")}, ensure_ascii=False),
        completed_nodes_json=json.dumps(context["completed_scope"], ensure_ascii=False),
        path_json=json.dumps(context["path"], ensure_ascii=False),
        mastery_json=json.dumps(context["mastery"], ensure_ascii=False),
    )


# 供应商的报错正文里常带凭据（401 的响应就常回显 api_key），日志不能原样打。
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_\-]{4,}|Bearer\s+[A-Za-z0-9._\-]+|(?:api[_-]?key|authorization)[\"'\s:=]+[A-Za-z0-9._\-]+)",
    re.IGNORECASE,
)


def _redact(text: Any) -> str:
    return _SECRET_PATTERN.sub("[已脱敏]", str(text or ""))


def _describe_failure(exc: BaseException) -> str:
    """异常的**类型 + 脱敏后的短消息**。

    以前这里只记 `type(exc).__name__`。超时倒是能靠类型名认出来，但"JSON 解析失败"
    "任务结构无效""模型返回空"这些只能靠消息区分 —— 结果是这次排查只能看到一句
    `error=TimeoutError` 之外的什么都没有，逼得去手动复现。消息必须脱敏后再打。
    """
    detail = _redact(str(exc)).strip()
    return f"{type(exc).__name__}: {detail[:160]}" if detail else type(exc).__name__


async def generate_agent_task_set(
    user_id: int,
    profile: dict,
    path: dict,
    mastery_records: list[Any],
    milestone: int,
    fallback_tasks: list[dict],
) -> dict:
    """跑一次智能体生成，返回落库用的 {tasks, summary, source, error}。

    只在后台作业里调用（见 task_jobs）—— 它可能跑满 ADVANCED_AGENT_TIMEOUT_SECONDS，
    放在请求里就会把页面拖到超时。
    """
    context = _agent_context(profile, path, mastery_records, milestone)
    try:
        from backend.src.ai_core.llm_config import llm
        from backend.src.utils.json_parser import parse_llm_json

        prompt = _build_agent_prompt(context)
        response = await asyncio.wait_for(
            # 高优先级：这份任务就是学生打开进阶页要看的东西，不是后台任务。标成 low 时它得和
            # 资源预生成、课堂过渡摘要、记忆抽取抢同一条全局 10 路通道，而 `wait_for` 把**排队
            # 时间也算进这 120 秒**里 —— 排队久了直接超时降级，页面上就是兜底模板。
            llm.ainvoke(prompt, priority="high", user_id=user_id, pool="advanced"),
            timeout=ADVANCED_AGENT_TIMEOUT_SECONDS,
        )
        parsed = parse_llm_json(response.content)
        normalised = _normalise_agent_tasks(parsed, fallback_tasks)
        if normalised:
            tasks, summary = normalised
            return {"tasks": tasks, "summary": summary, "source": "agent", "error": None}
        raise ValueError("进阶任务智能体返回的任务结构无效")
    except Exception as exc:
        logger.warning("进阶任务智能体降级兜底 user_id=%s milestone=%s error=%s", user_id, milestone, _describe_failure(exc))
        return {
            "tasks": fallback_tasks,
            "summary": "智能体这次没返回结果，先按你已完成的节点给出临时入口，稍后会自动重试。",
            "source": "fallback",
            "error": "进阶任务智能体暂时不可用",
        }


def _current_node(path: dict) -> dict:
    nodes = path.get("nodes") or []
    current_id = path.get("current_node_id")
    return next((node for node in nodes if node.get("id") == current_id), None) or next(
        (node for node in nodes if node.get("status") in ("unlocked", "in_progress")),
        None,
    ) or (nodes[-1] if nodes else {})


def build_advanced_task(profile: dict, path: dict, mastery_records: Iterable[Any] | None = None) -> dict:
    """Create the read-only task contract consumed by the advanced page.

    锚点是**最近完成的节点**，而不是 `current_node_id` 指向的那个（后者常常还没解锁）。
    已完成的节点集（scope）同时进入上下文和 project 任务的措辞里 —— 任务要建立在
    "已经学过什么"上，而不是"系统打算让你学什么"上。
    """
    identity = profile.get("identity") or "学习者"
    goal = profile.get("goal") or "建立系统化知识基础"
    direction = profile.get("direction") or path.get("goal") or "当前学习方向"
    node = _focus_node(path)
    topic = node.get("title") or direction
    mode = classify_goal(goal)
    template = TASK_TEMPLATES[mode]
    diagnosis = path.get("diagnosis") or {}
    mastery = _normalise_mastery_records(mastery_records)
    scope = completed_scope(path)
    scope_tags = completed_scope_tags(path)
    node_tags = _node_tags(node)
    # 挑薄弱点时优先看锚点节点自己的标签：它是最新学的，比整条路径的第一个标签
    # 更能代表"现在卡在哪"。
    focus, weak = _find_focus(node_tags + [tag for tag in scope_tags if tag not in node_tags], diagnosis, mastery, topic, prefer=node_tags)

    if weak:
        weak_copy = f"“{focus}”当前掌握度约为 {_percent(weak.get('accuracy'))}%"
    else:
        weak_copy = f"当前还缺少“{focus}”的充分练习证据"

    if scope:
        completed_copy = f"已完成 {len(scope)} 个路径节点，最近学的是“{topic}”"
    else:
        completed_copy = "尚未完成完整路径节点"
    first_deliverable = template["deliverables"][0]
    recommendation = (
        f"你当前以“{identity}”身份学习，目标是“{goal}”，{completed_copy}；{weak_copy}。"
        f"本次先围绕“{topic}”完成{first_deliverable}，再进入结果验证。"
    )
    resources = node.get("resources") or []
    context = _build_learning_context(node, focus, weak, scope, len(path.get("nodes") or []))
    # 锚点是"已完成"的节点，措辞得是完成时 —— 原来固定写"你正在学习“X”"，
    # 而 X 明明已经学完了，读起来像系统不知道自己的状态。
    if scope:
        study_copy = f"你已经完成“{topic}”这个节点"
        scene_copy = f"围绕已经学过的“{topic}”，针对“{focus}”完成一次与“{goal}”直接相关、可被复查的判断。"
    else:
        study_copy = f"你正在学习“{topic}”"
        scene_copy = f"在“{topic}”的学习情境中，针对“{focus}”完成一次与“{goal}”直接相关、可被复查的判断。"

    return {
        "id": f"path-{path.get('path_id')}-node-{node.get('id', 'current')}",
        "mode": mode,
        "title": template["title"].format(topic=topic),
        "brief": template["brief"],
        "problem": scene_copy,
        "scenario": f"{study_copy}。现在需要把“{focus}”用到一个具体问题中，交付{first_deliverable}。",
        "focus": focus,
        "recommendation": recommendation,
        "context": context,
        "completed_scope": scope,
        "deliverables": [
            {"id": f"deliverable-{index}", "label": label, "completed": False}
            for index, label in enumerate(template["deliverables"], start=1)
        ],
        "criteria": template["criteria"],
        "constraints": [
            "至少引用一项学习材料或实际数据作为判断依据",
            "说明为什么选择当前方案，以及放弃了哪些替代方案",
            "提交能够被他人复查的结果，而不是只写最终结论",
        ],
        "resources": resources,
        # 阶段骨架来自 practice_service.PHASE_SETS —— 会话的账本就认那套 id，这里
        # 再写一份字面量的话，两处迟早对不上（这正是改动前 context/plan/verify/review
        # 那套词汇的来历：前后端各写各的，谁都没在账本里见过它）。
        "stages": practice_stages("case"),
        "workspace": {"path_id": path.get("path_id"), "node_id": node.get("id")},
    }


def _compact_tag_list(tags: list[str], fallback: str, budget: int = 34) -> str:
    """把知识标签拼成一句能塞进标题的短语。

    全部拼上会超长（真实数据 3 个标签就 42 字），标题里读起来像堆词；这里按字数
    预算挑前面的几个 —— 路径本来就是由浅入深，前面的是更基础、更该被覆盖的。
    """
    picked: list[str] = []
    used = 0
    for tag in tags:
        extra = len(tag) + (1 if picked else 0)
        if picked and used + extra > budget:
            break
        picked.append(tag)
        used += extra
    return "、".join(picked) if picked else fallback


def build_advanced_tasks(profile: dict, path: dict, mastery_records: Iterable[Any] | None = None) -> list[dict]:
    """Create distinct practice entry points for the same current knowledge gap.

    The task list is deliberately derived from the existing task contract so the
    overview and practice pages share one source of truth.  ``status`` describes
    the suggested order only; completing a task is not inferred on the client.
    """
    base = build_advanced_task(profile, path, mastery_records)
    topic = _focus_node(path).get("title") or profile.get("direction") or "当前知识点"
    scope = base.get("completed_scope") or []
    recommended_kind = _recommended_kind(base["context"])
    # project 要综合整段已完成范围，不是只围着最近一个节点转。取已完成范围内最靠前的
    # 几个标签当"必须覆盖到"的清单 —— 挑前面的是因为路径本来就是由浅入深。
    scope_copy = _compact_tag_list(completed_scope_tags(path), topic)

    transfer = {
        **base,
        "id": f"{base['id']}-transfer",
        "kind": "transfer",
        "kind_label": "迁移练习",
        "difficulty_label": "引导练习",
        "status": "pending",
        "support_level": "high",
        # 三种类型的阶段骨架各不相同 —— 这正是"交互形态跟着任务类型走"的落点，
        # 以前三个变体都从 base 继承同一份 stages，操作方式自然一字不差。
        "stages": practice_stages("transfer"),
        "title": f"把“{topic}”迁移到一个新情境",
        "brief": "换一个与原例子不同的情境，说明你会如何识别问题、选择方法并验证结果。",
        "why": f"{base['context']['mastery_label']}；换一个情境检查“{base['context']['focus']}”能否迁移。",
    }
    case = {
        **base,
        "kind": "case",
        "kind_label": "案例诊断",
        "difficulty_label": "当前推荐",
        "status": "active",
        "support_level": "medium",
        "stages": practice_stages("case"),
        "why": base["recommendation"],
    }
    if scope:
        project_title = f"综合“{scope_copy}”完成一次项目交付"
        project_brief = f"把已完成的 {len(scope)} 个节点串成一条可交付的方案，独立完成设计、验证和复盘。"
        project_scenario = (
            f"你已经完成 {len(scope)} 个节点，覆盖{scope_copy}等内容。"
            f"现在需要一个把它们放进同一个目标的交付物，而不是只演示其中一个知识点。"
        )
        # 交付物要点名覆盖到的标签，否则"综合"只是一句话，学习者不知道该覆盖什么
        project_deliverables = [
            {"id": "deliverable-1", "label": f"覆盖「{scope_copy}」的方案设计", "completed": False},
            {"id": "deliverable-2", "label": "关键取舍说明与放弃的替代方案", "completed": False},
            {"id": "deliverable-3", "label": "可复现的验证或运行证据", "completed": False},
        ]
        project_why = f"{base['context']['node_status_label']}；已完成 {len(scope)} 个节点，用开放交付检验能否把它们合起来独立完成。"
    else:
        project_title = f"围绕“{topic}”完成一段项目交付"
        project_brief = "把当前知识点放进一个更开放的项目目标中，独立完成方案、验证和复盘。"
        project_scenario = base["scenario"]
        project_deliverables = base["deliverables"]
        project_why = f"{base['context']['node_status_label']}；当“{base['context']['focus']}”已有足够证据后，用开放交付检验独立完成能力。"
    project = {
        **base,
        "id": f"{base['id']}-project",
        "kind": "project",
        "kind_label": "项目实训",
        "difficulty_label": "开放挑战",
        "status": "pending",
        "support_level": "low",
        "stages": practice_stages("project"),
        "title": project_title,
        "brief": project_brief,
        "scenario": project_scenario,
        "deliverables": project_deliverables,
        "why": project_why,
    }
    tasks = [transfer, case, project]
    for item in tasks:
        item["status"] = "active" if item["kind"] == recommended_kind else "available"
        item["is_recommended"] = item["kind"] == recommended_kind
        if item["kind"] == recommended_kind:
            item["difficulty_label"] = "建议先做"
    return tasks


def _read_snapshot(snapshot: Any) -> dict | None:
    if not snapshot:
        return None
    payload = snapshot.task_json if isinstance(snapshot.task_json, dict) else {}
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return None
    return {
        "tasks": tasks,
        "summary": payload.get("summary") or "本次实践任务已根据当前学习里程碑更新。",
        "source": snapshot.source or "agent",
        "generation_error": snapshot.generation_error,
        "generated_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


async def _attach_practice_status(user_id: int, path_id: int, tasks: list[dict]) -> list[dict]:
    """把服务端巩固会话状态附加到当前任务快照；返回**没被任何任务认领**的历史会话。

    任务 id 里带着锚点节点（`path-48-node-659-project`），而锚点是"最近完成的节点" ——
    用户一完成下一个节点，锚点就换名字，快照重建后老会话再也挂不回任何任务上。库里
    实测有 active 状态的会话，也就是用户还能接着做的东西；就这么从界面上消失等于把
    他的工作藏起来。

    所以认领不上的不丢，单独作为"历史实践"返回。**不按 kind 硬套到同名任务上**：
    那样用户会看到自己没做过的任务标着"已完成"，比看不到更糟。
    """
    task_keys = [str(item.get("id")) for item in tasks if isinstance(item, dict) and item.get("id")]
    from backend.src.models.advanced_practice_model import AdvancedPracticeSession

    # 这里不再用 task_key__in 过滤：要找的恰恰是**不在**当前任务里的那些。
    # 每个 (user, path) 的会话是用户手动做出来的，量级很小。
    sessions = await AdvancedPracticeSession.filter(
        user_id=user_id,
        path_id=path_id,
    ).order_by("-updated_at").all()
    latest_by_task: dict[str, AdvancedPracticeSession] = {}
    for session in sessions:
        latest_by_task.setdefault(session.task_key, session)
    status_labels = {"active": "进行中", "paused": "已暂存", "completed": "已完成"}
    for item in tasks:
        session = latest_by_task.get(str(item.get("id")))
        if session:
            item["practice_status"] = session.status
            item["practice_status_label"] = status_labels.get(session.status, "已保存")
            item["practice_session_id"] = session.session_key
    if not task_keys:
        return []
    claimed = set(task_keys)
    history = [
        {
            "session_id": session.session_key,
            "task_key": task_key,
            "task_title": (session.task_snapshot or {}).get("title") or "之前的实践任务",
            "status": session.status,
            "status_label": status_labels.get(session.status, "已保存"),
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        }
        for task_key, session in latest_by_task.items()
        if task_key not in claimed
    ]
    history.sort(key=lambda item: item["updated_at"] or "", reverse=True)
    return history[:6]


def _snapshot_age_seconds(snapshot: Any) -> float:
    stamp = getattr(snapshot, "updated_at", None) or getattr(snapshot, "created_at", None)
    if not stamp:
        return float("inf")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())


def _snapshot_action(source: str | None, job_running: bool, age_seconds: float) -> str:
    """这次请求该怎么处理快照：直接用（serve），还是顺带起一个生成作业（generate）。

    抽成纯函数是因为分支全是"状态 + 时间"的组合，而这几个组合正好是最容易写错的地方：
    `pending` 行如果没人接手（进程重启把进程内的作业注册表清空了），页面就永远停在
    "生成中"；`fallback` 行如果不设年龄门槛，每次进页面都会打一发可能失败的生成。
    """
    if source == "agent":
        return "serve"
    if job_running:
        return "serve"  # 已经在生成了，等它
    if source == "fallback":
        return "generate" if age_seconds >= ADVANCED_FALLBACK_RETRY_SECONDS else "serve"
    # pending 且没人跑 = 陈旧（进程重启过），接手重跑；没有快照时同理
    return "generate"


async def _run_agent_generation(
    user_id: int,
    path_id: int,
    milestone: int,
    profile: dict,
    path: dict,
    mastery_records: list[Any],
    fallback_tasks: list[dict],
) -> None:
    """后台作业体：跑智能体，把结果写回那一行快照。"""
    from backend.src.models.advanced_task_model import AdvancedTaskSnapshot

    generated = await generate_agent_task_set(user_id, profile, path, mastery_records, milestone, fallback_tasks)
    completed, _ = completed_node_count(path)
    # updated_at 必须显式写：QuerySet.update() 不触发 auto_now，不写的话
    # "兜底过了多久才允许重试"的年龄永远不涨，每次进页面都会重发一次生成。
    await AdvancedTaskSnapshot.filter(user_id=user_id, path_id=path_id, milestone=milestone).update(
        task_json={"tasks": generated["tasks"], "summary": generated["summary"]},
        source=generated["source"],
        generation_error=generated["error"],
        completed_nodes=completed,
        updated_at=datetime.now(timezone.utc),
    )
    logger.info(
        "进阶任务生成完成 user_id=%s path_id=%s milestone=%s source=%s",
        user_id, path_id, milestone, generated["source"],
    )


async def _ensure_generation(
    user_id: int,
    path_id: int,
    milestone: int,
    profile: dict,
    path: dict,
    mastery_records: list[Any],
    fallback_tasks: list[dict],
) -> None:
    """起一个后台生成作业；同一个里程碑已有作业在跑就什么都不做。"""
    from backend.src.service.advanced.task_jobs import ensure_task_job

    await ensure_task_job(
        user_id,
        path_id,
        milestone,
        lambda: _run_agent_generation(user_id, path_id, milestone, profile, path, mastery_records, fallback_tasks),
    )


async def _create_pending_snapshot(
    user_id: int,
    path_id: int,
    milestone: int,
    fallback_tasks: list[dict],
    path: dict,
) -> dict | None:
    """先落一份确定性任务，让请求能立刻返回；生成结果随后写回同一行。"""
    from backend.src.models.advanced_task_model import AdvancedTaskSnapshot

    completed, _ = completed_node_count(path)
    node = _current_node(path)
    try:
        snapshot = await AdvancedTaskSnapshot.create(
            user_id=user_id,
            path_id=path_id,
            milestone=milestone,
            completed_nodes=completed,
            current_node_id=node.get("id"),
            task_json={"tasks": fallback_tasks, "summary": _PENDING_SUMMARY},
            source="pending",
            generation_error=None,
        )
    except Exception:
        # 另一个 worker 在读写之间抢先建了同一行（unique 约束）—— 用它的就行
        logger.warning("进阶任务快照创建冲突 user_id=%s path_id=%s milestone=%s", user_id, path_id, milestone)
        return _read_snapshot(await AdvancedTaskSnapshot.filter(
            user_id=user_id, path_id=path_id, milestone=milestone,
        ).first())

    # The current milestone is the only task set shown to the learner.
    await AdvancedTaskSnapshot.filter(user_id=user_id, path_id=path_id).exclude(milestone=milestone).delete()
    return _read_snapshot(snapshot)


async def _get_or_create_snapshot(
    user_id: int,
    path_id: int,
    milestone: int,
    profile: dict,
    path: dict,
    mastery_records: list[Any],
) -> dict:
    """读取这一里程碑的任务快照；没有就**立刻**落一份确定性任务，生成放后台。

    以前这里是同步跑智能体的（`asyncio.wait_for(..., timeout=40)`），于是三件事连着发生：
    请求阻塞到超时 → 退到确定性兜底 → 兜底被缓存且永不失效。库里就是这么留下
    "09-04 一次 agent，之后 12 天全是 fallback"的。现在请求只等一次 DB 读写，
    智能体在后台跑完写回，前端下一次轮询就接上。
    """
    from backend.src.models.advanced_task_model import AdvancedTaskSnapshot
    from backend.src.service.advanced.task_jobs import is_generating

    row = await AdvancedTaskSnapshot.filter(user_id=user_id, path_id=path_id, milestone=milestone).first()
    existing = _read_snapshot(row)
    job_running = is_generating(user_id, path_id, milestone)
    action = _snapshot_action(existing.get("source") if existing else None, job_running, _snapshot_age_seconds(row))
    if existing and action == "serve":
        return existing

    fallback_tasks = build_advanced_tasks(profile, path, mastery_records)
    if not existing:
        existing = await _create_pending_snapshot(user_id, path_id, milestone, fallback_tasks, path)
    await _ensure_generation(user_id, path_id, milestone, profile, path, mastery_records, fallback_tasks)
    return existing or {
        "tasks": fallback_tasks,
        "summary": _PENDING_SUMMARY,
        "source": "pending",
        "generation_error": None,
        "generated_at": None,
    }


class AdvancedLearningService:
    @staticmethod
    async def get_current(user_id: int) -> dict:
        from backend.src.models.usermodel import User
        from backend.src.service.path.service import PathService
        from backend.src.service.portrait.service import parse_traits
        from backend.src.models.exam_model import KnowledgeMastery

        user = await User.filter(id=user_id).first()
        if not user:
            raise ValueError("用户不存在")

        picture = await user.picture
        traits = parse_traits(picture.traits if picture else None)
        onboarding = traits.get("onboarding") if isinstance(traits.get("onboarding"), dict) else {}
        current_path = await PathService.get_current_path(user_id)
        profile = {
            "identity": onboarding.get("identity") or "学习者",
            "direction": onboarding.get("direction") or (current_path or {}).get("goal") or "",
            "goal": onboarding.get("goal") or "建立系统化知识基础",
            "learning_signals": traits.get("learning_signals", {}) if isinstance(traits.get("learning_signals"), dict) else {},
        }

        if not current_path:
            return {"status": "path_required", "profile": profile, "path": None, "tasks": [], "task": None}

        mastery_records = await KnowledgeMastery.filter(user_id=user_id).all()
        completed, total = completed_node_count(current_path)
        # 节点数不足默认门槛的路径按实际长度解锁，否则其用户永远进不了进阶学习。
        unlock_nodes = effective_unlock_nodes(total)
        is_unlocked = completed >= unlock_nodes
        milestone = advanced_milestone(completed) if is_unlocked else 0
        # 短路径全部完成时 advanced_milestone 仍返回 0，归入第一个里程碑。
        if is_unlocked and milestone == 0:
            milestone = 1
        path_payload = {
            "id": current_path.get("path_id"),
            "stage": current_path.get("stage"),
            "progress": current_path.get("progress", 0),
            "current_node_id": current_path.get("current_node_id"),
            "diagnosis": current_path.get("diagnosis") or {},
            "completed_nodes": completed,
            "total_nodes": total,
        }
        milestone_payload = {
            "size": ADVANCED_MILESTONE_SIZE,
            "unlock_nodes": unlock_nodes,
            "completed_nodes": completed,
            "current": milestone,
            "next": max(unlock_nodes, (milestone + 1) * ADVANCED_MILESTONE_SIZE),
            "remaining": max(0, unlock_nodes - completed),
        }

        if not is_unlocked:
            return {
                "status": "locked",
                "profile": profile,
                "path": path_payload,
                "milestone": milestone_payload,
                "tasks": [],
                "task": None,
            }

        try:
            snapshot = await _get_or_create_snapshot(
                user_id,
                int(current_path["path_id"]),
                milestone,
                profile,
                current_path,
                mastery_records,
            )
        except Exception:
            # Keep the page usable during a rolling deploy before the new table is created.
            logger.exception(
                "进阶任务快照不可用 user_id=%s path_id=%s milestone=%s",
                user_id,
                current_path.get("path_id"),
                milestone,
            )
            generated = build_advanced_tasks(profile, current_path, mastery_records)
            snapshot = {
                "tasks": generated,
                "summary": "当前里程碑任务已生成，保存服务恢复后会继续沿用。",
                "source": "fallback",
                "generation_error": "任务快照暂不可用",
                "generated_at": None,
            }
        tasks = snapshot["tasks"]
        practice_history: list[dict] = []
        try:
            practice_history = await _attach_practice_status(
                user_id, int(current_path["path_id"]), tasks
            )
        except Exception:
            # 会话状态是增强信息；即使旧部署还没创建会话表，也不能阻断任务入口。
            logger.exception(
                "进阶实践状态不可用 user_id=%s path_id=%s",
                user_id,
                current_path.get("path_id"),
            )
        active_task = next((item for item in tasks if item.get("is_recommended")), tasks[0] if tasks else None)

        return {
            "status": "ready",
            "profile": profile,
            "path": path_payload,
            "milestone": milestone_payload,
            # 前端靠这三个字段区分"智能体生成中 / 临时入口 / 已生成"。
            # 以前只返回了 task_source 而前端从没读它，用户只能靠那句兜底文案猜。
            "task_source": snapshot["source"],
            "task_summary": snapshot["summary"],
            "task_generated_at": snapshot["generated_at"],
            "task_generation_error": snapshot.get("generation_error"),
            # 沿 path_router 的既有命名：任务还没落定，前端应当稍后再拉一次
            "generation_status": "partial" if snapshot["source"] == "pending" else "ready",
            "tasks": tasks,
            "task": active_task,
            # 做过、但当前任务列表里已经没有它位置的实践记录。任务 id 带锚点节点，
            # 用户完成下一个节点后锚点换名字，这些会话就挂不回去了 —— 但它们是
            # 用户真实做过的东西（可能还没提交），不能就这么从页面上消失。
            "practice_history": practice_history,
        }
