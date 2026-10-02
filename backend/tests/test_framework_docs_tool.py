# -*- coding: utf-8 -*-
"""教练拉官方文档那条链路：工具 → 帧 → 前端去拉。

抓取本身在 `test_framework_docs.py` / `test_web_page_fetch.py` 里测；这里只测**接缝**：
注册、白名单、描述跟着注册表走、参数解析、以及帧里带出去的是 id / 地址而不是正文。
"""
import pytest

from backend.src.ai_core.brain import TOOL_REGISTRY, _frame_from_event
from backend.src.ai_core.tools.workspace import (
    FRAMEWORK_DOC_DIR,
    FRAMEWORK_DOC_TOOL,
    fetch_framework_docs,
    resolve_doc_sources,
)
from backend.src.service.path import classroom_chat as cg_chat
from backend.src.utils.framework_docs import catalogue


def _tool_start(name, args):
    return {"event": "on_tool_start", "name": name, "data": {"input": args}}


# ═══════════════════════════════════════
#  注册与白名单
# ═══════════════════════════════════════

def test_the_tool_is_registered_and_whitelisted():
    assert FRAMEWORK_DOC_TOOL in TOOL_REGISTRY
    assert FRAMEWORK_DOC_TOOL in cg_chat._CLASSROOM_TOOLS


def test_the_description_lists_every_framework_in_the_registry():
    """描述里的框架清单是**按注册表生成的**，不是手抄的。

    这条测试守的是"生成"这件事本身：哪天有人图省事把描述写死，加框架时漏改一处，
    教练就会拿着一个调不通的名字去调，而它只会看到"我不认识这个名字"。
    """
    for item in catalogue():
        assert item["id"] in fetch_framework_docs.description
        assert item["name"] in fetch_framework_docs.description


def test_the_description_does_not_say_the_list_is_the_limit():
    """**描述里不能出现"只有这几个"那种话。**

    这就是这次故障的成因：以前那句「能拉的只有这几个」被教练当成事实读，于是学生问
    Vue 时它答「Vue 的拉不了，你去看 vuejs.org」—— 把学生推出了产品。注册表是快捷
    方式，不是门禁；描述必须说得出另一条路。
    """
    description = fetch_framework_docs.description

    assert "只有这几个" not in description
    assert "urls" in description


# ═══════════════════════════════════════
#  参数解析
# ═══════════════════════════════════════

def test_ids_are_resolved_case_insensitively():
    """模型会把 id 写成 `FastAPI` / `LangChain` —— 大小写不该让它调不通。"""
    known, unknown, _ = resolve_doc_sources(["FastAPI", "LangChain"], None)

    assert [item["id"] for item in known] == ["fastapi", "langchain"]
    assert unknown == []


def test_unknown_names_are_reported_not_dropped():
    """认不出的名字必须单独回 —— 悄悄丢掉的话，教练以为三个都拉到了。"""
    known, unknown, _ = resolve_doc_sources(["fastapi", "rust", "cobol"], None)

    assert [item["id"] for item in known] == ["fastapi"]
    assert unknown == ["rust", "cobol"]


def test_duplicates_collapse():
    known, _, _ = resolve_doc_sources(["fastapi", "FASTAPI", " fastapi "], None)

    assert len(known) == 1


def test_a_bare_string_is_accepted():
    """模型偶尔会把数组参数写成一个字符串，不该因此整轮失败。"""
    known, _, _ = resolve_doc_sources("langchain", None)

    assert [item["id"] for item in known] == ["langchain"]


def test_junk_input_yields_nothing():
    assert resolve_doc_sources(None, None) == ([], [], [])
    assert resolve_doc_sources(["", "   "], None) == ([], [], [])


def test_the_coach_picked_urls_are_passed_through_untouched():
    """教练自己找的地址**原样收着**。

    这一层判不了两件事，也不该判：这个站算不算官方（判不出来）、抓不抓得开
    （`web_page.check_fetchable_url` 逐跳拦）。它只管把地址带到下游。
    """
    pages = ["https://vuejs.org/guide/quick-start.html", "https://vite.dev/guide/"]

    _, _, urls = resolve_doc_sources(None, pages)

    assert urls == pages


def test_a_bare_url_string_is_accepted_too():
    _, _, urls = resolve_doc_sources(None, "https://vuejs.org/guide/introduction.html")

    assert urls == ["https://vuejs.org/guide/introduction.html"]


def test_the_same_url_given_twice_is_fetched_once():
    _, _, urls = resolve_doc_sources(None, ["https://vite.dev/guide/", "https://vite.dev/guide/"])

    assert urls == ["https://vite.dev/guide/"]


