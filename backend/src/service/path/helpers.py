"""Internal helpers for learning path services."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime

from backend.src.models.exam_model import KnowledgeMastery
from backend.src.models.path_model import PathNode, UserPathProgress
from backend.src.models.portraitmodel import User_picture
from backend.src.models.resource_model import GeneratedResource
from backend.src.models.usermodel import User
from backend.src.service.notification.service import check_and_create_node_unlocked
from backend.src.service.resource.document_quality import validate_document_chapter
from backend.src.service.resource.persistence import is_failed_generation_content
from backend.src.service.path.teaching_context import PATH_DEFAULT_RESOURCE_TYPES
from backend.src.ai_core.ppt_planner import PPT_MAX_PAGES_PER_DECK

logger = logging.getLogger(__name__)

GenerateResources = Callable[[int, int, int], Awaitable[dict]]
GenerateQuiz = Callable[..., Awaitable[dict]]
GenerateClassroom = Callable[[int, int, int], Awaitable[dict | None]]
_CLASSROOM_WARMUP_TASKS: set[asyncio.Task] = set()
_NODE_WARMUP_TASKS: set[asyncio.Task] = set()


def _resource_page_count(content: str) -> int:
    """Count PPT pages for stale-resource validation without parsing slide markup."""
    text = str(content or "").strip()
    if not text:
        return 0
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return len(parsed)
        if isinstance(parsed, dict):
            slides = parsed.get("slides") or parsed.get("pages") or parsed.get("items")
            if isinstance(slides, list):
                return len(slides)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return len([item for item in re.split(r"\n\s*---+\s*\n", text) if item.strip()])


async def check_existing_resources(
    user_id: int,
    topic: str,
    resource_types: list[str] | None = None,
):
    """Return existing resource records and missing resource types for a path node."""
    if resource_types is None:
        resource_types = list(PATH_DEFAULT_RESOURCE_TYPES)

    existing_records = []
    missing_types = []
    for resource_type in resource_types:
        record = await GeneratedResource.filter(
            user_id=user_id,
            topic=topic,
            resource_type=resource_type,
        ).first()
        if record:
            existing_records.append(record)
        else:
            missing_types.append(resource_type)
    return existing_records, missing_types


def _load_resource_ids(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    ids: list[int] = []
    for item in raw:
        try:
            rid = int(item)
        except (TypeError, ValueError):
            continue
        if rid > 0 and rid not in ids:
            ids.append(rid)
    return ids


async def get_bound_node_resources(
    progress,
    user_id: int,
    resource_types: list[str] | None = None,
    topic: str | None = None,
    teaching_context: dict | None = None,
):
    """Return resources valid for this path-node binding.

    ``UserPathProgress.resource_ids`` is the path cache.  A global same-topic
    lookup is intentionally not performed here because identical topics can
    have different teaching contracts on different paths.
    """
    if resource_types is None:
        resource_types = list(PATH_DEFAULT_RESOURCE_TYPES)
    requested_types = list(dict.fromkeys(
        str(resource_type).strip()
        for resource_type in resource_types
        if str(resource_type).strip()
    ))
    if not requested_types:
        return [], []

    if not topic and isinstance(teaching_context, dict):
        current = teaching_context.get("current")
        if isinstance(current, dict):
            topic = str(current.get("topic") or "").strip() or None

    bound_ids = _load_resource_ids(getattr(progress, "resource_ids", None))
    if not bound_ids:
        return [], requested_types

    records = [
        record
        for record in await GeneratedResource.filter(id__in=bound_ids, user_id=user_id).all()
        if not is_failed_generation_content(record.content)
    ]
    by_id = {record.id: record for record in records}
    ordered = [by_id[rid] for rid in bound_ids if rid in by_id]

    existing_records = []
    seen_types: set[str] = set()
    accepted_ids: set[int] = set()
    rejected_ids: set[int] = set()
    for record in ordered:
        resource_type = str(record.resource_type or "").strip()
        if resource_type not in requested_types:
            accepted_ids.add(record.id)
            continue
        if topic and str(record.topic or "").strip() != topic:
            rejected_ids.add(record.id)
            continue
        if resource_type == "document" and teaching_context is not None:
            quality_errors = validate_document_chapter(record.content, teaching_context)
            if quality_errors:
                rejected_ids.add(record.id)
                logger.info(
                    "路径节点文档未通过复用校验，解除绑定 resource_id=%s errors=%s",
                    record.id,
                    quality_errors,
                )
                continue
        if resource_type == "ppt" and _resource_page_count(record.content) > PPT_MAX_PAGES_PER_DECK:
            rejected_ids.add(record.id)
            logger.info(
                "路径节点 PPT 超过页数上限，解除绑定 resource_id=%s pages=%s max=%s",
                record.id,
                _resource_page_count(record.content),
                PPT_MAX_PAGES_PER_DECK,
            )
            continue
        if resource_type not in seen_types:
            existing_records.append(record)
            seen_types.add(resource_type)
        accepted_ids.add(record.id)

    # Remove stale, failed, wrong-topic, and quality-invalid IDs from this
    # node binding.  The GeneratedResource rows remain available for inspection.
    retained_ids = [
        resource_id
        for resource_id in bound_ids
        if resource_id in accepted_ids and resource_id not in rejected_ids
    ]
    if retained_ids != bound_ids:
        serialized_ids = json.dumps(retained_ids, ensure_ascii=False)
        try:
            await UserPathProgress.filter(id=progress.id, user_id=user_id).update(
                resource_ids=serialized_ids,
            )
            progress.resource_ids = serialized_ids
        except Exception:
            logger.exception(
                "清理路径节点资源绑定失败 progress_id=%s user_id=%s",
                getattr(progress, "id", None),
                user_id,
            )

    missing_types = [resource_type for resource_type in requested_types if resource_type not in seen_types]
    return existing_records, missing_types


async def update_progress_resource_ids(progress, all_ids: list[int]):
    """Persist generated resource ids and move an unlocked node into progress."""
    update_fields = {"resource_ids": json.dumps(all_ids, ensure_ascii=False)}
    if progress.node_status == "unlocked":
        update_fields["node_status"] = "in_progress"
        update_fields["started_at"] = datetime.now()
    await UserPathProgress.filter(id=progress.id).update(**update_fields)


async def reconcile_completed_prerequisites(progress_records, node_order: dict[int, int] | None = None):
    """修复线性路径中不可能的回退状态。

    后续节点已经完成，说明所有前置节点曾通过门禁。旧版复习交卷会把已完成
    节点误写回 in_progress；这里仅恢复这种有明确后继完成证据的记录。
    """
    order = node_order or {}
    records = sorted(
        list(progress_records),
        key=lambda record: order.get(record.node_id, getattr(getattr(record, "node", None), "order_index", 10**9)),
    )
    completed_later = False
    restored_ids: list[int] = []
    for record in reversed(records):
        if record.node_status == "completed":
            completed_later = True
            continue
        if completed_later and record.node_status in {"unlocked", "in_progress"}:
            record.node_status = "completed"
            record.quiz_passed = True
            if not record.completed_at:
                record.completed_at = datetime.now()
            await record.save(update_fields=["node_status", "quiz_passed", "completed_at"])
            restored_ids.append(record.node_id)
    if restored_ids:
        logger.warning("恢复被错误回退的路径节点 progress node_ids=%s", sorted(restored_ids))
    return records


async def check_resource_viewed(node_id: int, user_id: int) -> tuple[bool, int]:
    """Return whether any node resource has been viewed and the total view count."""
    progress = await UserPathProgress.filter(user_id=user_id, node_id=node_id).first()
    if not progress or not progress.resource_ids:
        return False, 0

    resource_ids = json.loads(progress.resource_ids) if progress.resource_ids else []
    if not resource_ids:
        return False, 0

    resources = await GeneratedResource.filter(id__in=resource_ids).all()
    total_views = sum(resource.view_count or 0 for resource in resources)
    return total_views > 0, total_views


async def pre_generate_node(
    path_id: int,
    node_id: int,
    user_id: int,
    generate_resources: GenerateResources,
    generate_quiz: GenerateQuiz,
    generate_classroom: GenerateClassroom | None = None,
):
    try:
        await asyncio.gather(
            generate_resources(path_id, node_id, user_id),
            generate_quiz(path_id, node_id, user_id, pre_generate=True),
        )
        # 课堂依赖资源和题目快照，二者落库后再预生成避免空上下文版本。
        if generate_classroom:
            task = asyncio.create_task(generate_classroom(path_id, node_id, user_id))
            _CLASSROOM_WARMUP_TASKS.add(task)
            task.add_done_callback(_CLASSROOM_WARMUP_TASKS.discard)
            logger.info("课堂预生成已排队 path_id=%s node_id=%s", path_id, node_id)
    except Exception:
        logger.exception("预生成节点资源/检测题/课堂失败 path_id=%s node_id=%s", path_id, node_id)


async def unlock_next_node(
    path_id: int,
    current_order: int,
    user_id: int,
    generate_resources: GenerateResources,
    generate_quiz: GenerateQuiz,
    generate_classroom: GenerateClassroom | None = None,
):
    """解锁下一节点，并为最近两个节点预生成资料、测验和互动课堂。"""
    next_node = await PathNode.filter(path_id=path_id, order_index=current_order + 1).first()
    if not next_node:
        return

    await UserPathProgress.filter(
        user_id=user_id,
        path_id=path_id,
        node_id=next_node.id,
    ).update(node_status="unlocked")

    await check_and_create_node_unlocked(user_id, next_node.topic, path_id, next_node.id)

    pre_gen_ids = [next_node.id]
    node_after = await PathNode.filter(path_id=path_id, order_index=current_order + 2).first()
    if node_after:
        pre_gen_ids.append(node_after.id)

    async def warmup_nodes() -> None:
        try:
            # 解锁接口只负责更新门禁；资料、题目和课堂继续并发预生成，不能阻塞交卷响应。
            await asyncio.gather(
                *(
                    pre_generate_node(path_id, node_id, user_id, generate_resources, generate_quiz, generate_classroom)
                    for node_id in pre_gen_ids
                )
            )
            logger.info(
                "节点预生成完成 path_id=%s user_id=%s node_ids=%s",
                path_id,
                user_id,
                pre_gen_ids,
            )
        except Exception:
            logger.exception(
                "节点预生成后台任务失败 path_id=%s user_id=%s node_ids=%s",
                path_id,
                user_id,
                pre_gen_ids,
            )

    task = asyncio.create_task(warmup_nodes(), name=f"path-node-warmup-{path_id}-{current_order + 1}")
    _NODE_WARMUP_TASKS.add(task)
    task.add_done_callback(_NODE_WARMUP_TASKS.discard)
    logger.info(
        "节点已解锁，预生成已后台排队 path_id=%s user_id=%s node_ids=%s",
        path_id,
        user_id,
        pre_gen_ids,
    )


async def update_portrait_from_mastery(user_id: int):
    """Summarize knowledge mastery and sync it into portrait traits."""
    records = await KnowledgeMastery.filter(user_id=user_id).all()
    if not records:
        return

    mastery_data = [
        {
            "tag": record.knowledge_tag,
            "level": record.mastery_level,
            "accuracy": round(record.correct_count / max(record.total_attempts, 1), 2),
        }
        for record in records
    ]

    strengths = [item["tag"] for item in mastery_data if item["level"] in ("mastered", "proficient")]
    weaknesses = [item["tag"] for item in mastery_data if item["level"] == "beginner"]
    avg_accuracy = round(sum(item["accuracy"] for item in mastery_data) / len(mastery_data), 2)
    level_map = {"beginner": 1, "learning": 2, "proficient": 3, "mastered": 4}
    avg_level = sum(level_map.get(item["level"], 1) for item in mastery_data) / len(mastery_data)
    knowbase = round(min(avg_level, 5), 1)

    user = await User.filter(id=user_id).prefetch_related("picture").first()
    if not user:
        return

    picture = await user.picture
    if not picture:
        picture = await User_picture.create()
        user.picture = picture
        await user.save()

    existing = {}
    if picture.traits:
        try:
            existing = json.loads(picture.traits)
        except (json.JSONDecodeError, TypeError):
            logger.warning("画像 traits JSON 解析失败 user_id=%s", user_id)
            existing = {}

    existing["knowledge_mastery"] = mastery_data
    existing["updated_at"] = str(datetime.now())
    existing["knowbase"] = {
        "value": str(knowbase),
        "confidence": min(0.95, 0.3 + avg_accuracy * 0.5),
        "source": "agent_inferred",
    }
    if strengths:
        existing["strengths"] = {
            "value": "、".join(strengths[:5]),
            "confidence": 0.85,
            "source": "agent_inferred",
        }
    if weaknesses:
        existing["weaknesses"] = {
            "value": "、".join(weaknesses[:5]),
            "confidence": 0.75,
            "source": "agent_inferred",
        }

    picture.traits = json.dumps(existing, ensure_ascii=False)
    await picture.save()
    try:
        from backend.src.service.chat.service import invalidate_portrait_cache
        invalidate_portrait_cache(user_id)
    except Exception:
        logger.debug("掌握度画像缓存刷新失败 user_id=%s", user_id, exc_info=True)
