"""Goal-oriented advanced learning and practice-session endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.src.service.advanced.service import AdvancedLearningService
from backend.src.service.advanced.practice_service import AdvancedPracticeService
from backend.src.utils.jwt import get_user_id_from_token

router = APIRouter(prefix="/learning/advanced", tags=["进阶学习"])


class PracticeSessionRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    path_id: int = Field(gt=0)
    node_id: int = Field(gt=0)
    task: dict[str, Any] = Field(default_factory=dict)


class PracticeStateRequest(BaseModel):
    current_phase: str = Field(default="understand", max_length=32)
    completed_phase_ids: list[str] = Field(default_factory=list, max_length=6)
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=120)
    confirmed_facts: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class PracticeSubmitRequest(PracticeStateRequest):
    final_submission: str = Field(default="", max_length=6000)


@router.get("/current")
async def get_current_advanced_task(user_id: int = Depends(get_user_id_from_token)):
    """Return the task snapshot for the current ten-node learning milestone."""
    try:
        result = await AdvancedLearningService.get_current(user_id)
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
    """保存对话、阶段和学习者当前整理出的事实/假设。"""
    try:
        result = await AdvancedPracticeService.save_state(
            user_id,
            session_id,
            current_phase=data.current_phase,
            completed_phase_ids=data.completed_phase_ids,
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
    return {"code": 200, "msg": "本次巩固已暂存", "data": result}


@router.post("/practice/sessions/{session_id}/submit")
async def submit_practice_session(
    session_id: str,
    data: PracticeSubmitRequest,
    user_id: int = Depends(get_user_id_from_token),
):
    """提交实践方案，保存服务端评价并结束本次会话。"""
    try:
        result = await AdvancedPracticeService.submit(
            user_id,
            session_id,
            final_submission=data.final_submission,
            current_phase=data.current_phase,
            completed_phase_ids=data.completed_phase_ids,
            messages=data.messages,
            confirmed_facts=data.confirmed_facts,
            assumptions=data.assumptions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"code": 200, "msg": "方案已提交并完成评价", "data": result}
