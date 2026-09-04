"""Build a goal-oriented advanced task from existing learning data."""

from __future__ import annotations

from typing import Any, Iterable

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
        }

        if not current_path:
            return {"status": "path_required", "profile": profile, "path": None, "tasks": [], "task": None}

        mastery_records = await KnowledgeMastery.filter(user_id=user_id).all()
        tasks = build_advanced_tasks(profile, current_path, mastery_records)

        return {
            "status": "ready",
            "profile": profile,
            "path": {
                "id": current_path.get("path_id"),
                "stage": current_path.get("stage"),
                "progress": current_path.get("progress", 0),
                "current_node_id": current_path.get("current_node_id"),
                "diagnosis": current_path.get("diagnosis") or {},
            },
            "tasks": tasks,
            # Keep the original field for clients that only render one task.
            "task": tasks[1] if len(tasks) > 1 else (tasks[0] if tasks else None),
        }
