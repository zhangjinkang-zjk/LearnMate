# -*- coding: utf-8 -*-
"""教练代笔方案文档的那条链路：工具 → 帧 → 前端。

落盘本身在浏览器里，后端测不到；后端能测的是**中间那一段是否原样把内容带出去**，
以及工具的校验有没有把"占位式的一节"放过去。
"""
import pytest

from backend.src.ai_core.brain import TOOL_REGISTRY, _frame_from_event
from backend.src.ai_core.tools.workspace import (
    DOC_PATH,
    DOC_WRITE_TOOL,
    write_design_doc,
)
from backend.src.service.path import classroom_chat as cg_chat


def _tool_start(name, args):
    return {"event": "on_tool_start", "name": name, "data": {"input": args}}


# ═══════════════════════════════════════
#  注册与白名单
# ═══════════════════════════════════════

def test_the_tool_is_registered():
    assert DOC_WRITE_TOOL in TOOL_REGISTRY


def test_the_classroom_whitelist_includes_it():
    """白名单才是真正决定教练能不能用它那一关 —— 注册了但没进白名单 = 全程调不到。"""
    assert DOC_WRITE_TOOL in cg_chat._CLASSROOM_TOOLS


# ═══════════════════════════════════════
#  事件 → 帧
# ═══════════════════════════════════════

def test_the_write_tool_becomes_a_doc_write_frame():
    frame = _frame_from_event(_tool_start(DOC_WRITE_TOOL, {"section": "技术栈", "content": "选 LangGraph"}))

    assert frame["type"] == "doc_write"
    assert frame["path"] == DOC_PATH
    assert frame["section"] == "技术栈"
    assert frame["content"] == "选 LangGraph"


def test_other_tools_keep_the_generic_frame():
    """别的工具走的还是 tool_start —— 加这一种帧不许把原来那条路顶掉。"""
    frame = _frame_from_event(_tool_start("web_search", {"query": "x"}))

    assert frame == {"role": "tool", "type": "tool_start", "tool": "web_search"}


def test_missing_args_do_not_crash_the_frame():
    """参数字典缺字段（模型偶尔会这么干）不该让整轮对话炸掉，退化成空串往下走。"""
    frame = _frame_from_event(_tool_start(DOC_WRITE_TOOL, {}))

    assert frame["type"] == "doc_write"
    assert frame["section"] == ""
    assert frame["content"] == ""


def test_a_non_dict_input_degrades_to_empty():
    """`data.input` 不是字典时（形状变了、或事件来自别的链路）不能抛异常。"""
    frame = _frame_from_event({"event": "on_tool_start", "name": DOC_WRITE_TOOL, "data": {"input": "oops"}})

    assert frame["section"] == "" and frame["content"] == ""


def test_chunk_and_unknown_events_are_untouched():
    class _Chunk:
        content = "你好"

    assert _frame_from_event({"event": "on_chat_model_stream", "data": {"chunk": _Chunk()}})["type"] == "chunk"
    assert _frame_from_event({"event": "on_chain_start", "data": {}}) is None


# ═══════════════════════════════════════
#  工具自己的校验
# ═══════════════════════════════════════

async def _write(section, content):
    return await write_design_doc.ainvoke({"section": section, "content": content})


@pytest.mark.asyncio
async def test_a_good_section_is_accepted():
    reply = await _write("技术栈", "选 LangGraph，因为它把状态摆在明面上。" * 2)

    assert "技术栈" in reply and DOC_PATH in reply


@pytest.mark.asyncio
async def test_a_placeholder_body_is_rejected():
    """「待补充」这种占位必须拦掉 —— 写进文档比不写更坏：学生下次打开会以为定性了。"""
    reply = await _write("技术栈", "待补充")

    assert "太短" in reply


@pytest.mark.asyncio
async def test_an_empty_title_is_rejected():
    reply = await _write("", "内容" * 20)

    assert "标题" in reply


@pytest.mark.asyncio
async def test_a_paragraph_long_title_is_rejected():
    reply = await _write("这一节我想说的是关于技术选型的一些考虑和取舍，" * 4, "内容" * 20)

    assert "太长" in reply


@pytest.mark.asyncio
async def test_the_reply_tells_the_model_not_to_paste_it_again():
    """回话里必须带上"别再贴一遍"这句。

    它同时是给模型的行为指令：不写这句，模型很容易把刚写进文档的同一段又在聊天里
    贴一遍 —— 那这一轮就白干了，学生看到两份一样的东西。
    """
    reply = await _write("技术栈", "选 LangGraph，因为它把状态摆在明面上。" * 2)

    assert "不要再贴一遍" in reply or "不要把这节内容在聊天里再贴一遍" in reply
