"""Build and persist milestone-based advanced practice tasks."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

ADVANCED_MILESTONE_SIZE = 10
ADVANCED_UNLOCK_NODES = 10
ADVANCED_AGENT_TIMEOUT_SECONDS = 40
_snapshot_locks: dict[tuple[int, int, int], asyncio.Lock] = {}

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
        "title": "围绕{topic}完成一次目标验证",
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


def _find_focus(node: dict, diagnosis: dict, mastery_records: list[dict]) -> tuple[str, dict | None]:
    """Prefer a weak point belonging to the current node over global weak points."""
    tags = [str(tag) for tag in (node.get("knowledge_tags") or []) if tag]
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
    return (tags[0] if tags else node.get("title") or "当前知识点"), None


def _build_learning_context(node: dict, focus: str, mastery: dict | None, completed_count: int, total_count: int) -> dict:
    status = node.get("status") or "locked"
    mastery_percent = _percent(mastery["accuracy"]) if mastery is not None else None
    resource_count = len(node.get("resources") or [])
    resources_viewed = bool(node.get("resources_viewed") or node.get("total_views"))
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
    if mastery_percent is None:
        reason = f"当前节点“{node_title}”处于{status_text}，还没有“{focus}”的应用证据，先用案例把判断过程走一遍。"
    elif mastery_percent < 60:
        reason = f"基础测试显示“{focus}”掌握度为 {mastery_percent}%，当前节点“{node_title}”仍在{status_text}，先处理一个带边界的案例。"
    elif status == "completed" or mastery_percent >= 80:
        reason = f"“{focus}”基础测试达到 {mastery_percent}%，节点“{node_title}”已具备基础证据，可以进入开放交付。"
    else:
        reason = f"“{focus}”基础测试达到 {mastery_percent}%，节点“{node_title}”正在{status_text}，换一个情境检查能否迁移。"
    return {
        "node_title": node_title,
        "node_status": status,
        "node_status_label": status_text,
        "knowledge_tags": node.get("knowledge_tags") or [],
        "focus": focus,
        "mastery_percent": mastery_percent,
        "mastery_label": mastery_label,
        "evidence": evidence,
        "resource_label": resource_label,
        "resource_count": resource_count,
        "resources_viewed": resources_viewed,
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


def _agent_context(profile: dict, path: dict, mastery_records: Iterable[Any], milestone: int) -> dict:
    completed, total = completed_node_count(path)
    node = _current_node(path)
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
        "profile": profile,
        "path": {
            "path_id": path.get("path_id"),
            "goal": path.get("goal"),
            "stage": path.get("stage"),
            "current_node": {
                "id": node.get("id"),
                "title": node.get("title") or node.get("topic"),
                "summary": node.get("summary"),
                "status": node.get("status"),
                "knowledge_tags": node.get("knowledge_tags") or [],
                "resources": resources,
                "resources_viewed": bool(node.get("resources_viewed") or node.get("total_views")),
                "time_spent": node.get("time_spent", 0),
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
        raw_stages = raw.get("stages")
        if isinstance(raw_stages, list) and len(raw_stages) >= 4:
            item["stages"] = [
                {
                    "id": _clean_text(stage.get("id"), fallback["stages"][index]["id"], 24),
                    "label": _clean_text(stage.get("label"), fallback["stages"][index]["label"], 24),
                    "hint": _clean_text(stage.get("hint"), "完成本阶段并留下证据", 48),
                    "status": fallback["stages"][index].get("status", "pending"),
                }
                for index, stage in enumerate(raw_stages[:4])
                if isinstance(stage, dict)
            ]
        if len(item.get("stages", [])) != 4:
            item["stages"] = fallback["stages"]
        normalised.append(item)

    # The agent can propose a mode, but the server owns the progression gate.
    # This prevents a low-evidence learner from jumping directly to project work.
    recommended = next((item["kind"] for item in fallback_tasks if item.get("is_recommended")), "case")
    if payload.get("recommended_kind") != recommended:
        logger.info(
            "advanced task recommendation constrained requested=%s applied=%s",
            payload.get("recommended_kind"),
            recommended,
        )
    for item in normalised:
        item["status"] = "active" if item["kind"] == recommended else "available"
        item["is_recommended"] = item["kind"] == recommended
        if item["is_recommended"]:
            item["difficulty_label"] = "建议先做"
    return normalised, _clean_text(payload.get("summary"), "本次实践任务已根据当前学习里程碑更新。", 100)


async def _generate_agent_task_set(user_id: int, profile: dict, path: dict, mastery_records: list[Any], milestone: int) -> dict:
    """Generate once at a milestone, with the existing deterministic contract as fallback."""
    fallback_tasks = build_advanced_tasks(profile, path, mastery_records)
    context = _agent_context(profile, path, mastery_records, milestone)
    try:
        from backend.src.ai_core.llm_config import llm
        from backend.src.utils.json_parser import parse_llm_json
        from backend.src.utils.prompt_loader import fill_prompt, load_prompt

        prompt = fill_prompt(
            load_prompt("advanced/task_generator"),
            profile_json=json.dumps(context["profile"], ensure_ascii=False),
            milestone_json=json.dumps({key: context[key] for key in ("milestone", "completed_nodes", "total_nodes")}, ensure_ascii=False),
            path_json=json.dumps(context["path"], ensure_ascii=False),
            mastery_json=json.dumps(context["mastery"], ensure_ascii=False),
        )
        response = await asyncio.wait_for(
            llm.ainvoke(prompt, priority="low", user_id=user_id, pool="advanced"),
            timeout=ADVANCED_AGENT_TIMEOUT_SECONDS,
        )
        parsed = parse_llm_json(response.content)
        normalised = _normalise_agent_tasks(parsed, fallback_tasks)
        if normalised:
            tasks, summary = normalised
            return {"tasks": tasks, "summary": summary, "source": "agent", "error": None}
        raise ValueError("进阶任务智能体返回的任务结构无效")
    except Exception as exc:
        logger.warning("advanced task agent fallback user_id=%s milestone=%s error=%s", user_id, milestone, type(exc).__name__)
        return {
            "tasks": fallback_tasks,
            "summary": "智能体暂不可用，已根据当前学习记录生成临时实践入口。",
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
    """Create the read-only task contract consumed by the advanced page."""
    identity = profile.get("identity") or "学习者"
    goal = profile.get("goal") or "建立系统化知识基础"
    direction = profile.get("direction") or path.get("goal") or "当前学习方向"
    node = _current_node(path)
    topic = node.get("title") or direction
    mode = classify_goal(goal)
    template = TASK_TEMPLATES[mode]
    diagnosis = path.get("diagnosis") or {}
    mastery = _normalise_mastery_records(mastery_records)
    completed = [item for item in path.get("nodes") or [] if item.get("status") == "completed"]
    focus, weak = _find_focus(node, diagnosis, mastery)

    if weak:
        weak_copy = f"“{focus}”当前掌握度约为 {_percent(weak.get('accuracy'))}%"
    else:
        weak_copy = f"当前还缺少“{focus}”的充分练习证据"

    completed_copy = f"已完成 {len(completed)} 个路径节点" if completed else "尚未完成完整路径节点"
    first_deliverable = template["deliverables"][0]
    recommendation = (
        f"你当前以“{identity}”身份学习，目标是“{goal}”，{completed_copy}；{weak_copy}。"
        f"本次先围绕“{topic}”完成{first_deliverable}，再进入结果验证。"
    )
    resources = node.get("resources") or []
    context = _build_learning_context(node, focus, weak, len(completed), len(path.get("nodes") or []))

    return {
        "id": f"path-{path.get('path_id')}-node-{node.get('id', 'current')}",
        "mode": mode,
        "title": template["title"].format(topic=topic),
        "brief": template["brief"],
        "problem": f"在“{topic}”的学习情境中，针对“{focus}”完成一次与“{goal}”直接相关、可被复查的判断。",
        "scenario": f"你正在学习“{topic}”。现在需要把“{focus}”用到一个具体问题中，交付{first_deliverable}。",
        "focus": focus,
        "recommendation": recommendation,
        "context": context,
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
        "stages": [
            {"id": "context", "label": "理解情境", "status": "active"},
            {"id": "plan", "label": "制定方案", "status": "pending"},
            {"id": "verify", "label": "验证结果", "status": "pending"},
            {"id": "review", "label": "复盘答辩", "status": "pending"},
        ],
        "workspace": {"path_id": path.get("path_id"), "node_id": node.get("id")},
    }


def build_advanced_tasks(profile: dict, path: dict, mastery_records: Iterable[Any] | None = None) -> list[dict]:
    """Create distinct practice entry points for the same current knowledge gap.

    The task list is deliberately derived from the existing task contract so the
    overview and practice pages share one source of truth.  ``status`` describes
    the suggested order only; completing a task is not inferred on the client.
    """
    base = build_advanced_task(profile, path, mastery_records)
    topic = _current_node(path).get("title") or profile.get("direction") or "当前知识点"
    recommended_kind = _recommended_kind(base["context"])

    transfer = {
        **base,
        "id": f"{base['id']}-transfer",
        "kind": "transfer",
        "kind_label": "迁移练习",
        "difficulty_label": "引导练习",
        "status": "pending",
        "support_level": "high",
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
        "why": base["recommendation"],
    }
    project = {
        **base,
        "id": f"{base['id']}-project",
        "kind": "project",
        "kind_label": "项目实训",
        "difficulty_label": "开放挑战",
        "status": "pending",
        "support_level": "low",
        "title": f"围绕“{topic}”完成一段项目交付",
        "brief": "把当前知识点放进一个更开放的项目目标中，独立完成方案、验证和复盘。",
        "why": f"{base['context']['node_status_label']}；当“{base['context']['focus']}”已有足够证据后，用开放交付检验独立完成能力。",
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


async def _attach_practice_status(user_id: int, path_id: int, tasks: list[dict]) -> None:
    """把服务端巩固会话状态附加到当前任务快照，不让前端猜测完成状态。"""
    task_keys = [str(item.get("id")) for item in tasks if isinstance(item, dict) and item.get("id")]
    if not task_keys:
        return
    from backend.src.models.advanced_practice_model import AdvancedPracticeSession

    sessions = await AdvancedPracticeSession.filter(
        user_id=user_id,
        path_id=path_id,
        task_key__in=task_keys,
    ).order_by("-updated_at").all()
    latest_by_task = {}
    for session in sessions:
        latest_by_task.setdefault(session.task_key, session)
    status_labels = {"active": "进行中", "paused": "已暂存", "completed": "已完成"}
    for item in tasks:
        session = latest_by_task.get(str(item.get("id")))
        if session:
            item["practice_status"] = session.status
            item["practice_status_label"] = status_labels.get(session.status, "已保存")
            item["practice_session_id"] = session.session_key


async def _get_or_create_snapshot(
    user_id: int,
    path_id: int,
    milestone: int,
    profile: dict,
    path: dict,
    mastery_records: list[Any],
) -> dict:
    from backend.src.models.advanced_task_model import AdvancedTaskSnapshot

    existing = _read_snapshot(await AdvancedTaskSnapshot.filter(
        user_id=user_id,
        path_id=path_id,
        milestone=milestone,
    ).first())
    if existing:
        return existing

    lock = _snapshot_locks.setdefault((user_id, path_id, milestone), asyncio.Lock())
    async with lock:
        existing = _read_snapshot(await AdvancedTaskSnapshot.filter(
            user_id=user_id,
            path_id=path_id,
            milestone=milestone,
        ).first())
        if existing:
            return existing

        generated = await _generate_agent_task_set(user_id, profile, path, mastery_records, milestone)
        completed, _ = completed_node_count(path)
        node = _current_node(path)
        try:
            snapshot = await AdvancedTaskSnapshot.create(
                user_id=user_id,
                path_id=path_id,
                milestone=milestone,
                completed_nodes=completed,
                current_node_id=node.get("id"),
                task_json={"tasks": generated["tasks"], "summary": generated["summary"]},
                source=generated["source"],
                generation_error=generated["error"],
            )
        except Exception as exc:
            # A second worker may win the unique milestone row between the read and create.
            logger.warning("advanced snapshot create race user_id=%s path_id=%s milestone=%s error=%s", user_id, path_id, milestone, type(exc).__name__)
            existing = _read_snapshot(await AdvancedTaskSnapshot.filter(
                user_id=user_id,
                path_id=path_id,
                milestone=milestone,
            ).first())
            if existing:
                return existing
            raise

        # The current milestone is the only task set shown to the learner.
        await AdvancedTaskSnapshot.filter(user_id=user_id, path_id=path_id).exclude(milestone=milestone).delete()
        return _read_snapshot(snapshot) or {
            "tasks": generated["tasks"],
            "summary": generated["summary"],
            "source": generated["source"],
            "generation_error": generated["error"],
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
        milestone = advanced_milestone(completed)
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
            "unlock_nodes": ADVANCED_UNLOCK_NODES,
            "completed_nodes": completed,
            "current": milestone,
            "next": max(ADVANCED_UNLOCK_NODES, (milestone + 1) * ADVANCED_MILESTONE_SIZE),
            "remaining": max(0, ADVANCED_UNLOCK_NODES - completed) if completed < ADVANCED_UNLOCK_NODES else 0,
        }

        if completed < ADVANCED_UNLOCK_NODES:
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
                "advanced task snapshot unavailable user_id=%s path_id=%s milestone=%s",
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
        try:
            await _attach_practice_status(user_id, int(current_path["path_id"]), tasks)
        except Exception:
            # 会话状态是增强信息；即使旧部署还没创建会话表，也不能阻断任务入口。
            logger.exception(
                "advanced practice status unavailable user_id=%s path_id=%s",
                user_id,
                current_path.get("path_id"),
            )
        active_task = next((item for item in tasks if item.get("is_recommended")), tasks[0] if tasks else None)

        return {
            "status": "ready",
            "profile": profile,
            "path": path_payload,
            "milestone": milestone_payload,
            "task_source": snapshot["source"],
            "task_summary": snapshot["summary"],
            "task_generated_at": snapshot["generated_at"],
            "tasks": tasks,
            "task": active_task,
        }
