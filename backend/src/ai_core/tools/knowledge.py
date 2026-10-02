"""Knowledge-base tools for the chat agent."""

import asyncio
import re

from langchain_core.tools import tool

from backend.src.ai_core.tools.search import search_collect
from backend.src.utils.education_sources import label_for
from backend.src.utils.knowledge_base import (
    delete as kb_delete,
    ingest as kb_ingest,
    list_all as kb_list,
    search as kb_search,
    update as kb_update,
)
# 抓取内核在 utils/ 里 —— 它不该知道"智能体"这个概念，而且"把官网文档落进学生工作区"
# 那条路要走 service/router，按分层规矩 service 不许 import ai_core。见该模块开头。
from backend.src.utils.web_page import fetch_readable_text


def _compact_text(value: str, max_chars: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_chars].rstrip()


def _normalize_source_url(value: str) -> str:
    return str(value or "").strip()


_AUTO_STAGE_TRIGGERS = (
    "补库",
    "入库",
    "加入知识库",
    "添加到知识库",
    "放进知识库",
    "存到知识库",
    "提交审核",
    "待审核",
    "自动搜索资料",
    "自动搜资料",
    "联网补充",
    "补充知识库",
)


def _is_explicit_stage_request(user_request: str, topic: str) -> bool:
    text = f"{user_request or ''} {topic or ''}"
    return any(trigger in text for trigger in _AUTO_STAGE_TRIGGERS)


@tool
async def search_knowledge_base(query: str, user_id: str, top_k: int = 5):
    """从知识库检索资料。参数：query 用户问题或关键词，user_id 用户数字 ID，top_k 返回条数。"""
    return await kb_search(query, top_k, user_id=int(user_id))


@tool
async def ingest_document(title: str, content: str, user_id: str):
    """保存用户主动提供的学习资料到个人知识库。参数：title 标题，content 正文，user_id 用户数字 ID。"""
    return await kb_ingest(title, content, user_id=int(user_id))


def _result_body(result: dict, limit: int = 1200) -> str:
    """检索结果的正文片段：长摘要优先，其次短摘要"""
    return _compact_text(result.get("summary") or result.get("snippet") or "", limit)


def _result_source(result: dict, limit: int = 60) -> str:
    """来源名：白名单里的中文名优先，其次搜索服务返回的站点名"""
    return _compact_text(label_for(result.get("url") or "") or result.get("site_name") or "", limit)


def _format_web_reference(topic: str, result: dict, source_text: str = "", fetch_note: str = "") -> tuple[str, str]:
    title = _compact_text(result.get("title") or "联网资料", 120)
    body = _result_body(result)
    url = _normalize_source_url(result.get("url") or "")
    source = _result_source(result)

    kb_title = f"[WEB待审核] {topic} - {title}"
    content_parts = [
        f"主题：{topic}",
        f"来源标题：{title}",
    ]
    if url:
        content_parts.append(f"来源链接：{url}")
    if source:
        content_parts.append(f"来源站点：{source}")
    content_parts.extend(
        [
            "状态说明：该资料由智能体联网检索自动暂存，需管理员审核后才能进入公共知识库。",
            "",
        ]
    )
    if source_text:
        content_parts.extend(["正文提取：", source_text])
    else:
        if fetch_note:
            content_parts.append(f"正文抓取说明：{fetch_note}")
        content_parts.extend(["搜索摘要：", body or title])
    return kb_title, "\n".join(content_parts)


@tool
async def search_web_and_stage_knowledge(topic: str, user_request: str, user_id: str, max_results: int = 5):
    """
    联网搜索资料并暂存到知识库待审核区。
    仅在用户明确要求“联网补充知识库、自动搜索资料入库、为课程补库”时使用。
    user_request 必须传入用户原话，用于防止普通搜索误入库。
    入库 visibility 固定为 pending，管理员审核通过后才会成为公共资料。
    """
    topic = _compact_text(topic, 80)
    if not topic:
        return "请先说明要补充到知识库的主题。"
    if not _is_explicit_stage_request(user_request, topic):
        return (
            "我可以联网搜索资料并提交到知识库待审核区，但这需要用户明确确认。"
            "请让用户回复类似“帮我为微机原理补库”或“把这些资料提交知识库审核”。"
        )

    try:
        limit = max(1, min(int(max_results or 5), 8))
    except Exception:
        limit = 5

    results, collect_note = await search_collect(topic, max_results=max(limit * 3, 12))
    if not results:
        extra = f"；原因：{collect_note}" if collect_note else ""
        return f"未搜索到可暂存的资料：{topic}{extra}"

    candidates = []
    seen_urls = set()
    for result in results:
        url = _normalize_source_url(result.get("url") or "")
        title = _compact_text(result.get("title") or "", 120)
        body = _result_body(result)
        if not title and not body:
            continue
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        candidates.append(result)
        if len(candidates) >= limit:
            break

    fetch_tasks = [
        fetch_readable_text(_normalize_source_url(result.get("url") or result.get("href") or ""))
        for result in candidates
    ]
    fetched_sources = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    staged = []
    for result, fetched in zip(candidates, fetched_sources):
        url = _normalize_source_url(result.get("url") or result.get("href") or "")
        source_text = ""
        fetch_note = ""
        if isinstance(fetched, Exception):
            fetch_note = f"来源网页抓取失败：{type(fetched).__name__}"
        else:
            source_text, fetch_note = fetched

        kb_title, content = _format_web_reference(topic, result, source_text, fetch_note)
        msg = await kb_ingest(
            title=kb_title,
            content=content,
            user_id=int(user_id),
            visibility="pending",
            category="reference",
        )
        staged.append((kb_title, url, msg))

    if not staged:
        return f"搜索到了结果，但没有可暂存的有效摘要：{topic}"

    lines = [
        f"已为《{topic}》联网暂存 {len(staged)} 条参考资料，状态为待审核。",
        "管理员审核通过后，这些资料才会进入公共知识库。",
    ]
    for idx, (title, url, msg) in enumerate(staged, 1):
        lines.append(f"{idx}. {title}")
        if url:
            lines.append(f"   {url}")
        lines.append(f"   {msg}")
    return "\n".join(lines)


@tool
async def list_knowledge(user_id: str):
    """列出当前用户可见的知识库资料。参数：user_id 用户数字 ID。"""
    records = await kb_list(user_id=int(user_id))
    if not records:
        return "知识库中暂无资料"
    lines = ["知识库资料列表："]
    for i, r in enumerate(records, 1):
        label_map = {"public": "公开", "private": "私有", "pending": "待审核", "rejected": "已驳回"}
        label = label_map.get(r["visibility"], r["visibility"])
        lines.append(f"{i}. [{label}] {r['title']} (id: {r['doc_id']})")
        lines.append(f"   内容摘要：{r['content'][:120]}...")
    return "\n".join(lines)


@tool
async def update_knowledge(doc_id: str, user_id: str, title: str = None, content: str = None):
    """更新当前用户自己的知识库资料。参数：doc_id 资料 ID，title 新标题可选，content 新正文可选。"""
    return await kb_update(doc_id=doc_id, title=title, content=content, user_id=int(user_id), is_admin=False)


@tool
async def delete_knowledge(doc_id: str, user_id: str):
    """删除当前用户自己的私有知识库资料。参数：doc_id 资料 ID，user_id 用户数字 ID。"""
    return await kb_delete(doc_id=doc_id, user_id=int(user_id), is_admin=False)