@pytest.mark.asyncio
async def test_a_json_string_of_urls_is_parsed_not_treated_as_one_url():
    """**模型真的会把数组写成 JSON 字符串。**

    实测就是这一句：`{'urls': '["https://svelte.dev/docs/svelte/overview", ...]'}` ——
    一个字符串里装着四个地址。以前它被当成"一个网址"，谁都取不到；更糟的是签名写成
    `list[str]` 时 pydantic 在校验那一步就把它拒了，异常穿过 AgentExecutor 把整条流打断。

    所以这条测试走的是**完整调用**（`ainvoke` 会先过校验器），不是直接调
    `resolve_doc_sources` —— 出问题的那一步就在校验器那里。
    """
    raw = '["https://svelte.dev/docs/svelte/overview", "https://svelte.dev/kit/introduction"]'

    reply = await fetch_framework_docs.ainvoke({"urls": raw})

    assert "2 个地址" in reply          # 认成两份，不是一份


def test_the_schema_still_promises_an_array():
    """对外只承诺数组 —— 校验器负责把字符串收下来，但 schema 不该教模型写字符串。

    哪天有人图省事把签名改成 `list[str] | str`，模型看到的就是"字符串也行"，
    于是这种写法会变多。断言 schema 里没有字符串分支。
    """
    urls = fetch_framework_docs.args_schema.model_json_schema()["properties"]["urls"]

    assert urls["type"] == "array"
    assert urls["items"] == {"type": "string"}


def test_a_name_and_a_url_can_be_given_together():
    """一次调用可以两种都给 —— 表里认得的用名字，认不得的用地址。"""
    known, unknown, urls = resolve_doc_sources(
        ["fastapi"], ["https://vuejs.org/guide/introduction.html"]
    )

    assert [item["id"] for item in known] == ["fastapi"]
    assert unknown == []
    assert urls == ["https://vuejs.org/guide/introduction.html"]


# ═══════════════════════════════════════
#  帧
# ═══════════════════════════════════════

def test_the_frame_carries_ids_and_not_the_document_text():
    """帧里**只能有 id / 地址**。

    正文一次最多 12 篇、每篇上限 12 万字符 —— 全塞进一帧能到一两 MB，SSE 帧扛不住，
    而且会把这一轮的首字节拖到几十秒后。前端拿 id 自己去 POST 拉。
    """
    frame = _frame_from_event(_tool_start(FRAMEWORK_DOC_TOOL, {"frameworks": ["fastapi"]}))

    assert frame["type"] == "framework_docs"
    assert frame["dir"] == FRAMEWORK_DOC_DIR
    assert frame["frameworks"] == [{"id": "fastapi", "name": "FastAPI"}]
    assert frame["urls"] == []
    assert frame["unknown"] == []
    # 整帧要小到能放进一帧 SSE
    assert len(str(frame)) < 500


def test_the_frame_carries_the_coach_picked_urls_but_not_their_text():
    frame = _frame_from_event(_tool_start(
        FRAMEWORK_DOC_TOOL,
        {"urls": ["https://vuejs.org/guide/quick-start.html"]},
    ))

    assert frame["urls"] == ["https://vuejs.org/guide/quick-start.html"]
    assert frame["frameworks"] == []
    assert len(str(frame)) < 500


def test_the_frame_reports_unknown_names_too():
    frame = _frame_from_event(_tool_start(FRAMEWORK_DOC_TOOL, {"frameworks": ["fastapi", "django"]}))

    assert frame["unknown"] == ["django"]


def test_other_tools_are_still_generic():
    frame = _frame_from_event(_tool_start("web_search", {"query": "x"}))

    assert frame == {"role": "tool", "type": "tool_start", "tool": "web_search"}


# ═══════════════════════════════════════
#  回给模型的话
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_an_unknown_name_points_at_the_urls_route():
    """**这条是这次故障的正对靶心。**

    学生问 Vue，教练查表没查到，回的是「只能取这几个」—— 死路一条。它在对话里把这个
    死路转述成了「这个我拉不了，你去看 vuejs.org」。

    所以认不出名字时，回给模型的话里必须带着下一步：去找官网，把地址放进 urls。
    """
    reply = await fetch_framework_docs.ainvoke({"frameworks": ["django"]})

    assert "认不出来" in reply
    assert "django" in reply
    assert "urls" in reply


@pytest.mark.asyncio
async def test_an_empty_call_lists_what_is_available():
    reply = await fetch_framework_docs.ainvoke({})

    assert "fastapi" in reply
    assert "urls" in reply


@pytest.mark.asyncio
async def test_the_reply_tells_the_model_not_to_open_the_folder_this_turn():
    """拉取和写盘是**异步**的（前端自己去 POST），这一轮结束时文件还没写好。

    不说这一句，教练会顺手说"你打开左边那个目录看看" —— 学生打开是空的，
    而他只会以为自己哪里点错了。
    """
    reply = await fetch_framework_docs.ainvoke({"frameworks": ["fastapi"]})

    assert "先不要让他打开" in reply


@pytest.mark.asyncio
async def test_urls_alone_are_enough_to_fetch():
    reply = await fetch_framework_docs.ainvoke({"urls": ["https://vuejs.org/guide/quick-start.html"]})

    assert "先不要让他打开" in reply
    assert "认不出来" not in reply


@pytest.mark.asyncio
async def test_unrecognised_names_are_mentioned_alongside_the_good_ones():
    reply = await fetch_framework_docs.ainvoke({"frameworks": ["fastapi", "django"]})

    assert "FastAPI" in reply
    assert "django" in reply
