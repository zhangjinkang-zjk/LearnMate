"""Resource difficulty matching helpers for the learning overview."""

from __future__ import annotations

from typing import Any

from backend.src.service.path.difficulty import clamp_difficulty_score, derive_difficulty_score


_RESOURCE_DIFFICULTY_OFFSETS = {
    "document": 0.0,
    "reading": 0.0,
    "mindmap": -0.05,
    "ppt": -0.05,
    "video": -0.15,
    "external_video": -0.15,
    "template": 0.1,
    "code": 0.15,
    "exercise": 0.2,
    "case": 0.25,
}


def _difficulty_to_percent(score: float) -> int:
    """Map the shared 1-10 difficulty scale to the chart's 0-100 scale."""
    return round(20 + ((score - 1.0) / 9.0) * 70)


def _match_status(difficulty: int, user_level: int | None) -> tuple[str, int | None]:
    if user_level is None:
        return "unknown", None
    gap = difficulty - user_level
    if gap >= 18:
        status = "too_hard"
    elif gap <= -18:
        status = "too_easy"
    else:
        status = "well_matched"
    return status, max(0, min(100, round(100 - abs(gap) * 2.5)))


def build_resource_difficulty_match(
    nodes: list[dict[str, Any]],
    user_level: float | int | None,
) -> list[dict[str, Any]]:
    """Flatten path-bound resources into chart points with a match judgement."""
    ordered_nodes = sorted(nodes or [], key=lambda item: item.get("order_index", 0))
    normalized_user_level = None
    if user_level is not None:
        try:
            normalized_user_level = max(0, min(100, round(float(user_level))))
        except (TypeError, ValueError):
            normalized_user_level = None

    points: list[dict[str, Any]] = []
    seen_resource_ids: set[int] = set()
    for node_index, node in enumerate(ordered_nodes, 1):
        node_score = clamp_difficulty_score(node.get("difficulty_score"))
        if node_score is None:
            teaching_spec = node.get("teaching_spec") if isinstance(node.get("teaching_spec"), dict) else {}
            tags = node.get("knowledge_tags") if isinstance(node.get("knowledge_tags"), list) else []
            prerequisites = node.get("prerequisites") if isinstance(node.get("prerequisites"), list) else []
            node_score = derive_difficulty_score(
                order_index=node_index,
                total_nodes=len(ordered_nodes),
                cognitive_level=str(teaching_spec.get("cognitive_level") or ""),
                module=str(teaching_spec.get("module") or ""),
                key_points_count=len(teaching_spec.get("key_points") or tags),
                prerequisite_count=len(prerequisites),
            )

        for resource in node.get("resources") or []:
            if not isinstance(resource, dict):
                continue
            raw_id = resource.get("resource_id", resource.get("id"))
            try:
                resource_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if resource_id in seen_resource_ids:
                continue
            seen_resource_ids.add(resource_id)

            resource_type = str(resource.get("resource_type") or "document")
            adjusted_score = max(1.0, min(10.0, node_score + _RESOURCE_DIFFICULTY_OFFSETS.get(resource_type, 0.0)))
            difficulty = _difficulty_to_percent(adjusted_score)
            status, match_score = _match_status(difficulty, normalized_user_level)
            points.append({
                "resource_id": resource_id,
                "title": resource.get("title") or resource.get("topic") or "未命名资源",
                "resource_type": resource_type,
                "node_id": node.get("id"),
                "node_title": node.get("title") or node.get("topic") or "未命名节点",
                "order_index": node.get("order_index", node_index),
                "difficulty_score": difficulty,
                "user_level": normalized_user_level,
                "match_score": match_score,
                "status": status,
            })
    return points
