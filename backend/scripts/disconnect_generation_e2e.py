"""端到端验证：客户端断开后，章节资源生成的作业是否活着跑完并完成绑定。

跑法（仓库根目录）：
    /f/anaconda3/envs/zhiban/python.exe backend/scripts/disconnect_generation_e2e.py

测试的是一条真实的 ASGI 链路：真 uvicorn + 真 Starlette StreamingResponse +
真的 `PathService.generate_node_resources_stream`。只把生成的下游（DB 查询、LLM）
换成假的，避免真的调模型。客户端读到第一帧后**硬关 socket**，这正是浏览器
`AbortController.abort()` 的行为。

对照项 `/inline` 是一个最小复刻（生成直接 await 在 SSE 生成器里，即改造前的形状），
用来显示框架在同样操作下确实会取消请求栈上的工作。

它是**手动跑**的脚本，不是 pytest 用例（会起真 uvicorn、关真 socket，进测试套件只会又慢又不稳），
所以放在 `backend/scripts/` 而不是 `tests/`。
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
import uvicorn  # noqa: E402

from backend.src.service.path import node_resource_jobs  # noqa: E402
from backend.src.service.path import service as path_service  # noqa: E402

PORT = 8944
GENERATE_SECONDS = 4.0

state = {"bound": [], "stream_calls": 0, "generation_completed": False, "inline_completed": False}


class FakeLock:
    def locked(self):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeQuery:
    def __init__(self, first_value=None):
        self.first_value = first_value

    async def first(self):
        return self.first_value

    def order_by(self, *_args):
        return self


def _install_fakes():
    node = SimpleNamespace(id=909, topic="文档切分")
    progress = SimpleNamespace(id=9090, node_status="unlocked")

    async def get_lock(*_args):
        return FakeLock()

    async def get_resources(*_args, **_kwargs):
        return [], ["document"]

    async def get_context(*_args):
        return {"subject": "RAG"}

    async def save_resource_ids(_progress, resource_ids):
        state["bound"].append(list(resource_ids))

    async def fake_generate_stream(**_kwargs):
        state["stream_calls"] += 1
        yield f"data: {json.dumps({'type': 'file', 'resource_id': 901, 'resource_type': 'document', 'topic': '文档切分'})}\n\n"
        # 模拟真实生成耗时：这段时间里客户端会断开。
        await asyncio.sleep(GENERATE_SECONDS)
        yield f"data: {json.dumps({'type': 'file', 'resource_id': 902, 'resource_type': 'ppt', 'topic': '文档切分'})}\n\n"
        yield f"data: {json.dumps({'done': True, 'resources': [{'resource_id': 901}, {'resource_id': 902}]})}\n\n"
        state["generation_completed"] = True

    path_service.PathNode.filter = lambda **filters: FakeQuery(node)
    path_service.UserPathProgress.filter = lambda **filters: FakeQuery(progress)
    path_service.get_node_generation_lock = get_lock
    path_service.get_bound_node_resources = get_resources
    path_service.build_node_teaching_context = get_context
    path_service.update_progress_resource_ids = save_resource_ids
    path_service.ResourceService.generate_stream = fake_generate_stream


def build_app():
    app = FastAPI()

    @app.post("/stream")
    async def stream():
        return StreamingResponse(
            path_service.PathService.generate_node_resources_stream(7, 909, 5),
            media_type="text/event-stream",
        )

    @app.post("/inline")
    async def inline():
        """对照：改造前的形状 —— 生成直接 await 在 SSE 生成器里。"""

        async def gen():
            yield "data: first\n\n"
            try:
                await asyncio.sleep(GENERATE_SECONDS)
                state["inline_completed"] = True
                yield "data: second\n\n"
            except asyncio.CancelledError:
                print("  [inline] 生成被取消了（框架行为，符合预期）")
                raise

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


async def hit_and_disconnect(path: str) -> str:
    """读一帧就硬关连接，返回读到的那一帧。"""
    reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
    writer.write(
        f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n".encode()
    )
    await writer.drain()
    first = await reader.read(400)
    await asyncio.sleep(0.8)  # 让生成进入耗时段
    writer.close()
    await writer.wait_closed()
    return first.decode(errors="replace").split("\r\n\r\n")[-1].strip()


async def main():
    _install_fakes()
    server = uvicorn.Server(uvicorn.Config(build_app(), host="127.0.0.1", port=PORT, log_level="warning"))
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        print("=" * 68)
        print("对照组 /inline —— 生成 await 在请求栈上（改造前的形状）")
        print("=" * 68)
        await hit_and_disconnect("/inline")
        for _ in range(int((GENERATE_SECONDS + 3) * 10)):
            if state["inline_completed"]:
                break
            await asyncio.sleep(0.1)
        print(f"  生成是否跑完: {state['inline_completed']}   <- 期望 False（被断了）")

        print()
        print("=" * 68)
        print("实验组 /stream —— 生成在后台作业里（本次改造）")
        print("=" * 68)
        first = await hit_and_disconnect("/stream")
        print(f"  断开前收到的第一帧: {first[:60]}")
        for _ in range(int((GENERATE_SECONDS + 5) * 10)):
            if state["generation_completed"] and node_resource_jobs.active_job_count() == 0:
                break
            await asyncio.sleep(0.1)

        print(f"  生成是否跑完: {state['generation_completed']}   <- 期望 True")
        print(f"  绑定的 id 序列: {state['bound']}")
        print(f"  生产者启动次数: {state['stream_calls']}   <- 期望 1（断开没有触发重跑）")

        ok = (
            state["generation_completed"]
            and state["bound"] == [[901], [901, 902]]
            and state["stream_calls"] == 1
            and not state["inline_completed"]
        )
        print()
        print("结论:", "通过 —— 断开只掉订阅者，作业照常跑完并增量绑定" if ok else "不通过")
        return 0 if ok else 1
    finally:
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
