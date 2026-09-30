"""博查（Bocha）Web Search 客户端 — 全站联网搜索的唯一出口

视频搜索（service/video）与智能体联网工具（ai_core/tools/search）都走这里，
替换掉此前的自建 SearXNG（该服务从未部署，调用一直返回空）。

设计要点：
- 未配置 key、超时、接口报错一律**返回空列表并记日志，不抛异常** ——
  调用方按"没搜到"处理，绝不把异常文本当资料喂给模型
- 结果按 query + 限定域名 + 条数缓存进 Redis，命中不发请求
- 每日调用配额用现有 check_rate_limit_key 兜底，按量付费必须有闸
"""

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.bochaai.com"
ENDPOINT_PATH = "/v1/web-search"
MAX_COUNT = 50
DEFAULT_COUNT = 10

# 结果解析结构的版本。**改了 `_normalize_page` / `_extract_images` 就要 +1** ——
# 缓存 key 带它，好让旧解析写下的那批结果立刻失效（否则要等 6 小时 TTL）。
_CACHE_VERSION = 2


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def api_key() -> str:
    return (os.getenv("BOCHA_API_KEY") or "").strip()


def is_configured() -> bool:
    """调用方用它区分「没配 key」和「真的没搜到」，好给出不同的提示"""
    return bool(api_key())


