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


def _diagnosis_event(status: str, message: str, **extra) -> dict:
    """把诊断包装成一条 agent_event，让它在"智能体流程"里成为一个可见角色。

    以前这里只推 status/result，诊断在智能体工作流里完全不可见 —— 而学情诊断正是
    协同闭环的第一个角色（分析→生成→校验→决策），看不见就等于没参与。
    """
    return {
        "type": "agent_event",
        "agent_id": "diagnosis",
        "agent_name": "学情诊断智能体",
        "phase": "diagnosis",
        "status": status,
        "message": message,
        **extra,
    }


def _describe_result(result) -> str:
    """按诊断返回体拼一句人话，别只报"完成"。"""
    if not isinstance(result, dict):
        return "诊断步骤完成"
    if result.get("finished"):
        percentage = (result.get("result") or {}).get("percentage")
        return f"诊断完成，正确率 {percentage}%" if percentage is not None else "诊断完成"
    index, total = result.get("current_index"), result.get("total_questions")
    if index is not None and total:
        return f"第 {int(index) + 1}/{int(total)} 题已就绪"
    return "诊断题目已就绪"


async def _stream_diagnosis(operation, status_message: str):
    """Keep the diagnosis connection alive while the LLM generates a question.

    operation 收一个 writer，模型边写边把正文交出来（出题的那句、判分的那句），这里立刻
    转成 SSE 推给页面。以前是等整段生成完一次性返回，学生对着"正在生成回复…"干等
    几十秒；现在字是长出来的。

    keepalive 仍然照发：模型也可能一段时间一个字都不出（超时上限是 60 秒）。
    """
    queue: asyncio.Queue = asyncio.Queue()

    def writer(text: str, channel: str) -> None:
        queue.put_nowait({"type": "reply_delta", "channel": channel, "text": text})

    task = asyncio.create_task(operation(writer))
    try:
        yield _sse(_diagnosis_event("running", status_message))
        yield _sse({"type": "status", "message": status_message})
        while True:
            if task.done() and queue.empty():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=3)
            except asyncio.TimeoutError:
                # 一个字都没出来的时候才发 keepalive，免得把正在长的正文打断成心跳
                if task.done():
                    break
                yield _sse({"type": "keepalive"})
                continue
            yield _sse(item)
        result = task.result()
        yield _sse(_diagnosis_event("done", _describe_result(result)))
        yield _sse({"type": "result", "data": result})
    except asyncio.CancelledError:
        raise
    except ValueError as exc:
        yield _sse(_diagnosis_event("failed", str(exc)))
        yield _sse({"type": "error", "message": str(exc)})
    except Exception:
        logger.exception("诊断流处理失败")
        yield _sse(_diagnosis_event("failed", "诊断服务暂时不可用"))
        yield _sse({"type": "error", "message": "诊断服务暂时不可用，请稍后重试"})
    finally:
        # 正常跑完时 task 已 done，这里是个空操作；只有被取消退出时才真正接管它。
        _detach(task)
    yield _sse(done=True)


@router.post("/start/stream")
async def stream_start_diagnosis(data: StartDiagnosisRequest, user_id: int = Depends(get_user_id_from_token)):
    return StreamingResponse(
        _stream_diagnosis(
            lambda writer: start_diagnosis(user_id, data.identity, data.direction, data.goal, data.max_steps, on_delta=writer),
            "正在根据你的学习方向生成第一道诊断题…",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/answer/stream")
async def stream_answer_diagnosis(data: AnswerDiagnosisRequest, user_id: int = Depends(get_user_id_from_token)):
    return StreamingResponse(
        _stream_diagnosis(
            lambda writer: answer_diagnosis(user_id, data.session_id, data.question_id, data.answer, data.time_spent, data.max_steps, on_delta=writer),
            "正在结合你的回答调整下一道题…",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
