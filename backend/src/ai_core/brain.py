# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import os
import weakref
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from backend.src.ai_core.llm_config import llm
from backend.src.ai_core.tools.knowledge import (
    search_knowledge_base, ingest_document,
    search_web_and_stage_knowledge,
    list_knowledge, update_knowledge, delete_knowledge,
)
from backend.src.ai_core.tools.portrait import read_portrait, update_portrait
from backend.src.ai_core.tools.skill import (
    read_skill, upsert_skill, list_skills, delete_skill, create_action_skill,
)
from backend.src.ai_core.tools.resource import generate_learning_resource
from backend.src.ai_core.tools.search import web_search
from backend.src.ai_core.tools.mcp_external import load_external_mcp_tools
from backend.src.ai_core.tools.image import generate_image
from backend.src.ai_core.tools.exam import generate_exam_questions
from backend.src.ai_core.tools.path import (
    list_learning_paths, get_learning_path_detail, enroll_learning_path,
    regenerate_learning_path, update_path_node, add_path_node, delete_path_node,
)
from backend.src.ai_core.tools.animation import generate_slide_animation
from backend.src.ai_core.tools.video_search import search_online_video
from backend.src.ai_core.tools.history import get_used_history
from backend.src.ai_core.tools.memory import search_memory
from backend.src.utils.prompt_loader import load_prompt
from pydantic import create_model, Field as PydanticField
try:
    from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
except ModuleNotFoundError:
    from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, AIMessage


def _inject_user_id(tool, user_id: str):
    """拷贝一个 tool，移除 user_id 参数并自动注入当前用户 ID"""
    original_coro = tool.coroutine
    if tool.args_schema:
        fields = {}
        for name, field_info in tool.args_schema.model_fields.items():
            if name != "user_id":
                fields[name] = (field_info.annotation, field_info)
        new_schema = create_model(f"{tool.name}_input", **fields) if fields else None
    else:
        new_schema = None

    desc = (tool.description or "").replace("user_id用户数字ID", "")
    desc = desc.replace("，，", "，").replace("，。", "。").replace("参数：，", "参数：").strip()

    async def _scoped(**kwargs):
        kwargs["user_id"] = user_id
        return await original_coro(**kwargs)

    _scoped.__name__ = tool.name
    return StructuredTool.from_function(
        coroutine=_scoped,
        name=tool.name,
        description=desc,
        args_schema=new_schema,
    )


def _inject_chat_group_id(tool, chat_group_id: int):
    """为 get_used_history 注入当前聊天组 ID"""
    original_coro = tool.coroutine
    if tool.args_schema:
        fields = {}
        for name, field_info in tool.args_schema.model_fields.items():
            if name not in ("chat_group_id",):
                fields[name] = (field_info.annotation, field_info)
        new_schema = create_model(f"{tool.name}_scoped_input", **fields) if fields else None
    else:
        new_schema = None

    async def _scoped(**kwargs):
        kwargs["chat_group_id"] = chat_group_id
        return await original_coro(**kwargs)

    _scoped.__name__ = tool.name
    return StructuredTool.from_function(
        coroutine=_scoped,
        name=tool.name,
        description=(tool.description or ""),
        args_schema=new_schema,
    )


# 冷启动时水合多少轮原文历史。
#
# **必须等于 `service/memory/service.WORKING_BUFFER_TURNS`**（同一个环境变量
# `MEMORY_BUFFER_TURNS`，同一套默认值）。那边把超过窗口的消息折叠进
# `memory_summary.summary`（滚动摘要），这边把最近若干轮原样水合进上下文。
# 两个数一旦不等，多出来的那几轮就会**同时以"原文"和"摘要"两种形态**出现在 prompt 里
# —— 既白烧 token，又可能让模型把同一条信息当成两件事（一条"你之前提过"，一条"你刚才说"）。
#
# 不直接 import 那边的常量：`ai_core` 不能反向依赖 `service/`。所以两边各自读同一个
# 环境变量，再用一条测试把"它们必须相等"钉死（tests/test_memory_window_alignment.py）。
_MAX_HISTORY_TURNS = int(os.getenv("MEMORY_BUFFER_TURNS", "20"))

