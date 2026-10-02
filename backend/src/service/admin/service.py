from backend.src.models.usermodel import User
from backend.src.utils.pwintohash import get_password_hash
from fastapi import HTTPException
from tortoise.transactions import in_transaction
from backend.src.models.resource_model import GeneratedResource
from backend.src.models.notification_model import Notification
from backend.src.service.resource.metadata import resource_to_dict


async def list_users() -> list[dict]:
    users = await User.all().prefetch_related("picture")
    return [
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "university": user.university,
            "grade": user.grade,
            "major": user.major,
            "email": user.email,
            "phonenum": user.phonenum,
            "profile": user.profile,
            "has_picture": user.picture_id is not None,
            "created_at": str(user.created_at),
        }
        for user in users
    ]


async def delete_user(user_id: int) -> str:
    user = await User.filter(id=user_id).first()
    if not user:
        return "用户不存在"
    if user.role == "admin":
        return "不能删除管理员"
    username = user.username
    await user.delete()
    return f"用户 '{username}' 已删除"


async def reset_password(user_id: int, new_password: str) -> str:
    user = await User.filter(id=user_id).first()
    if not user:
        return "用户不存在"
    user.password = get_password_hash(new_password)
    await user.save()
    return f"用户 '{user.username}' 密码已重置"


async def list_knowledge_base() -> list[dict]:
    from backend.src.utils.knowledge_base import list_grouped
    return await list_grouped()


async def update_account(user_id: int, request) -> dict:
    user = await User.filter(id=user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    changes = request.model_dump()
    for field, value in changes.items():
        setattr(user, field, value)
    await user.save(update_fields=[*changes, "updated_at"])
    return {"id": user.id, **changes}


async def list_resource_catalog(options: dict) -> dict:
    query = GeneratedResource.all()
    if options.get("visibility"):
        query = query.filter(visibility=options["visibility"])
    if options.get("search"):
        query = query.filter(topic__icontains=options["search"])
    if options.get("pushable"):
        query = query.filter(visibility="public", review_passed=True)
    total = await query.count()
    records = await query.order_by("-updated_at", "-id").offset((options["page"] - 1) * options["size"]).limit(options["size"])
    return {"items": [await resource_to_dict(row) for row in records], "total": total,
            "pending": await GeneratedResource.filter(visibility="pending").count()}


async def get_resource_detail(resource_id: int) -> dict:
    record = await GeneratedResource.filter(id=resource_id).first()
    if not record:
        raise HTTPException(404, "资源不存在")
    result = await resource_to_dict(record, include_content=True)
    # The editor must receive original source, not a transformed mind-map preview.
    result["content"] = record.content
    return result


async def review_resource(resource_id: int, approved: bool, reason: str = "") -> dict:
    async with in_transaction() as connection:
        record = await GeneratedResource.filter(id=resource_id).using_db(connection).select_for_update().first()
        if not record:
            raise HTTPException(404, "资源不存在")
        if record.visibility != "pending":
            raise HTTPException(409, "该资源已不在待审核状态，请刷新列表")
        record.visibility = "public" if approved else "rejected"
        record.review_passed = approved
        await record.save(using_db=connection, update_fields=["visibility", "review_passed", "updated_at"])
        await Notification.create(
            type="resource", title="资源审核通过" if approved else "资源审核未通过",
            content=f"《{record.topic}》" + ("已公开。" if approved else f"未通过审核。{reason}"),
            target_user_id=record.user_id, target_url="/resources/mine", using_db=connection,
        )
    return await resource_to_dict(record)
