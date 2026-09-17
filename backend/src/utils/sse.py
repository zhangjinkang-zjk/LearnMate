# -*- coding: utf-8 -*-
"""SSE 里"边跑边推"的公共部分：诊断和画像访谈共用。

业务侧只写一个 operation，它拿到的 writer 可以在任意时刻把正文交出来；这里负责把它
交出来的东西立刻变成帧推给前端，同时维持 keepalive 和"断连不取消业务"这两件事。
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Callable

logger = logging.getLogger(__name__)

# 内部帧类型：把 operation 的返回值从队里传出来（它不是要发给前端的帧）。
RESULT_FRAME = "_result"


def sse_frame(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 收尾帧：前端见到它就停止解析（各处的解析器都会跳过它）。
DONE_FRAME = "data: [DONE]\n\n"


async def drain_stream(
    operation: Callable,
    *,
    keepalive_event: dict | None = None,
    keepalive_seconds: float = 3.0,
    on_task: Callable | None = None,
) -> AsyncIterator[dict]:
    """跑 operation，把它边跑边交出来的帧 yield 出去，最后 yield 一个 RESULT_FRAME。

    - operation 收到一个 writer(text, channel="reply")；channel 用来区分同一轮里的多个
      气泡（比如诊断先出"判分那句话"、再出下一题）。
    - keepalive_event 为 None 表示不发心跳；模型可能几十秒一个字都不出，前端靠它区分
      "还在跑"和"卡住了"。
    - on_task 拿到刚创建的任务对象，用来把强引用留住（断连时任务不能跟着被取消）。

    异常不在这里吞：业务异常按原样抛给调用方，由它决定给前端什么文案。
    """
    queue: asyncio.Queue = asyncio.Queue()

    def writer(text: str, channel: str = "reply") -> None:
        queue.put_nowait({"type": "reply_delta", "channel": channel, "text": text})

    task = asyncio.create_task(operation(writer))
    if on_task is not None:
        on_task(task)

    while True:
        if task.done() and queue.empty():
            break
        try:
            item = await asyncio.wait_for(queue.get(), timeout=keepalive_seconds)
        except asyncio.TimeoutError:
            if task.done():
                break
            if keepalive_event is not None:
                yield keepalive_event
            continue
        yield item

    yield {"type": RESULT_FRAME, "data": task.result()}
