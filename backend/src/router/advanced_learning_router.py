"""Goal-oriented advanced learning and practice-session endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.src.service.advanced.reference_docs import collect as collect_reference_docs
from backend.src.service.advanced.service import AdvancedLearningService
from backend.src.service.advanced.practice_service import AdvancedPracticeService
from backend.src.utils.framework_docs import catalogue
from backend.src.utils.jwt import get_user_id_from_token

router = APIRouter(prefix="/learning/advanced", tags=["进阶学习"])


class PracticeSessionRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    path_id: int = Field(gt=0)
    node_id: int = Field(gt=0)
    task: dict[str, Any] = Field(default_factory=dict)


class ReferenceDocsRequest(BaseModel):
    # 框架标识（见 utils/framework_docs.py 的 FRAMEWORKS）。上限 8 是防呆：
    # 请求体是客户端给的，而每个标识会展开成 3-6 次出网抓取。
    frameworks: list[str] = Field(default_factory=list, max_length=8)
    # 教练自己找的官方文档页地址 —— 表里没有的技术走这条（见 ai_core/tools/workspace.py）。
    # 上限同样是防呆：**这条接口是登录用户的出网抓取口子**，不封顶等于给了个随便放大的
    # 放大器。抓内网那条闸在 web_page.check_fetchable_url，逐跳拦，和这里无关。
    urls: list[str] = Field(default_factory=list, max_length=8)


class PracticeStateRequest(BaseModel):
    # 这里只收消息体。早点期的客户端还会发 `current_phase` / `completed_phase_ids` /
    # `deliverable_state` 这类阶段机的字段 —— pydantic 默认忽略多余键，它们会被静默丢掉，
    # 不报错也不会被存下来。这是要的行为：那套状态已经删干净了，收下来只会让人以为还在用。
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=120)
    confirmed_facts: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)


@router.get("/current")
async def get_current_advanced_task(
    refresh: bool = False,
    user_id: int = Depends(get_user_id_from_token),
):
    """Return the task snapshot for the current ten-node learning milestone.

    `refresh=true` 表示这是用户**手点**「重新同步 / 重新生成」发出来的：绕过兜底重试冷却，
    强制重跑一次生成作业。自动轮询不要带它 —— 每 3 秒一发会白烧调用。

    请求本身照样立刻返回（生成在后台跑），前端按 `task_source` 决定要不要继续轮询。
    """
    try:
        result = await AdvancedLearningService.get_current(user_id, refresh=refresh)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"code": 200, "msg": "success", "data": result}


@router.post("/practice/sessions")
async def open_practice_session(
    data: PracticeSessionRequest,
    user_id: int = Depends(get_user_id_from_token),
):
    """创建或恢复一次进阶实践会话。"""
    try:
        result = await AdvancedPracticeService.open_session(
            user_id=user_id,
            task_id=data.task_id,
            path_id=data.path_id,
            node_id=data.node_id,
            task=data.task,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"code": 200, "msg": "巩固会话已打开", "data": result}


@router.get("/practice/sessions/{session_id}")
async def get_practice_session(session_id: str, user_id: int = Depends(get_user_id_from_token)):
    """读取当前用户的进阶实践会话状态和历史消息。"""
    try:
        result = await AdvancedPracticeService.get_session(user_id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"code": 200, "msg": "success", "data": result}


@router.patch("/practice/sessions/{session_id}")
async def save_practice_session(
    session_id: str,
    data: PracticeStateRequest,
    user_id: int = Depends(get_user_id_from_token),
):
    """保存这次实践会话的对话记录。"""
    try:
        result = await AdvancedPracticeService.save_state(
            user_id,
            session_id,
            messages=data.messages,
            confirmed_facts=data.confirmed_facts,
            assumptions=data.assumptions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"code": 200, "msg": "巩固状态已保存", "data": result}


@router.post("/practice/sessions/{session_id}/end")
async def pause_practice_session(session_id: str, user_id: int = Depends(get_user_id_from_token)):
    """暂存本次巩固，不代表提交成果或完成任务。"""
    try:
        result = await AdvancedPracticeService.pause_session(user_id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"code": 200, "msg": "本次实践已暂存", "data": result}


@router.get("/reference-docs/catalogue")
async def list_reference_doc_frameworks(user_id: int = Depends(get_user_id_from_token)):
    """能取到官方文档的框架清单。

    界面拿它渲染"要哪个框架的资料"。**只给标识和名字，不给 URL** —— URL 是服务端的
    实现细节，而且前端也不需要它。
    """
    return {"code": 200, "msg": "success", "data": {"frameworks": catalogue()}}


@router.post("/reference-docs")
async def fetch_reference_docs(
    data: ReferenceDocsRequest,
    user_id: int = Depends(get_user_id_from_token),
):
    """抓这些框架的官方文档（外加教练自己给的地址），返回一组可以直接落盘的文件。

    **后端不写学生的磁盘**：学生在哪儿放这些文件由他的浏览器决定（FSA 选择目录），
    这里只把内容备好。这一点不用 `user_id` —— 内容是公开文档，跟用户无关；
    但鉴权仍然要有，否则它就成了一条对外的匿名抓取代理。
    """
    result = await collect_reference_docs(data.frameworks, data.urls)
    return {"code": 200, "msg": "success", "data": result}
