"""首次使用能力诊断接口。"""

from typing import Optional

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.src.service.diagnosis.service import answer as answer_diagnosis
from backend.src.service.diagnosis.service import start as start_diagnosis
from backend.src.utils.jwt import get_user_id_from_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning/diagnosis", tags=["能力诊断"])


class StartDiagnosisRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=80)
    direction: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=160)
    max_steps: int = Field(default=3, ge=3, le=5)


class AnswerDiagnosisRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    question_id: int
    answer: str = Field(min_length=1, max_length=2000)
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


# asyncio 只保留任务的弱引用；断连后要把生成任务留在进程里跑完，得自己拿住强引用。
_DETACHED_TASKS: set[asyncio.Task] = set()


def _detach(task: asyncio.Task) -> None:
    """客户端断开后让业务继续跑完并落库，而不是取消它。

    Starlette 在 http.disconnect 时取消承载这个生成器的任务，取消点就落在生成器的
    await/yield 上。如果顺手把子任务也取消掉，一次切页或刷新就会带走"正在生成的诊断题"
    或"正在落库的作答"：回来要么看到空白页，要么被 answer() 判成"该题已经提交过"而卡死。
    结果没人接收没关系 —— 它已经写进数据库，下一次请求按同一个 session 就能接着走。
    """
    if task.done():
        return
    _DETACHED_TASKS.add(task)

    def _finished(done: asyncio.Task) -> None:
        _DETACHED_TASKS.discard(done)
        if done.cancelled():
            return
        error = done.exception()
        if error:
            logger.warning("诊断后台任务异常（客户端已断开）error=%s", error)

    task.add_done_callback(_finished)


async def _stream_diagnosis(operation, status_message: str):
    """Keep the diagnosis connection alive while the LLM generates a question."""
    task = asyncio.create_task(operation())
    try:
        yield _sse({"type": "status", "message": status_message})
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except asyncio.TimeoutError:
                yield _sse({"type": "keepalive"})
        yield _sse({"type": "result", "data": task.result()})
    except asyncio.CancelledError:
        raise
    except ValueError as exc:
        yield _sse({"type": "error", "message": str(exc)})
    except Exception:
        logger.exception("诊断流处理失败")
        yield _sse({"type": "error", "message": "诊断服务暂时不可用，请稍后重试"})
    finally:
        # 正常跑完时 task 已 done，这里是个空操作；只有被取消退出时才真正接管它。
        _detach(task)
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