# ── 消息分类：按需加载工具行为指南 ──

_CREATE_TRIGGERS = [
    "生成学习", "生成资料", "生成文档", "做个PPT", "做PPT", "生成PPT",
    "整理成文档", "整理成PPT", "做成文档", "做成PPT",
    "生成思维导图", "生成脑图", "做思维导图", "做脑图",
    "帮我整理", "帮我总结", "帮我生成",
    "出题", "出几道", "出一些题", "练习题", "测验", "考试模拟",
    "做几道题", "来几道题", "做题", "习题", "试卷",
    "画一张", "画个", "生成图片", "生成一张图", "配图", "插图",
    "帮我画", "帮我生成图",
    "生成动画", "播放PPT", "演示PPT", "旁白", "念给我听",
    "搜视频", "找视频", "视频教程",
]

_MANAGE_TRIGGERS = [
    "学习路径", "课程路径", "学习计划", "选课", "有哪些路径",
    "加入路径", "路径管理", "修改节点", "添加节点", "删除节点",
    "重新规划路径", "路径不合适", "路径查看",
    "skill", "Skill", "自定义提示词", "修改提示词", "设置提示词",
    "恢复默认", "升级生成", "删除skill", "创建skill",
    "动作skill", "action skill", "添加能力", "添加工具",
]


_INGEST_TRIGGERS = [
    "上传", "入库", "补库", "联网补充", "补充知识库", "存到知识库", "收进知识库",
    "加进知识库", "归到知识库", "我的笔记", "这是我的资料", "帮我存", "题解",
]

_KB_MANAGE_TRIGGERS = [
    "有哪些资料", "列出我的资料", "我的资料", "知识库有哪些", "知识库里有",
    "删除资料", "删掉资料", "修改资料", "改一下资料", "知识库里的资料",
]

_PORTRAIT_TRIGGERS = [
    "记住", "帮我记录", "我的目标", "我在学", "最近在学", "我是学生", "已经工作",
    "学习风格", "我的弱点", "我的强项", "我的基础",
]

_HISTORY_TRIGGERS = ["之前说过", "上次", "之前聊", "以前说过", "历史记录"]

# 一张表管全部：类别 → (触发词, 提示词文件)。新增一类只加两行，不用碰加载逻辑。
# 拆开的原因见 _load_tool_guides。
_TRIGGERS: dict[str, list[str]] = {
    "create": _CREATE_TRIGGERS,
    "manage": _MANAGE_TRIGGERS,
    "ingest": _INGEST_TRIGGERS,
    "kb_manage": _KB_MANAGE_TRIGGERS,
    "portrait": _PORTRAIT_TRIGGERS,
    "history": _HISTORY_TRIGGERS,
}

_GUIDE_MODULES: dict[str, str] = {
    "create": "chat/guide_create",
    "manage": "chat/guide_manage",
    "ingest": "chat/modules/ingest",
    "kb_manage": "chat/modules/kb_manage",
    "portrait": "chat/modules/portrait",
    "history": "chat/modules/history",
}


def _classify_message(message: str) -> set[str]:
    """按触发词判断这轮该加载哪些行为模块。命中多个就都加载。"""
    text = str(message or "")
    return {
        category
        for category, triggers in _TRIGGERS.items()
        if any(trigger in text for trigger in triggers)
    }


