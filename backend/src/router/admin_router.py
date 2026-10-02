from fastapi import APIRouter, HTTPException, Depends, Body, Request, Query
from typing import Literal

from backend.src.service.admin import service as admin_service
from backend.src.service.resource.library import ResourceLibraryService as ResourceService
from backend.src.schemas.admin import (ResetPasswordRequest, DeleteUserRequest, ActivityQuery,
    PushResourceRequest, UpdateResourceRequest, ReviewResourceRequest, UpdateAccountRequest)
from backend.src.service.admin import activity, assignments
from backend.src.utils.jwt import get_user_id_from_token
from backend.src.utils.admin_check import is_admin
from backend.src.models.knowledgemodel import KnowledgeVector


def _knowledge_base_title_prefix(title: str) -> str:
    return str(title or "").split(" (")[0].split("锛堢")[0].strip()

router = APIRouter(prefix = "/admin", tags = ["管理员"])


async def _require_admin(user_id : int = Depends(get_user_id_from_token)) -> int:
    if not await is_admin(user_id):
        raise HTTPException(403, "需要管理员权限")
    return user_id


@router.get("/resource-catalog")
async def list_resource_catalog(
    search: str = Query("", max_length=100),
    visibility: Literal["public", "private", "pending", "rejected"] | None = None,
    pushable: bool = False,
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    admin_id: int = Depends(_require_admin),
):
    result = await admin_service.list_resource_catalog({"search": search, "visibility": visibility,
        "pushable": pushable, "page": page, "size": size})
    return {"code": 200, "data": result}


@router.get("/resources/{resource_id}/detail")
async def get_resource_detail(resource_id: int, admin_id: int = Depends(_require_admin)):
    return {"code": 200, "data": await admin_service.get_resource_detail(resource_id)}


@router.get("/activity")
async def list_activity(
    days: int = Query(7, ge=7, le=30), search: str = Query("", max_length=100),
    activity_filter: Literal["all", "active", "inactive"] = Query("all", alias="activity"),
    sort: Literal["study_seconds", "active_days"] = "study_seconds",
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    admin_id: int = Depends(_require_admin),
):
    if days not in (7, 30):
        raise HTTPException(422, "统计范围仅支持 7 天或 30 天")
    options = ActivityQuery(days=days, search=search, activity=activity_filter, sort=sort, page=page, size=size)
    return {"code": 200, "data": await activity.list_activity(options)}


@router.get("/users/{user_id}/activity")
async def get_user_activity(user_id: int, admin_id: int = Depends(_require_admin)):
    return {"code": 200, "data": await activity.get_user_activity(user_id)}


@router.put("/users/{user_id}")
async def update_account(user_id: int, data: UpdateAccountRequest, admin_id: int = Depends(_require_admin)):
    return {"code": 200, "data": await admin_service.update_account(user_id, data)}


@router.post("/resource-pushes")
async def push_resource(data: PushResourceRequest, admin_id: int = Depends(_require_admin)):
    return {"code": 200, "data": await assignments.push_resource(admin_id, data)}


@router.get("/resources")
async def list_resources(
    visibility: str | None = None,
    admin_id: int = Depends(_require_admin),
):
    try:
        records = await ResourceService.admin_list_resources(visibility=visibility)
        return {"code": 200, "msg": "success", "data": records}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "服务器错误")


@router.get("/resources/pending")
async def list_pending_resources(admin_id: int = Depends(_require_admin)):
    try:
        records = await ResourceService.admin_list_resources(visibility="pending", include_content=True)
        return {"code": 200, "msg": "success", "data": records}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "服务器错误")


@router.post("/resources/applications/{resource_id}/approve")
async def approve_resource_application(resource_id: int, admin_id: int = Depends(_require_admin)):
    try:
        record = await admin_service.review_resource(resource_id, True)
        if record is None:
            return {"code": 404, "msg": "资源不存在"}
        return {"code": 200, "msg": "success", "data": record}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "服务器错误")


@router.post("/resources/applications/{resource_id}/reject")
async def reject_resource_application(resource_id: int, data: ReviewResourceRequest, admin_id: int = Depends(_require_admin)):
    try:
        record = await admin_service.review_resource(resource_id, False, data.reason)
        if record is None:
            return {"code": 404, "msg": "资源不存在"}
        reason = data.reason
        return {"code": 200, "msg": reason or "success", "data": record}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "服务器错误")


@router.put("/resources/{resource_id}")
async def update_resource(resource_id: int, data: UpdateResourceRequest, admin_id: int = Depends(_require_admin)):
    try:
        record = await ResourceService.admin_update_resource(resource_id, data.model_dump())
        if record is None:
            return {"code": 404, "msg": "资源不存在"}
        return {"code": 200, "msg": "success", "data": record}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "服务器错误")


@router.delete("/resources/{resource_id}")
async def delete_resource(resource_id: int, admin_id: int = Depends(_require_admin)):
    try:
        ok = await ResourceService.admin_delete_resource(resource_id)
        if not ok:
            return {"code": 404, "msg": "资源不存在"}
        return {"code": 200, "msg": "删除成功"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "服务器错误")


async def _read_import_payload(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        payload = dict(form)
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            raw = await upload.read()
            payload["filename"] = getattr(upload, "filename", "")
            if not payload.get("content"):
                payload["content"] = raw.decode("utf-8", errors="ignore")
        return payload
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


@router.post("/resources/import")
async def import_base_resource(request: Request, admin_id: int = Depends(_require_admin)):
    try:
        payload = await _read_import_payload(request)
        record = await ResourceService.admin_import_base_resource(admin_id, payload)
        if record is None:
            return {"code": 404, "msg": "管理员不存在"}
        return {"code": 200, "msg": "success", "data": record}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "服务器错误")


