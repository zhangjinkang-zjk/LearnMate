from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from backend.src.models.admin_model import ResourceAssignment
from backend.src.models.notification_model import Notification
from backend.src.models.resource_model import GeneratedResource
from backend.src.models.usermodel import User


async def push_resource(admin_id: int, request) -> dict:
    """Commit task and notification together; repeated pushes do not create duplicate tasks."""
    async with in_transaction() as connection:
        resource = await GeneratedResource.filter(id=request.resource_id).using_db(connection).select_for_update().first()
        if not resource:
            raise HTTPException(404, "资源不存在")
        if resource.visibility != "public" or not resource.review_passed:
            raise HTTPException(409, "只能推送已审核通过的公开资源")
        user_ids = sorted(set(request.user_ids))
        found = await User.filter(id__in=user_ids).using_db(connection).values_list("id", flat=True)
        if len(found) != len(user_ids):
            raise HTTPException(404, "部分用户不存在，请刷新账号列表")
        created_count = 0
        for user_id in user_ids:
            assignment, created = await ResourceAssignment.get_or_create(
                user_id=user_id, resource_id=resource.id, using_db=connection,
                defaults={"assigned_by_id": admin_id, "title": resource.topic, "message": request.message},
            )
            if not created:
                continue
            await Notification.create(
                type="resource", title="管理员为你推荐了学习资源",
                content=f"《{resource.topic}》已加入学习任务。{request.message}",
                target_url=f"/learning/assignments?task={assignment.id}",
                target_user_id=user_id, using_db=connection,
            )
            created_count += 1
    return {"created": created_count, "skipped": len(user_ids) - created_count}


def serialize_assignment(record) -> dict:
    resource = record.resource if record.resource_id else None
    return {
        "id": record.id, "title": record.title, "message": record.message,
        "resource_id": record.resource_id,
        "resource_type": resource.resource_type if resource else None,
        "is_available": bool(resource and resource.visibility == "public"),
        "created_at": record.created_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


async def list_assignments(user_id: int) -> list[dict]:
    records = await ResourceAssignment.filter(user_id=user_id).order_by("-created_at").prefetch_related("resource")
    return [serialize_assignment(record) for record in records]


async def complete_assignment(user_id: int, assignment_id: int) -> dict:
    record = await ResourceAssignment.filter(id=assignment_id, user_id=user_id).prefetch_related("resource").first()
    if not record:
        raise HTTPException(404, "学习任务不存在")
    if not record.resource_id or record.resource.visibility != "public":
        raise HTTPException(409, "资源已下架，暂时无法完成任务")
    if not record.completed_at:
        record.completed_at = datetime.now(timezone.utc)
        await record.save(update_fields=["completed_at"])
    return serialize_assignment(record)