# ── 工具注册表：工具名 → 工厂函数(uid, gid) → 已注入的 LangChain Tool ──
TOOL_REGISTRY: dict[str, callable] = {
    "search_knowledge_base":      lambda uid, gid: _inject_user_id(search_knowledge_base, uid),
    "ingest_document":             lambda uid, gid: _inject_user_id(ingest_document, uid),
    "search_web_and_stage_knowledge": lambda uid, gid: _inject_user_id(search_web_and_stage_knowledge, uid),
    "list_knowledge":              lambda uid, gid: _inject_user_id(list_knowledge, uid),
    "update_knowledge":            lambda uid, gid: _inject_user_id(update_knowledge, uid),
    "delete_knowledge":            lambda uid, gid: _inject_user_id(delete_knowledge, uid),
    "read_portrait":               lambda uid, gid: _inject_user_id(read_portrait, uid),
    "update_portrait":             lambda uid, gid: _inject_user_id(update_portrait, uid),
    "get_used_history":            lambda uid, gid: _inject_chat_group_id(_inject_user_id(get_used_history, uid), gid),
    "search_memory":               lambda uid, gid: _inject_user_id(search_memory, uid),
    "web_search":                  lambda uid, gid: web_search,
    "read_skill":                  lambda uid, gid: _inject_user_id(read_skill, uid),
    "upsert_skill":                lambda uid, gid: _inject_user_id(upsert_skill, uid),
    "list_skills":                 lambda uid, gid: _inject_user_id(list_skills, uid),
    "delete_skill":                lambda uid, gid: _inject_user_id(delete_skill, uid),
    "create_action_skill":         lambda uid, gid: _inject_user_id(create_action_skill, uid),
    "generate_learning_resource":  lambda uid, gid: _inject_chat_group_id(_inject_user_id(generate_learning_resource, uid), gid),
    "generate_image":              lambda uid, gid: _inject_chat_group_id(_inject_user_id(generate_image, uid), gid),
    "generate_exam_questions":     lambda uid, gid: _inject_chat_group_id(_inject_user_id(generate_exam_questions, uid), gid),
    "generate_slide_animation":    lambda uid, gid: _inject_chat_group_id(_inject_user_id(generate_slide_animation, uid), gid),
    "search_online_video":         lambda uid, gid: _inject_chat_group_id(_inject_user_id(search_online_video, uid), gid),
    "list_learning_paths":         lambda uid, gid: _inject_user_id(list_learning_paths, uid),
    "get_learning_path_detail":    lambda uid, gid: _inject_user_id(get_learning_path_detail, uid),
    "enroll_learning_path":        lambda uid, gid: _inject_user_id(enroll_learning_path, uid),
    "regenerate_learning_path":    lambda uid, gid: _inject_user_id(regenerate_learning_path, uid),
    "update_path_node":            lambda uid, gid: _inject_user_id(update_path_node, uid),
    "add_path_node":               lambda uid, gid: _inject_user_id(add_path_node, uid),
    "delete_path_node":            lambda uid, gid: _inject_user_id(delete_path_node, uid),
}