@router.get("/users")
async def list_users(admin_id : int = Depends(_require_admin)):
    try :
        users = await admin_service.list_users()
        return {"code" : 200, "msg" : "success", "data" : users}
    except HTTPException :
        raise
    except Exception :
        raise HTTPException(500, "服务器错误")


@router.delete("/users/{user_id}")
async def delete_user(
    user_id : int,
    admin_id : int = Depends(_require_admin),
    data : DeleteUserRequest = Body(...)
):
    if not data.confirm :
        return {"code" : 400, "msg" : "请确认删除"}
    try :
        msg = await admin_service.delete_user(user_id)
        if "不存在" in msg or "不能删除" in msg :
            return {"code" : 403, "msg" : msg}
        return {"code" : 200, "msg" : msg}
    except HTTPException :
        raise
    except Exception :
        raise HTTPException(500, "服务器错误")


@router.post("/users/{user_id}/reset_password")
async def reset_password(
    user_id : int,
    admin_id : int = Depends(_require_admin),
    data : ResetPasswordRequest = Body(...)
):
    try :
        msg = await admin_service.reset_password(user_id, data.new_password)
        if "不存在" in msg :
            return {"code" : 404, "msg" : msg}
        return {"code" : 200, "msg" : msg}
    except HTTPException :
        raise
    except Exception :
        raise HTTPException(500, "服务器错误")


@router.get("/knowledge_base/pending")
async def admin_pending_knowledge_base(admin_id: int = Depends(_require_admin)):
    from backend.src.utils.knowledge_base import list_grouped
    try:
        records = await list_grouped(visibility="pending")
        return {"code": 200, "msg": "success", "data": records}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "server error")


@router.post("/knowledge_base/{doc_id}/approve")
async def approve_knowledge_base_application(doc_id: str, admin_id: int = Depends(_require_admin)):
    try:
        record = await KnowledgeVector.filter(doc_id=doc_id, visibility="pending").first()
        if not record:
            return {"code": 404, "msg": "not found"}
        title_prefix = _knowledge_base_title_prefix(record.title)

        # 逐个更新，避免 Tortoise ORM filter+update 在部分后端的兼容问题
        matched = await KnowledgeVector.filter(
            title__startswith=title_prefix, user_id=record.user_id, visibility="pending"
        ).all()
        for r in matched:
            r.visibility = "public"
            await r.save()

        return {"code": 200, "msg": "success", "data": {"doc_id": doc_id, "visibility": "public"}}
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("approve_knowledge_base_application 失败 doc_id=%s", doc_id)
        raise HTTPException(500, f"server error: {e}")


@router.post("/knowledge_base/{doc_id}/reject")
async def reject_knowledge_base_application(doc_id: str, admin_id: int = Depends(_require_admin)):
    try:
        record = await KnowledgeVector.filter(doc_id=doc_id, visibility="pending").first()
        if not record:
            return {"code": 404, "msg": "not found"}
        title_prefix = _knowledge_base_title_prefix(record.title)

        matched = await KnowledgeVector.filter(
            title__startswith=title_prefix, user_id=record.user_id, visibility="pending"
        ).all()
        for r in matched:
            r.visibility = "rejected"
            await r.save()

        return {"code": 200, "msg": "success", "data": {"doc_id": doc_id, "visibility": "rejected"}}
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("reject_knowledge_base_application 失败 doc_id=%s", doc_id)
        raise HTTPException(500, f"server error: {e}")


@router.put("/knowledge_base/{doc_id}")
async def update_knowledge_base(doc_id: str, data: dict = Body(default_factory=dict), admin_id: int = Depends(_require_admin)):
    """管理员更新知识库条目"""
    try:
        record = await KnowledgeVector.filter(doc_id=doc_id).first()
        if not record:
            return {"code": 404, "msg": "not found"}

        if "title" in data:
            record.title = data["title"]
        if "content" in data:
            record.content = data["content"]
        if "visibility" in data:
            record.visibility = data["visibility"]
        if "category" in data or "resource_type" in data:
            cat = data.get("category") or data.get("resource_type")
            if cat in ("knowledge_point", "exercise", "textbook", "note", "case_study", "reference", "video"):
                record.category = cat

        await record.save()
        return {"code": 200, "msg": "success", "data": {"doc_id": doc_id}}
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("update_knowledge_base 失败 doc_id=%s", doc_id)
        raise HTTPException(500, f"server error: {e}")


@router.delete("/knowledge_base/{doc_id}")
async def delete_knowledge_base(doc_id: str, admin_id: int = Depends(_require_admin)):
    """管理员删除知识库条目"""
    try:
        record = await KnowledgeVector.filter(doc_id=doc_id).first()
        if not record:
            return {"code": 404, "msg": "not found"}
        await record.delete()
        return {"code": 200, "msg": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("delete_knowledge_base 失败 doc_id=%s", doc_id)
        raise HTTPException(500, f"server error: {e}")


@router.get("/knowledge_base")
async def admin_knowledge_base(admin_id : int = Depends(_require_admin)):
    try :
        records = await admin_service.list_knowledge_base()
        return {"code" : 200, "msg" : "success", "data" : records}
    except HTTPException :
        raise
    except Exception :
        raise HTTPException(500, "服务器错误")
