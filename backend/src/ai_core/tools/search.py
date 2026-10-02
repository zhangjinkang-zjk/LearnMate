"""联网搜索工具 — 基于博查（Bocha）Web Search API

原实现走自建 SearXNG（SEARXNG_URL 默认 127.0.0.1:8888），但该服务从未部署：
deploy/ 里只有 nginx，.env 里没有任何 SEARXNG_* 变量，依赖它的入口实际一直返回空。
现统一改为付费搜索 API，实际请求由 backend/src/utils/web_search_client.py 承担。

对外接口保持稳定，上游调用方无需改动：
    web_search(query)                     — 智能体工具
    read_web_page(url)                    — 智能体工具（把某一页读成正文）
    search_recent_web_brief(query, n)     — 课堂等待页简报
    search_collect(query, n)              — 联网补库批量收集

**`web_search` 和 `read_web_page` 是一对。** 前者只给标题+摘要+链接，摘要一两句话，
回答不了"这个 API 到底怎么调"；后者把具体那一页读进来。模型自己会把两步串起来用，
不需要为它再造一个组合工具。
"""

import logging
import re

from langchain_core.tools import tool

from backend.src.utils.education_sources import label_for
from backend.src.utils.web_page import fetch_readable_text
from backend.src.utils.web_search_client import is_configured, search_web

logger = logging.getLogger(__name__)

# 机器可读的哨兵，供模型区分「没搜到」和「没配好」
NO_RESULTS_MARK = "【WEB_SEARCH_NO_RESULTS】"
NOT_CONFIGURED_MARK = "【WEB_SEARCH_NOT_CONFIGURED】"

# 默认条数：课堂简报少一些，补库收集多一些
_BRIEF_MAX = 4
_COLLECT_DEFAULT = 12


def _clean_query(query: str) -> str:
    """归一化检索词，并去掉模型偶尔自己加上的 !bang 前缀"""
    text = str(query or "").strip()
    if not text:
        return ""
    parts = [part for part in text.split() if not re.fullmatch(r"!\S*", part)]
    return " ".join(parts).strip()


def _source_label(item: dict) -> str:
    """来源名：优先白名单里的中文名，其次搜索服务返回的站点名"""
    return label_for(str(item.get("url") or "")) or str(item.get("site_name") or "").strip()


def _format_results(query: str, results: list[dict]) -> str:
    if not results:
        return f"{NO_RESULTS_MARK}未找到与「{query}」相关的结果"

    lines = [f"搜索「{query}」结果："]
    for i, r in enumerate(results, 1):
        title = str(r.get("title") or "").strip()
        # 这里刻意是 snippet 优先（补库那条链路是 summary 优先）：
        # 工具输出要短，长摘要只在该开的时候开
        body = str(r.get("snippet") or r.get("summary") or "").strip()
        url = str(r.get("url") or "").strip()
        source = _source_label(r)

        lines.append(f"{i}. {title}" if title else f"{i}.")
        if body:
            lines.append(f"   {body}")
        if url:
            lines.append(f"   {url}")
        if source:
            lines.append(f"   来源：{source}")

    return "\n".join(lines)


async def search_collect(query: str, max_results: int = _COLLECT_DEFAULT) -> tuple[list[dict], str]:
    """批量收集检索结果，供联网补库使用。

    返回 (结果列表, 说明)。说明非空表示这一轮没拿到结果及原因，
    调用方可以把它透给用户，而不是只报"没搜到"。
    """
    cleaned = _clean_query(query)
    if not cleaned:
        return [], ""

    if not is_configured():
        return [], "未配置联网搜索密钥（BOCHA_API_KEY）"

    try:
        limit = max(1, min(int(max_results or _COLLECT_DEFAULT), 50))
    except (TypeError, ValueError):
        limit = _COLLECT_DEFAULT

    # 补库要正文，开 summary 拿长摘要
    results = await search_web(cleaned, count=limit, summary=True, caller="collect")
    if results:
        return results, ""
    return [], "搜索服务未返回结果"


async def search_recent_web_brief(query: str, max_results: int = 3) -> list[dict[str, str]]:
    """快速获取近期公开资讯，供非阻塞的课堂等待页使用。

    调用方在后台执行，任何失败都返回空列表，不向课堂链路抛异常。
    """
    cleaned_query = _clean_query(query)
    if not cleaned_query:
        return []

    try:
        limit = max(1, min(int(max_results), _BRIEF_MAX))
    except (TypeError, ValueError):
        limit = 3

    try:
        results = await search_web(cleaned_query, count=limit, caller="classroom_brief")
    except Exception as exc:
        logger.warning("[Search][ClassroomBrief] 请求失败 query=%r error=%s", cleaned_query, exc)
        return []

    briefs: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = " ".join(str(item.get("title") or "").split())
        if not title or not url or not re.match(r"^https?://", url, re.I) or url in seen_urls:
            continue
        seen_urls.add(url)
        briefs.append(
            {
                "title": title[:100],
                "summary": " ".join(str(item.get("snippet") or item.get("summary") or "").split())[:180],
                "url": url,
                "source": (_source_label(item) or "公开来源")[:32],
                "published_at": str(item.get("published_at") or "").strip()[:32],
            }
        )
        if len(briefs) >= limit:
            break

    logger.info(
        "[Search][ClassroomBrief] 查询 query=%r raw=%s briefs=%s",
        cleaned_query,
        len(results),
        len(briefs),
    )
    return briefs


@tool
async def read_web_page(url: str):
    """打开一个具体网页，读出它的正文。

    什么时候用它：`web_search` 给回候选链接之后，用它把**具体那一页**读进来。
    搜索结果的摘要只有一两句，回答不了"这个 API 到底怎么调""这个骨架里有哪些文件"
    这类问题；而学生问的通常正是这类问题。

    **优先读官方文档**（框架官网、官方仓库里的 README / docs / quickstart），别读二手博客：
    博客常是照着旧版本写的，读起来却和官方文档一样肯定。

    不依赖搜索服务：只要给出地址就能读，没配搜索密钥时它照样能用。
    """
    target = str(url or "").strip()
    if not target:
        return "请给出要打开的网页地址。"

    text, note = await fetch_readable_text(target)
    if not text:
        # 读不到就**如实说读不到**，并且明确要求不要凭记忆补内容 —— 这条链路上
        # "假装读过"是最贵的错误：学生会拿一份编出来的 API 去写代码。
        return (
            f"没能读到这一页（{target}）：{note or '未知原因'}。\n"
            "不要凭记忆补它的内容，也不要猜那一页大概写了什么 —— 如实告诉学生这一页没读到，"
            "可以换一个地址再试。"
        )
    # 抓到了，但**可能没抓干净**（见 web_page.residual_markup_note）。这一句必须带上：
    # 不说的话，模型会把一屏 `<span style="...">` 当成正文读，还会照着它给学生讲。
    warning = f"\n（注意：{note}）" if note else ""
    return f"网页正文（{target}）：{warning}\n\n{text}"


@tool
async def web_search(query: str):
    """搜索公开网页资料，返回标题、摘要、链接和来源。适合查找事实、概念、教程和最新信息。"""
    try:
        cleaned_query = _clean_query(query)
        q = cleaned_query or str(query or "").strip()

        if not is_configured():
            return f"{NOT_CONFIGURED_MARK}联网搜索尚未配置，无法检索「{q}」。"

        results = await search_web(q, count=8, caller="agent_tool")
        return _format_results(q, results)
    except Exception as e:
        logger.warning("[Search] web_search 异常 query=%r", query, exc_info=True)
        return f"搜索异常: {type(e).__name__}: {e!r}"