def _base_url() -> str:
    # 官方文档里 api.bocha.cn 与 api.bochaai.com 两种说法都有，做成可配，
    # 万一默认域名不通，改 .env 即可，不用改代码
    raw = (os.getenv("BOCHA_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    return raw or DEFAULT_BASE_URL


def _extract_pages(payload) -> list[dict]:
    """取出网页结果列表。

    文档对响应是否包一层 data 说法不一致，两种外层都兜住。
    """
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    web_pages = data.get("webPages") or data.get("webpages") or {}
    if not isinstance(web_pages, dict):
        return []
    value = web_pages.get("value")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _page_key(url: str) -> str:
    """把 URL 归一成能跨 m./mip./www. 匹配的键。

    博查的图片结果给的是 `hostPageUrl`（`m.imooc.com/article/372181`），网页结果给的是
    `url`（可能是 `mip.` 或带 query 的同一篇），所以匹配前必须先归一化。
    """
    text = str(url or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^(?:m|mip|mobile|www)\.", "", text)
    return text.split("?")[0].rstrip("/")


def _extract_images(payload) -> dict[str, str]:
    """从 `data.images.value` 建「页面 → 封面图」的映射。

    **网页结果里没有封面字段，图片在一个兄弟节点里。** 响应结构是：

        data.webPages.value[]  {url, name, snippet, siteName, siteIcon, …}   ← 无封面
        data.images.value[]    {hostPageUrl, thumbnailUrl, contentUrl, …}    ← 封面在这
        data.videos            null

    每条图都带 `hostPageUrl`（这张图属于哪个页面），按 `_page_key` 归一化后与
    `webPages` 的 url **精确对得上** —— 实测两组查询交集 5/5、3/3。

    **以前这个节点从来没被读过**（只取了 `webPages`），于是所有结果的 `thumbnail`
    恒为空，还被误当成"博查不给封面"。这就是为什么现在要单独一个函数把它捞出来：
    封面一直在响应里，是我们没接。

    图片本身可能挂在 CDN 域（`imgapi.imooc.com`），与页面域不同 —— 不影响，我们只
    用它配**已经过白名单的页面**，不单独把图片当检索结果。

    防御式解析：结构不对就返回空 dict，绝不让它把整次搜索带崩。
    """
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    images = data.get("images") if isinstance(data, dict) else None
    if not isinstance(images, dict):
        return {}
    value = images.get("value")
    if not isinstance(value, list):
        return {}
    mapping: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = _page_key(item.get("hostPageUrl"))
        image = str(item.get("thumbnailUrl") or item.get("contentUrl") or "").strip()
        # 同一个页面可能有多张图，取第一张（响应里靠前的通常是头图）
        if key and image.startswith(("http://", "https://")) and key not in mapping:
            mapping[key] = image
    return mapping


def _normalize_page(item: dict, image_map: dict[str, str] | None = None) -> dict | None:
    """把博查的 WebPageValue 映射成内部统一结构，无 URL 的丢弃。

    `image_map` 是 `_extract_images()` 从兄弟节点建的「页面 → 封面」映射：网页结果自己
    没有封面字段，要拿它补上。
    """
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    own = str(item.get("thumbnail") or item.get("thumbnailUrl") or item.get("imageUrl") or "").strip()
    return {
        "title": " ".join(str(item.get("name") or "").split()),
        "url": url,
        "snippet": " ".join(str(item.get("snippet") or "").split()),
        # summary 需要请求时开 summary=true 才返回，可能为空
        "summary": " ".join(str(item.get("summary") or "").split()),
        "site_name": str(item.get("siteName") or "").strip(),
        # 网页结果自己那份优先（留着以防博查哪天真的加进来），否则用 images 节点里配到的那张
        "thumbnail": own or (image_map or {}).get(_page_key(url), ""),
        # datePublished 是 UTC+8；dateLastCrawled 的 Z 结尾实为 UTC+8，官方建议优先用前者
        "published_at": str(item.get("datePublished") or "").strip(),
        "favicon": str(item.get("siteIcon") or "").strip(),
    }


async def _quota_exceeded() -> bool:
    """每日配额闸。配额 <= 0 表示不限制。Redis 不可用时放行。"""
    quota = _env_int("WEB_SEARCH_DAILY_QUOTA", 500)
    if quota <= 0:
        return False
    try:
        from backend.src.utils.redis_client import check_rate_limit_key

        return not await check_rate_limit_key("bocha_search_daily", "global", quota, window=86400)
    except Exception:
        return False


async def search_web(
    query: str,
    *,
    count: int = DEFAULT_COUNT,
    include: str | None = None,
    summary: bool = False,
    freshness: str = "noLimit",
    caller: str = "",
) -> list[dict]:
    """检索网页，返回统一结构的列表；任何失败都降级成空列表。

    Args:
        query: 检索词
        count: 期望条数（夹到 1..50；实际可能更少，博查会过滤低质量结果）
        include: 限定域名，逗号分隔，例如 "bilibili.com,icourse163.org"
        summary: 是否要长文本摘要（开启后返回项才有 summary 字段）
        freshness: noLimit / oneDay / oneWeek / oneMonth / oneYear / 日期范围
        caller: 仅用于日志，标明调用来源
    """
    text = str(query or "").strip()
    if not text:
        return []

    if not is_configured():
        logger.warning("[WebSearch] BOCHA_API_KEY 未配置，跳过联网搜索 caller=%s query=%r", caller, text[:60])
        return []

    size = max(1, min(int(count or DEFAULT_COUNT), MAX_COUNT))

    try:
        from backend.src.utils.redis_client import cache_get, cache_set, _cache_key, _text_hash
        from backend.src.utils.constants import WEB_SEARCH_CACHE_TTL
    except Exception:
        cache_get = None

    cache_key = None
    if cache_get is not None:
        # `_CACHE_VERSION` 进 key：改了响应解析就要 +1，否则 Redis 里那批**按旧解析写的**
        # 结果会顶着 6 小时 TTL 继续被返回，新加的封面等半天才出现。
        # v2 = 开始从 data.images 取封面（v1 的结果 thumbnail 恒为空）。
        cache_key = _cache_key(
            "websearch",
            _text_hash(f"v{_CACHE_VERSION}|{text}|{include or ''}|{size}|{int(bool(summary))}"),
        )
        cached = await cache_get(cache_key)
        if isinstance(cached, list):
            return cached

    if await _quota_exceeded():
        logger.warning("[WebSearch] 今日调用配额已用尽，跳过 caller=%s query=%r", caller, text[:60])
        return []

    body: dict = {"query": text, "count": size, "summary": bool(summary), "freshness": freshness}
    if include:
        body["include"] = include

    timeout = _env_float("BOCHA_TIMEOUT", 12)
    url = f"{_base_url()}{ENDPOINT_PATH}"
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.RequestError as exc:
        logger.warning("[WebSearch] 请求失败 caller=%s query=%r error=%s", caller, text[:60], exc)
        return []

    if resp.status_code == 401:
        # 博查的 401 同时表示 key 无效 / 余额不足 / 频率超限，必须把响应体带出来才分得清
        logger.error("[WebSearch] 401 鉴权失败（key 无效 / 余额不足 / 频率超限）：%s", resp.text[:300])
        return []
    if resp.status_code >= 400:
        logger.warning(
            "[WebSearch] HTTP %s caller=%s query=%r body=%s",
            resp.status_code, caller, text[:60], resp.text[:200],
        )
        return []

    try:
        payload = resp.json()
    except ValueError:
        logger.warning("[WebSearch] 响应不是合法 JSON caller=%s query=%r", caller, text[:60])
        return []

    # 封面在兄弟节点 data.images 里，必须先建好「页面 → 图」的映射再映射网页
    image_map = _extract_images(payload)
    results = [item for item in (_normalize_page(page, image_map) for page in _extract_pages(payload)) if item]

    if cache_key is not None and results:
        try:
            await cache_set(cache_key, results, WEB_SEARCH_CACHE_TTL)
        except Exception:
            logger.debug("[WebSearch] 写缓存失败（降级运行）", exc_info=True)

    logger.info("[WebSearch] caller=%s query=%r 返回 %d 条", caller, text[:60], len(results))
    return results
