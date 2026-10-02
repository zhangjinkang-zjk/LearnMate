# -*- coding: utf-8 -*-
"""在 **zhiban 环境**里跑完一个场景的全部轮次，把教练的回复交给调用方。

     stdin  ← JSON  {"id": "...", "task": {...} | null, "turns": [{"student": "...", "workspace": {...}}, ...]}
     argv[1] ← 结果写到这里（**不写 stdout**：import backend 时 llm_config 会往
               stdout 打启动日志，走 stdout 会被日志污染成非法 JSON）

**它是子进程，不是被 import 的模块。** 调用方（persona_eval.py）只能通过进程边界说话。

## 跑的是**真的那条路**：`stream_classroom_chat`

    stream_classroom_chat(...)      ← 生产入口本身，不是它的某个片段
      ├ get_or_create_classroom_agent → **真读库**：用户行、UserAgent 行的建与查
      ├ _build_classroom_path_context → 真拼上下文（PathNode 查询 + 任务账本 + 工作区）
      ├ ChatHistory.create / brain.hydrate_history → 真记录、真恢复历史
      ├ brain.stream(...)             ← 生产自己的流：astream_events → `_frame_from_event`
      │                                 帧跟前端看到的**一模一样**
      └ _sse(...)                     ← 生产自己的 SSE 包装，这里把 data: 行解回来

以前这里是自己 `Brain(...)` + `_build_agent()` 拼一个教练出来，persona 和工具表都取代码
里的常量。那样测不到**取这两样的那一步** —— 而 `service/agent/service._ALLOWED_TOOLS`
那个 bug（教练的工具在新库上被静默滤成 5 个）就住在那里，那条路跑一百遍也看不见它。
库里那几行由 `subject.py` 负责建和删。

## 还是被固定的东西（**每一处都有理由，改之前先读**）

1. **工具背后那份世界**（`fixtures.FIXED_WORLD`）：`web_search` 走博查按次计费；
   `search_knowledge_base` / `read_portrait` / `search_memory` / `get_used_history`
   要读库，而评估不该拿合成学生的空库去冒充"查过了"。判据判的是教练怎么说话、
   怎么选工具，工具背后那份数据是布景。

2. **画像后处理**（`schedule_post_chat_enrichment`）被打桩成空操作：它在**后台**再发
   模型调用，会跑在整轮评估之后、把成本和时间变成不可比，而且会给合成学生写出一份
   画像。它不参与"教练这一轮说了什么"。

3. **开场那一轮**（`scenario="practice_opening"`）不跑：剧本是按"学生先开口"写的，
   加一轮开场会改变每个场景的起点，和已有结果不可比。

4. **路由层**（`path_router.classroom_chat` 的 `_assert_path_access` 和
   `StreamingResponse`）不在里面：那两层是鉴权和传输，评估测的是 service。
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from langchain_core.tools import StructuredTool  # noqa: E402

from backend.src.ai_core.brain import TOOL_REGISTRY, Brain  # noqa: E402
from backend.src.service.path import classroom_chat  # noqa: E402
from backend.src.service.path.classroom_chat import stream_classroom_chat  # noqa: E402
from backend.src.utils.database import close_db, init_db  # noqa: E402
from eval import subject as subject_module  # noqa: E402
from eval.fixtures import FIXED_WORLD  # noqa: E402

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 3.0

# 学生发言走这个 scenario（开场是 practice_opening，见模块开头第 3 条）。
PRACTICE_SCENARIO = "practice"

# 模型把工具调用**当成文本吐出来**时会留下的痕迹。真 agent 不该有这些 ——
# 有就说明这一轮的"回复"其实是它没调成的调用请求。
_LEAKED_TOOL_CALL_MARKERS = ("<tool_call", "</tool_call", "tool_call>", "<function=", "<|tool")

# 这一轮模型实际收到的路径上下文（由 `_capture_stream_input` 记下来）。
# **只有一轮在跑，所以用一个全局字典够了** —— 并发跑多轮的话这里要换成 contextvars。
_captured: dict = {}


# ═══════════════════════════════════════
#  固定的世界：换掉"执行"，留下"名字和形状"
# ═══════════════════════════════════════

def _fixed_tool(real_tool, name: str) -> StructuredTool:
    """拿**真工具**的名字、描述、参数 schema，只把执行换成写死的返回。

    这三样一样，模型看到的工具表和在生产里看到的就是同一份 —— "该不该调、调哪个、
    参数怎么写"全部由它真决定。换掉的只有那个工具背后的世界。
    """
    fixed = FIXED_WORLD[name]

    async def _run(**kwargs):
        return fixed(kwargs) if callable(fixed) else fixed

    return StructuredTool(
        name=real_tool.name,
        description=real_tool.description,
        args_schema=real_tool.args_schema,
        coroutine=_run,
    )


def _install_fixed_world() -> list[str]:
    """把 `FIXED_WORLD` 里点名的工具换成固定实现。返回换掉了哪几个。

    **改的是这个进程自己的 `TOOL_REGISTRY`** —— 子进程，跟跑着的后端不是一回事。
    """
    real_factories = dict(TOOL_REGISTRY)
    replaced: list[str] = []
    for name in FIXED_WORLD:
        factory = real_factories.get(name)
        if factory is None:
            continue      # 表里没这个名字就当没写（工具改名时这里不该炸）
        replaced.append(name)

        def patched(uid, gid, _name=name, _factory=factory):
            return _fixed_tool(_factory(uid, gid), _name)

        TOOL_REGISTRY[name] = patched
    return replaced


def _silence_post_chat_enrichment() -> None:
    """把画像后处理打桩成空操作（理由见模块开头第 2 条）。

    打的是**这个进程里 `classroom_chat` 那个模块的名字**，不是 `service.chat` 里的原函数 ——
    `stream_classroom_chat` 是在模块自己的命名空间里找它的。

    **桩必须是同步函数**：生产那边是 `schedule_post_chat_enrichment(...)` 直接调、不 await 的
    （它自己内部起后台任务）。换成一个 `async def` 的话每次调用都会造出一个没人 await 的
    协程，日志里冒一串 RuntimeWarning，而真正的问题会被这串噪音盖住。
    """
    def _noop(*args, **kwargs):
        return None

    classroom_chat.schedule_post_chat_enrichment = _noop


def _capture_stream_input() -> None:
    """记下每一轮 `brain.stream` 真正收到的 `path_context`。

    **评估器必须看到模型看到的那一份。** 判据里有"他有没有对看不到的文件瞎猜"这条 ——
    判官不知道上下文里有什么的话，这条必然误判（第一次跑就是这么栽的，见
    `persona_eval._user_turn_text` 的注释）。

    这里选择**截住真正传进去的那个值**，而不是照着参数再调一遍
    `_build_classroom_path_context` 复算：复算要靠"同一个输入必然得到同一个输出"这个假设，
    而这里根本不需要假设。
    """
    original = Brain.stream

    async def _stream(self, message, *args, **kwargs):
        _captured["path_context"] = kwargs.get("path_context") or ""
        _captured["prompt"] = message
        async for frame in original(self, message, *args, **kwargs):
            yield frame

    Brain.stream = _stream


# ═══════════════════════════════════════
#  学生这一轮的输入
# ═══════════════════════════════════════

def _practice_segment(task: dict, workspace: object, scenario_id: str) -> dict:
    """学生这一轮发上去的 segment —— 形状照抄**现在**的 `practiceSegment()`。

    ## 这里原本是错的，记下来免得改回去

    原来它拼的是 `brief / problem / 重点能力：{focus} / 验收标准：{criteria}`，注释写着
    "照抄前端的 `taskScriptParts()`"。**但前端早就把那一份删了**：`PracticeDialogue.vue` 的
    `practiceSegment()` 现在只发 `script: clientChapterSummary()`，也就是「主讲材料摘要：…」
    或「当前没有可用主讲材料」，任务说明一个字都不拼（前端那段注释写明了原因：同一份任务在
    教练眼前出现两套说法，它就照着表格那套念给学生听）。

    而服务端会把 `script` **原文**渲染进上下文（`classroom_chat._compose_user_prompt`：练习线
    直接 `lines.append(script)`）。于是评估桥喂进去的「验收标准：…」真的会被教练读到，
    教练复述出来，判据「说话像同行」的步骤 1（别念栏位名）就必然违规 ——
    **评估测的是它自己塞进去的缺陷**，而生产里根本没有这个缺陷了。

    这正是 `README` 里那条原则的反面教材：**"照抄前端"抄的必须是当前那一版**，
    前端改了而桥没跟着改，桥就从"真世界"变成了"另一个世界"。

    所以这里只留服务端不知道的那一件事：这一章有没有主讲材料（评估没有，所以按没有发）。
    `points` / `question` 一并去掉 —— 前端也去掉了，它们会被渲染成「板书：」「课堂提问：」，
    而实践对话里没有这两样东西。
    """
    return {
        "id": f"practice-{scenario_id}",
        "type": "practice",
        "title": (task or {}).get("title") or "",
        "script": "当前没有可用主讲材料",
        "workspace": workspace,
    }


# ═══════════════════════════════════════
#  跑一轮
# ═══════════════════════════════════════

def _sse_payloads(raw: str) -> list[dict]:
    """把 `_sse` 包出来的 `data: {...}` 解回字典。

    解不出来的行直接跳过（`data: [DONE]`、空行都在这里被滤掉），不能让一条它自己发的
    结束标记把整轮判死。
    """
    out: list[dict] = []
    for line in str(raw or "").splitlines():
        if not line.startswith("data: "):
            continue
        body = line[len("data: "):].strip()
        if not body or body == "[DONE]":
            continue
        try:
            payload = json.loads(body)
        except ValueError:
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def _tool_frames(payload: dict) -> dict | None:
    """把工具类帧压成一条评估用得上的记录（只留名字和关键参数，不留正文）。"""
    kind = payload.get("type")
    if kind == "tool_start":
        return {"event": "call", "tool": payload.get("tool")}
    if kind == "doc_write":
        return {
            "event": "call", "tool": "write_design_doc",
            "section": payload.get("section"),
            "content_chars": len(str(payload.get("content") or "")),
        }
    if kind == "framework_docs":
        return {
            "event": "call", "tool": "fetch_framework_docs",
            "frameworks": [item.get("id") for item in payload.get("frameworks") or []],
            "urls": payload.get("urls") or [],
            "unknown": payload.get("unknown") or [],
        }
    return None


async def _collect(subject, text: str, segment: dict) -> dict:
    """跑一轮：把 SSE 事件收集起来，正文拼回去。

    重试的代价是几厘钱，一次网络抖动就把整轮评估判死太亏。

    **错误要以异常的形式浮出来才能重试。** `stream_classroom_chat` 自己把异常兜成了
    一条 `{"error": ...}` 帧（学生在页面上看到的就是它），所以这里要把那条帧再翻回异常 ——
    否则一轮失败会被当成"教练回了一句错误提示"，判官照着它打分。
    """
    last_error: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        chunks: list[str] = []
        tool_calls: list[dict] = []
        failure: str | None = None
        try:
            async for raw in stream_classroom_chat(
                user_id=subject.user_id,
                path_id=subject.path_id,
                node_id=subject.node_id,
                segment=segment,
                scenario=PRACTICE_SCENARIO,
                text=text,
                resource_id=None,
                practice_session_id=subject.session_key,
            ):
                for payload in _sse_payloads(raw):
                    if payload.get("error"):
                        failure = str(payload["error"])
                        continue
                    if payload.get("type") in ("chunk", "content") and payload.get("content"):
                        chunks.append(str(payload["content"]))
                        continue
                    record = _tool_frames(payload)
                    if record:
                        tool_calls.append(record)
            if failure:
                raise RuntimeError(f"课堂对话返回了错误帧：{failure}")
        except Exception as exc:  # noqa: BLE001 —— 端点可能抛任何东西，这里都要能重试
            last_error = exc
            print(f"[bridge] 第 {attempt}/{RETRY_ATTEMPTS} 轮失败："
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            if attempt < RETRY_ATTEMPTS:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
            continue

        reply = "".join(chunks).strip()
        return {
            "reply": reply,
            "tool_calls": tool_calls,
            "context": _captured.get("path_context", ""),
            # 把工具调用当文本吐出来了。真 agent 不该这样；真发生了就得**说出来**，
            # 不能让判官把它读成"这轮没说话"。
            "leaked_tool_call": any(mark in reply for mark in _LEAKED_TOOL_CALL_MARKERS),
        }
    raise last_error


async def run(payload: dict) -> list[dict]:
    """按剧本走一遍，返回每一轮的（学生发言、附给他的材料、教练回复、他调了哪些工具）。"""
    replaced = _install_fixed_world()
    _silence_post_chat_enrichment()
    _capture_stream_input()
    print(f"[bridge] 固定世界：{replaced}", file=sys.stderr)

    await init_db()

    scenario_id = str(payload.get("id") or "unknown")
    task = payload.get("task")
    # 会话 key 由 subject 生成（每个进程一个，见那边的注释）—— 不同场景不串线，
    # 同一场景的多次运行（`--runs 3`）也不撞唯一约束。
    subject = await subject_module.ensure(task, scenario_id)
    print(f"[bridge] 合成学生 user_id={subject.user_id} 会话={subject.session_key}", file=sys.stderr)

    try:
        turns: list[dict] = []
        for turn in payload["turns"]:
            segment = _practice_segment(task, turn.get("workspace"), scenario_id)
            result = await _collect(subject, turn["student"], segment)
            turns.append({
                "student": turn["student"],
                "context": result.pop("context"),
                **result,
            })
        return turns
    finally:
        # 无论成功失败都收拾干净，且**把删了什么报出来** —— 这是动用户库的操作，
        # 不能只留一句"已经清理过了"。
        deleted = await subject_module.purge(subject)
        print(f"[bridge] 已清理合成学生的数据：{deleted}", file=sys.stderr)


def _read_payload() -> dict:
    """按 **UTF-8 读字节**，不走 `sys.stdin.read()`。

    Windows 上 `sys.stdin.read()` 用的是控制台本地编码（这里 GBK），而调用方写进来的是
    UTF-8 —— 中文会被解成一串代理字符（`\\udc80` 那种），一路活到写文件时才炸成一个
    跟真正原因毫无关系的 UnicodeEncodeError。
    """
    return json.loads(sys.stdin.buffer.read().decode("utf-8"))


def _log_backend_failures_to_stderr() -> None:
    """让后端的日志（警告以上）也落到 stderr。

    `stream_classroom_chat` 把异常**兜成了错误帧**（学生看到的就是那句"教练暂时无法回复"），
    也就是说真正的 traceback 不会跟着异常漂上来。评估失败时那一行是唯一的线索，
    而父进程会把 stderr 一起报出来。
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("[backend] %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)


async def _drive(payload: dict) -> dict:
    """跑一轮，**在同一个事件循环里**把连接关掉。

    关连接不能另起一个 `asyncio.run`：aiomysql 的连接是绑在**建它的那个循环**上的，
    在新循环里关会得到一串 `RuntimeError: Event loop is closed`（`Connection.__del__`
    里抛的，用户看得到、却和真正的原因毫无关系）。
    清理必须排在 `run()` 的 `finally` 之后 —— 那个 `finally` 还要删合成学生的数据。
    """
    try:
        return {"ok": True, "turns": await run(payload)}
    finally:
        try:
            await close_db()
        except Exception:  # noqa: BLE001 —— 关连接失败不该盖掉上面那个真正的原因
            pass


def main() -> int:
    # 往 stderr 打中文前**必须自己指定编码**。Windows 上 `sys.stderr` 默认是控制台代码页
    # （这台机器是 GBK），而父进程按 UTF-8 读 —— 于是 `[bridge] 固定世界：…` 这行日志让
    # 父进程的读线程抛 UnicodeDecodeError，整个评估在开跑前就崩了，报出来的错还和真正
    # 的原因（编码）毫无关系。和 `_read_payload` 是同一个病的另一个方向。
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    _log_backend_failures_to_stderr()

    out_path = Path(sys.argv[1])
    try:
        payload = _read_payload()
        out = asyncio.run(_drive(payload))
    except Exception as exc:  # 桥挂了要如实报出去，不能让评估器以为"教练没说话"
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
