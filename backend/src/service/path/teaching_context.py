"""Teaching contracts and prompt context for learning-path nodes."""

from __future__ import annotations

import json
from typing import Any


PATH_DEFAULT_RESOURCE_TYPES = ("document", "mindmap")
_TEACHING_SPEC_KEYS = (
    "module",
    "cognitive_level",
    "learning_goal",
    "key_points",
    "micro_example",
)


def _load_json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unique_texts(values: Any, limit: int = 8) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if values else []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def normalize_teaching_spec(
    value: Any = None,
    *,
    node: dict | None = None,
    planned: dict | None = None,
) -> dict:
    """Return a complete teaching spec while preserving old path compatibility."""
    node = node or {}
    planned = planned or {}
    stored = _load_json_dict(value)
    topic = str(
        node.get("topic")
        or planned.get("topic")
        or stored.get("topic")
        or "当前知识点"
    ).strip()

    def choose(key: str, default: str = "") -> str:
        for source in (stored, planned, node):
            candidate = str(source.get(key) or "").strip()
            if candidate:
                return candidate
        return default

    key_points = _unique_texts(
        stored.get("key_points")
        or planned.get("key_points")
        or node.get("key_points")
        or node.get("knowledge_tags")
        or [topic]
    )
    return {
        "module": choose("module", "基础讲解"),
        "cognitive_level": choose("cognitive_level", "理解"),
        "learning_goal": choose(
            "learning_goal",
            choose("description", f"能够解释并应用「{topic}」的核心知识"),
        ),
        "key_points": key_points or [topic],
        "micro_example": choose(
            "micro_example",
            f"用一个具体例子说明「{topic}」解决了什么问题",
        ),
    }


def attach_teaching_specs(nodes: list[dict], topic_outline: list[dict]) -> list[dict]:
    """Merge planner intent into executor nodes by stable order/topic matching."""
    outline_by_order = {index: item for index, item in enumerate(topic_outline, 1)}
    outline_by_topic = {
        str(item.get("topic") or "").strip(): item
        for item in topic_outline
        if str(item.get("topic") or "").strip()
    }
    merged: list[dict] = []
    for fallback_order, item in enumerate(nodes, 1):
        node = dict(item)
        try:
            order_index = int(node.get("order_index") or fallback_order)
        except (TypeError, ValueError):
            order_index = fallback_order
        planned = outline_by_topic.get(
            str(node.get("topic") or "").strip()
        ) or outline_by_order.get(order_index, {})
        node["order_index"] = order_index
        node["teaching_spec"] = normalize_teaching_spec(
            node.get("teaching_spec"),
            node=node,
            planned=planned,
        )
        merged.append(node)
    return merged


def _node_scope(node: Any) -> dict:
    node_data = {
        "topic": getattr(node, "topic", "") or "",
        "knowledge_tags": _load_json_list(getattr(node, "knowledge_tags", None)),
    }
    spec = normalize_teaching_spec(
        getattr(node, "teaching_spec", None),
        node=node_data,
    )
    return {
        "order_index": int(getattr(node, "order_index", 0) or 0),
        "topic": node_data["topic"],
        "learning_goal": spec["learning_goal"],
        "key_points": spec["key_points"],
    }


def _load_json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def compose_node_teaching_context(
    path: Any,
    current_node: Any,
    all_nodes: list[Any],
    learner_context: dict | None = None,
) -> dict:
    """Compose a bounded, serializable contract used by document and mind-map prompts."""
    ordered = sorted(all_nodes, key=lambda item: int(getattr(item, "order_index", 0) or 0))
    current_order = int(getattr(current_node, "order_index", 0) or 0)
    current_scope = _node_scope(current_node)
    current_scope["teaching_spec"] = normalize_teaching_spec(
        getattr(current_node, "teaching_spec", None),
        node={
            "topic": getattr(current_node, "topic", ""),
            "knowledge_tags": _load_json_list(getattr(current_node, "knowledge_tags", None)),
        },
    )

    previous_scopes = [_node_scope(node) for node in ordered if int(getattr(node, "order_index", 0) or 0) < current_order]
    next_scopes = [_node_scope(node) for node in ordered if int(getattr(node, "order_index", 0) or 0) > current_order]
    return {
        "subject": str(getattr(path, "subject", "") or "当前学科"),
        "difficulty": str(getattr(path, "difficulty", "medium") or "medium"),
        "position": {"current": current_order, "total": len(ordered)},
        "current": current_scope,
        "previous": previous_scopes[-1] if previous_scopes else None,
        "next": next_scopes[0] if next_scopes else None,
        "covered_scope": previous_scopes,
        "reserved_scope": next_scopes,
        "learner": learner_context or {},
    }


async def _load_learner_context(user_id: int) -> dict:
    from backend.src.models.usermodel import User

    user = await User.filter(id=user_id).first()
    if not user:
        return {}

    result = {
        "major": str(user.major or "").strip(),
        "grade": str(user.grade or "").strip(),
    }
    picture = await user.picture
    if picture:
        traits = _load_json_dict(picture.traits)
        onboarding = traits.get("onboarding") if isinstance(traits.get("onboarding"), dict) else {}
        result.update({
            "identity": str(onboarding.get("identity") or "").strip(),
            "direction": str(onboarding.get("direction") or "").strip(),
            "goal": str(onboarding.get("goal") or picture.learning_goal or "").strip(),
            "cognition": str(picture.cognition or "").strip(),
            "profile_summary": str(picture.profile_summary or "").strip()[:500],
        })
    return {key: value for key, value in result.items() if value}


async def build_node_teaching_context(path_id: int, node_id: int, user_id: int) -> dict:
    """Load authoritative path boundaries and current learner context from storage."""
    from backend.src.models.path_model import LearningPath, PathNode

    path = await LearningPath.filter(id=path_id).first()
    current_node = await PathNode.filter(id=node_id, path_id=path_id).first()
    if not path or not current_node:
        return {}
    all_nodes, learner = await _gather_context_parts(path_id, user_id)
    return compose_node_teaching_context(path, current_node, all_nodes, learner)


async def _gather_context_parts(path_id: int, user_id: int) -> tuple[list[Any], dict]:
    import asyncio

    from backend.src.models.path_model import PathNode

    nodes_task = PathNode.filter(path_id=path_id).order_by("order_index").all()
    learner_task = _load_learner_context(user_id)
    return await asyncio.gather(nodes_task, learner_task)


def format_teaching_context(context: dict | None) -> str:
    if not context:
        return "暂无路径节点教学上下文"
    return json.dumps(context, ensure_ascii=False, indent=2)


def teaching_spec_payload(value: Any, *, node: dict | None = None) -> dict:
    """Normalize a persisted spec for API payloads and old rows."""
    return normalize_teaching_spec(value, node=node)


def dump_teaching_spec(value: Any, *, node: dict | None = None, planned: dict | None = None) -> str:
    spec = normalize_teaching_spec(value, node=node, planned=planned)
    return json.dumps({key: spec[key] for key in _TEACHING_SPEC_KEYS}, ensure_ascii=False)