class Brain:
    _instances: weakref.WeakSet = weakref.WeakSet()

    def __init__(self, user_id: int, chat_group_id: int | None = None,
                 session_id: str | None = None, agent_id: int | None = None,
                 history_turns: int | None = None):
        self.user_id = user_id
        self.chat_group_id = chat_group_id
        self.session_id = session_id or f"brain_{user_id}"
        self.agent_id = agent_id
        # 记忆深度可以按调用方调。默认锁在 _MAX_HISTORY_TURNS，只有课堂/实践教练那条线
        # 会调高 —— 一次代码审核要跨几十轮，20 轮会让他"忘了"学生十分钟前说的设计决定。
        # 不直接改全局默认值：主智能体每轮都要把这批历史重放一遍（ReAct 循环里是每个
        # 工具步一遍），给它加长是另一笔账，得单独论证。
        self._history_turns = history_turns if history_turns and history_turns > 0 else _MAX_HISTORY_TURNS
        self._agent_persona: str | None = None
        self._agent_tool_names: set[str] | None = None
        self._agent_memory_text: str = ""
        self._raw_executor = None
        self._action_tools_loaded = False
        self._agent_config_loaded = False
        self._history: list = []
        self._history_hydrated = False   # 是否已从 DB 水合最近 N 轮（幂等）
        Brain._instances.add(self)

    # ── 记忆水合 ──

    async def hydrate_history(self, before_id: int | None = None):
        """冷启动时从 DB 水合最近 N 轮历史（幂等）。

        配合多级记忆系统：跨会话恢复短期记忆。before_id 用于截止（如当前
        消息 id），避免把正在处理的这一轮当成历史重放。
        """
        if self._history_hydrated:
            return
        self._history_hydrated = True
        try:
            from backend.src.models.chat_history_model import ChatHistory
            qs = ChatHistory.filter(
                user_id=self.user_id, chat_group_id=self.chat_group_id or 0
            )
            if before_id:
                qs = qs.filter(id__lt=before_id)
            records = await qs.order_by("-id").limit(self._history_turns).all()
            for r in reversed(records):
                if r.req:
                    self._history.append(HumanMessage(content=r.req))
                if r.res:
                    self._history.append(AIMessage(content=r.res))
        except Exception:
            logging.getLogger(__name__).exception("水合历史失败 user_id=%s", self.user_id)

    # ── 动态工具工厂 ──

    @staticmethod
    def _make_http_tool(skill: dict):
        """将 HTTP 类型的 action skill 包装成 LangChain StructuredTool"""
        config = json.loads(skill["action_config"]) if isinstance(skill["action_config"], str) else skill["action_config"]
        safe_name = skill["name"].replace("-", "_").replace(" ", "_")

        async def _handler(**kwargs):
            url = config["url"]
            for k, v in kwargs.items():
                url = url.replace(f"{{{{{k}}}}}", str(v))
            timeout = httpx.Timeout(30.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                method = config.get("method", "GET").upper()
                resp = await client.request(method, url)
                text = resp.text[:3000]
                if resp.status_code >= 400:
                    return f"请求失败 (HTTP {resp.status_code}): {text}"
                return text

        _handler.__name__ = safe_name

        params_schema = config.get("params", {})
        args_schema = None
        if params_schema:
            fields = {}
            for pname, pdesc in params_schema.items():
                if isinstance(pdesc, dict):
                    desc = str(pdesc.get("description") or pdesc.get("desc") or "")
                else:
                    desc = str(pdesc or "")
                fields[pname] = (str, PydanticField(description=desc))
            args_schema = create_model(f"{safe_name}_input", **fields)

        return StructuredTool.from_function(
            coroutine=_handler,
            name=safe_name,
            description=skill.get("tool_description", "") or f"自定义技能: {skill['name']}",
            args_schema=args_schema,
        )

    async def _load_action_tools_async(self):
        """在正确的 async 上下文中从 DB 加载 action skill"""
        from backend.src.service.skill import service as skill_service
        skills = await skill_service.list_actions(user_id=self.user_id)
        tools = []
        for s in skills:
            if s.get("action_type") != "http":
                continue
            try:
                tools.append(self._make_http_tool(s))
            except Exception:
                logging.getLogger(__name__).exception("action skill 构造失败，已跳过: %s", s.get("name"))
        return tools

    # ── 热刷新 ──

    @classmethod
    def rebuild_for_user(cls, user_id: int):
        """创建/删除 action skill 后标记需要刷新，下次对话时自动重建"""
        for inst in cls._instances:
            if inst.user_id == user_id:
                inst._action_tools_loaded = False
                inst._agent_config_loaded = False

    async def _load_agent_config(self):
        """Load user-defined agent config: persona, tool whitelist, memory.
        Only runs once when agent_id is set and not yet loaded."""
        if self.agent_id is None or self._agent_config_loaded:
            return
        try:
            from backend.src.service.agent.service import get as get_agent, get_memory_text
            agent_config = await get_agent(self.user_id, self.agent_id)
            if agent_config:
                self._agent_persona = agent_config.get("persona", "") or None
                tool_names = agent_config.get("tools", [])
                self._agent_tool_names = set(tool_names) if tool_names else None
                self._agent_memory_text = await get_memory_text(self.user_id, self.agent_id)
        except Exception:
            logging.getLogger(__name__).exception("加载智能体配置失败 agent_id=%s", self.agent_id)
            self._agent_persona = None
            self._agent_tool_names = None
            self._agent_memory_text = ""
        self._agent_config_loaded = True

    def _build_agent(self, action_tools: list, mcp_tools: list):
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        tz_name = "Asia/Shanghai"
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        current_time_context = (
            f"\n\n### Current Time Anchor\n"
            f"- Date: {date_str}\n"
            f"- Time: {time_str}\n"
            f"- Timezone: {tz_name}\n"
            f"- Always use this date as reference for time-sensitive queries.\n"
        )

        # 两条路都不在这里拼 `{tool_guides}`：**该不该有它由 persona 自己决定**。
        # 主智能体那份（chat/unified.yaml）里写着这个占位符，所以吃得到按需模块；
        # 实践教练那份故意不写 —— 它的工具集是只读的
        # （search_knowledge_base / web_search / read_portrait / search_memory /
        # get_used_history，见 classroom_chat._CLASSROOM_TOOLS），而那几个模块讲的
        # 是 ingest_document / update_portrait / list_knowledge 这类它**没有**的工具。
        # 注进去只会让它去调不存在的工具。自建智能体想用就自己写上占位符，同样生效。
        if self._agent_persona:
            system_prompt = (
                self._agent_persona
                + current_time_context
                + (("\n" + self._agent_memory_text) if self._agent_memory_text else "")
                + "\n\n{path_context}\n\n{portrait_context}\n\n{memory_context}"
                + "\n\n## Output Rules\n"
                + "- Use Markdown for formatting, NOT raw HTML tags.\n"
                + "- Wrap inline math in $...$ and display math in $$...$$.\n"
                + "- Never output <br>, <div>, <span> or other HTML tags.\n"
            )
        else:
            system_prompt = load_prompt("chat/unified") + current_time_context

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        uid = str(self.user_id)
        gid = self.chat_group_id or 0

        if self._agent_tool_names is not None:
            tool_names_to_load = self._agent_tool_names
        else:
            tool_names_to_load = set(TOOL_REGISTRY.keys())

        tools = []
        for name in tool_names_to_load:
            factory = TOOL_REGISTRY.get(name)
            if factory:
                tools.append(factory(uid, gid))

        tools.extend(_inject_user_id(t, uid) for t in action_tools)
        tools.extend(mcp_tools)

        agent = create_tool_calling_agent(llm=llm, prompt=prompt, tools=tools)
        max_iters = max(8, len(tools) * 2)
        self._raw_executor = AgentExecutor(
            agent=agent, tools=tools,
            verbose=True, handle_parsing_errors=True, max_iterations=max_iters,
        )

    def _load_tool_guides(self, message: str, *, has_portrait: bool = True) -> str:
        """按需加载行为模块；没命中的一律不加载。

        这些模块以前全写死在 `chat/unified.yaml` 里，**每一轮都整份注入** —— 于是
        用户随口闲聊一句，模型也要读一遍「画像构建」那 25 行怎么发起新用户访谈。
        无关指令不只是浪费 token，它会稀释真正相关的那几条。

        新用户引导是**情境信号而不是消息信号**：画像还空着就该把「画像构建」加载上，
        否则模型不会主动发起那几个认识对方的问题 —— 这条不能只靠触发词。
        """
        categories = _classify_message(message)
        if not has_portrait:
            categories.add("portrait")
        return "\n".join(
            load_prompt(_GUIDE_MODULES[cat]) for cat in _GUIDE_MODULES if cat in categories
        )

    async def _ensure_action_tools(self):
        """首次调用或 rebuild_for_user 后，异步加载 agent 配置、action tools 并重建 agent"""
        if self._action_tools_loaded:
            return
        await self._load_agent_config()
        try:
            action_tools = await self._load_action_tools_async()
        except Exception:
            logging.getLogger(__name__).exception("加载 action tools 失败")
            action_tools = []
        try:
            mcp_tools = await load_external_mcp_tools()
        except Exception:
            logging.getLogger(__name__).exception('Failed to load MCP tools')
            mcp_tools = []
        self._build_agent(action_tools, mcp_tools)
        self._action_tools_loaded = True

    async def chat(self, message: str, resource_context: str = "", path_context: str = "", portrait_context: str = "", memory_context: str = "") -> str:
        await self._ensure_action_tools()
        # 画像上下文为空 = 还没建立画像，把「新用户引导」那段一起加载上
        tool_guides = self._load_tool_guides(message, has_portrait=bool(str(portrait_context or "").strip()))
        response = await self._raw_executor.ainvoke({
            "input": message,
            "history": list(self._history),
            "current_user_id": str(self.user_id),
            "resource_context": resource_context,
            "path_context": path_context,
            "portrait_context": portrait_context,
            "memory_context": memory_context,
            "tool_guides": tool_guides,
        })
        self._history.append(HumanMessage(content=message))
        self._history.append(AIMessage(content=response["output"]))
        if len(self._history) > self._history_turns * 2:
            self._history = self._history[-self._history_turns * 2:]
        return response["output"]

    async def stream(self, message: str, resource_context: str = "", path_context: str = "", portrait_context: str = "", memory_context: str = ""):
        """逐 token 流式输出 — 包含工具调用事件，工具执行期间自动心跳保活"""
        await self._ensure_action_tools()

        full_response = ""
        tool_running = False
        # 同 chat()：画像为空说明还没建立画像，把新用户引导那段一起加载上
        tool_guides = self._load_tool_guides(message, has_portrait=bool(str(portrait_context or "").strip()))

        async def _stream_events(version: str):
            nonlocal tool_running
            agen = self._raw_executor.astream_events(
                {
                    "input": message,
                    "history": list(self._history),
                    "current_user_id": str(self.user_id),
                    "resource_context": resource_context,
                    "path_context": path_context,
                    "portrait_context": portrait_context,
                    "memory_context": memory_context,
                    "tool_guides": tool_guides,
                },
                version=version,
            )
            while True:
                try:
                    event = await asyncio.wait_for(agen.__anext__(), timeout=30 if tool_running else 120)
                except asyncio.TimeoutError:
                    yield {"type": "keepalive"}
                    continue
                except StopAsyncIteration:
                    break
                yield event

        try:
            async for event in _stream_events("v2"):
                kind = event.get("event", "")

                if kind == "on_tool_start":
                    tool_running = True
                    tool_name = event.get("name", "")
                    yield {"role": "tool", "type": "tool_start", "tool": tool_name}

                elif kind == "on_tool_end":
                    tool_running = False
                    tool_name = event.get("name", "")
                    tool_output = event.get("data", {}).get("output", "")
                    if isinstance(tool_output, str) and len(tool_output) > 500:
                        tool_output = tool_output[:500] + "..."
                    yield {"role": "tool", "type": "tool_end", "tool": tool_name, "output": str(tool_output)}

                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = getattr(chunk, "content", None)
                        if content:
                            full_response += content
                            yield {"role": "assistant", "type": "chunk", "content": content}
        except (TypeError, NotImplementedError):
            async for event in _stream_events("v1"):
                kind = event.get("event", "")

                if kind == "on_tool_start":
                    tool_running = True
                    tool_name = event.get("name", "")
                    yield {"role": "tool", "type": "tool_start", "tool": tool_name}

                elif kind == "on_tool_end":
                    tool_running = False
                    tool_name = event.get("name", "")
                    tool_output = event.get("data", {}).get("output", "")
                    if isinstance(tool_output, str) and len(tool_output) > 500:
                        tool_output = tool_output[:500] + "..."
                    yield {"role": "tool", "type": "tool_end", "tool": tool_name, "output": str(tool_output)}

                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = getattr(chunk, "content", None)
                        if content:
                            full_response += content
                            yield {"role": "assistant", "type": "chunk", "content": content}

        self._history.append(HumanMessage(content=message))
        self._history.append(AIMessage(content=full_response))
        if len(self._history) > self._history_turns * 2:
            self._history = self._history[-self._history_turns * 2:]
