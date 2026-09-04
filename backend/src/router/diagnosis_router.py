"""首次使用能力诊断接口。"""

from typing import Optional

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.src.service.diagnosis.service import answer as answer_diagnosis
from backend.src.service.diagnosis.service import start as start_diagnosis
from backend.src.utils.jwt import get_user_id_from_token

router = APIRouter(prefix="/learning/diagnosis", tags=["能力诊断"])


class StartDiagnosisRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=80)
    direction: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=160)
    max_steps: int = Field(default=3, ge=3, le=5)


class AnswerDiagnosisRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    question_id: int
    answer: str = Field(default="", max_length=2000)
    time_spent: Optional[int] = Field(default=None, ge=0)
    max_steps: int = Field(default=3, ge=3, le=5)


@router.post("/start")
async def start_diagnosis_endpoint(data: StartDiagnosisRequest, user_id: int = Depends(get_user_id_from_token)):
    try:
        result = await start_diagnosis(user_id, data.identity, data.direction, data.goal, data.max_steps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"code": 200, "msg": "success", "data": result}


@router.post("/answer")
async def answer_diagnosis_endpoint(data: AnswerDiagnosisRequest, user_id: int = Depends(get_user_id_from_token)):
    try:
        result = await answer_diagnosis(user_id, data.session_id, data.question_id, data.answer, data.time_spent, data.max_steps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"code": 200, "msg": "success", "data": result}


def _sse(payload: dict | None = None, done: bool = False) -> str:
    if done:
        return "data: [DONE]\n\n"
    return f"data: {json.dumps(payload or {}, ensure_ascii=False)}\n\n"


async def _stream_diagnosis(operation, status_message: str):
    """Keep the diagnosis connection alive while the LLM generates a question."""
    task = asyncio.create_task(operation())
    yield _sse({"type": "status", "message": status_message})
    try:
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except asyncio.TimeoutError:
                yield _sse({"type": "keepalive"})
        yield _sse({"type": "result", "data": task.result()})
    except ValueError as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception:
        yield _sse({"type": "error", "message": "诊断服务暂时不可用，请稍后重试"})
    finally:
        if not task.done():
            task.cancel()
    yield _sse(done=True)


@router.post("/start/stream")
async def stream_start_diagnosis(data: StartDiagnosisRequest, user_id: int = Depends(get_user_id_from_token)):
    return StreamingResponse(
        _stream_diagnosis(
            lambda: start_diagnosis(user_id, data.identity, data.direction, data.goal, data.max_steps),
            "正在根据你的学习方向生成第一道诊断题…",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/answer/stream")
async def stream_answer_diagnosis(data: AnswerDiagnosisRequest, user_id: int = Depends(get_user_id_from_token)):
    return StreamingResponse(
        _stream_diagnosis(
            lambda: answer_diagnosis(user_id, data.session_id, data.question_id, data.answer, data.time_spent, data.max_steps),
            "正在结合你的回答调整下一道题…",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
