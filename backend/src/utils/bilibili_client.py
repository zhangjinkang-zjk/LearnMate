"""B 站视频检索客户端 — 全站「按关键词找教学视频」的唯一出口

为什么不用博查搜视频：博查是**网页**搜索引擎，B 站视频页正文稀薄、JS 渲染，
索引质量天然差。实测 11 组查询（宽的窄的都有）平均只捞到 1.4 条真视频页，
其余全是 /read/ 专栏、/cheese/ 付费课、/medialist/ 收藏夹、/opus/ 动态。
而 B 站自己的搜索接口返回的 20 条**全是视频**，还带播放量 / 时长 / 封面 / UP 主 ——
恰好是博查填不满的那几个字段。这不是查询词的差距，是索引结构的差距。

⚠️ 稳定性说明（改这里之前必须知道）：
这走的是 B 站**未公开的 web 接口**，不是正式开放 API。
新接口 `x/web-interface/wbi/search/type` 已经要求 `v_voucher` 风控验证（实测被拦），
这里用的是老接口 `x/web-interface/search/type`，带 buvid3 指纹即可通。
**随时可能被堵**，所以调用方必须准备降级路径 —— 见 service/video/service.py
里 ExternalVideoService.search 的博查兜底，B 站返回空时会自动退回去。

设计要点：
- 未配置 / 超时 / 风控 / 结构变化一律**返回空列表并记日志，不抛异常**
- 结果按关键词缓存进 Redis，命中不发请求
- 出站加最小间隔节流，避免短时间连打触发风控
- buvid3 指纹按进程缓存一次
"""

import asyncio
import html
import logging
import os
import re
import time

import httpx

logger = logging.getLogger(__name__)

SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"

# B 站对默认的 httpx UA 更容易风控，用真实浏览器 UA
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_REFERER = "https://www.bilibili.com/"

MAX_LIMIT = 50
DEFAULT_LIMIT = 10
_PAGE_SIZE = 20  # 接口单页上限就是 20，传更大也只回 20
_MAX_PAGES = 3

_BVID_RE = re.compile(r"^BV[0-9A-Za-z]{10}$")
_TAG_RE = re.compile(r"<[^>]+>")
_DURATION_RE = re.compile(r"^[\d:]+$")

# 风控 / 限流类响应码：遇到直接放弃，不要重试打接口
_RISK_CODES = {-412, -352, -509}

# 触发风控/限流时统一的失败原因标记，供调用方判断要不要熔断
RISK_REASON = "风控或限流"

_throttle_lock = asyncio.Lock()
_last_call_at = 0.0
_buvid3: str = ""
_buvid4: str = ""
# 熔断截止时刻。实测密集请求会被 412 封 IP —— 而且是**封 IP 不是封指纹**，
# 换全新 buvid3 照样 412，间隔拉到 3 秒也没用。所以一旦被限流必须主动收手，
# 静默一段时间让调用方走降级路径，绝不能继续打接口。
_circuit_until = 0.0


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


def is_configured() -> bool:
    """B 站搜索不需要 key，默认就可用；留一个开关便于出问题时整体摘掉"""
    return (os.getenv("BILIBILI_SEARCH_ENABLED", "1") or "").strip().lower() not in {"0", "false", "no"}


# ── 字段规范化 ────────────────────────────────────────────────

def _clean_text(value) -> str:
    """去掉 <em class="keyword"> 高亮标签并还原 HTML 实体"""
    return html.unescape(_TAG_RE.sub("", str(value or ""))).strip()


def _safe_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _clean_duration(value) -> str:
    """`duration` 形如 "3:48" / "217:17"，取不到时是 "--"

    原样返回给 service 层的 _format_duration 解析，它能处理 MM:SS 和 HH:MM:SS。
    """
    raw = str(value or "").strip()
    return raw if raw and _DURATION_RE.fullmatch(raw) else ""


def _normalize_cover(raw) -> str:
    """封面在结果里可能是 //i2.hdslb.com/... 或 http://，统一成 https"""
    url = str(raw or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return f"https://{url[len('http://'):]}"
    return url if url.startswith("https://") else ""


def _normalize_video(item: dict) -> dict | None:
    """把搜索结果条目映射成内部统一结构；拿不到可播放的单个视频页就丢弃"""
    bvid = str(item.get("bvid") or "").strip()
    if not _BVID_RE.match(bvid):
        # 付费课程（课堂）、合集、用户等条目没有 bvid，拼不出可播放的视频页
        return None
    return {
        "bvid": bvid,
        "title": _clean_text(item.get("title")),
        "author": _clean_text(item.get("author")),
        "duration": _clean_duration(item.get("duration")),
        "view_count": _safe_int(item.get("play")),
        "description": _clean_text(item.get("description")),
        "cover_url": _normalize_cover(item.get("pic")),
        "page_url": f"https://www.bilibili.com/video/{bvid}",
        "embed_url": f"https://player.bilibili.com/player.html?bvid={bvid}",
        # source 目前没有消费者，source_label 才是展示用的；与博查那条链路保持同构
        "source": "bilibili",
        "source_label": "B站",
    }


# ── 出站与节流 ────────────────────────────────────────────────

def _circuit_open() -> bool:
    return time.monotonic() < _circuit_until


def _open_circuit() -> None:
    """被限流后静默一段时间。默认 10 分钟，可配。"""
    global _circuit_until
    seconds = max(0.0, _env_float("BILIBILI_CIRCUIT_SECONDS", 600))
    _circuit_until = time.monotonic() + seconds
    logger.warning("[Bilibili] 触发风控，熔断 %.0f 秒，期间改走降级路径", seconds)


async def _throttle() -> None:
    """出站最小间隔。短时间连打是触发风控最直接的原因。

    默认 1.5 秒是保守值：实测 0.6 秒间隔下约一半请求被 412 拦掉。
    """
    global _last_call_at
    interval = max(0.0, _env_float("BILIBILI_MIN_INTERVAL", 1.5))
    if interval <= 0:
        return
    async with _throttle_lock:
        wait = interval - (time.monotonic() - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = time.monotonic()


async def _ensure_fingerprint(client: httpx.AsyncClient) -> None:
    """取 buvid3/buvid4 指纹，按进程缓存。缺它搜索接口会触发风控。"""
    global _buvid3, _buvid4
    if not _buvid3:
        try:
            resp = await client.get(SPI_URL)
            data = (resp.json() or {}).get("data") or {}
            _buvid3 = str(data.get("b_3") or "").strip()
            _buvid4 = str(data.get("b_4") or "").strip()
        except Exception as exc:
            logger.warning("[Bilibili] 取 buvid 指纹失败，继续尝试: %s", exc)
    if _buvid3:
        client.cookies.set("buvid3", _buvid3, domain=".bilibili.com")
    if _buvid4:
        client.cookies.set("buvid4", _buvid4, domain=".bilibili.com")


async def _quota_exceeded() -> bool:
    """每日配额闸。接口免费但会风控，得有个上限。配额 <= 0 表示不限制。"""
    quota = _env_int("BILIBILI_DAILY_QUOTA", 3000)
    if quota <= 0:
        return False
    try:
        from backend.src.utils.redis_client import check_rate_limit_key

        return not await check_rate_limit_key("bilibili_search_daily", "global", quota, window=86400)
    except Exception:
        return False


async def _fetch_page(client: httpx.AsyncClient, keyword: str, page: int) -> tuple[list[dict], str]:
    """请求一页结果，返回 (规范化视频, 失败原因)。原因非空表示这页拿不到。"""
    params = {"search_type": "video", "keyword": keyword, "page": page, "page_size": _PAGE_SIZE}
    try:
        resp = await client.get(SEARCH_URL, params=params)
    except httpx.RequestError as exc:
        return [], f"请求失败 {exc}"

    if resp.status_code in (412, 429):
        return [], RISK_REASON
    if resp.status_code != 200:
        return [], f"HTTP {resp.status_code}"

    try:
        payload = resp.json()
    except ValueError:
        return [], "响应不是合法 JSON"
    if not isinstance(payload, dict):
        return [], "响应结构异常"

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    code = payload.get("code")
    # 新版风控会在正常 code 里塞一个 v_voucher 挑战，等同于被拦
    if code in _RISK_CODES or "v_voucher" in data:
        return [], RISK_REASON
    if code != 0:
        return [], f"接口返回 code={code} message={payload.get('message')}"

    raw = data.get("result")
    if not isinstance(raw, list):
        return [], ""
    return [v for v in (_normalize_video(i) for i in raw if isinstance(i, dict)) if v], ""


# ── 对外接口 ──────────────────────────────────────────────────

async def search_videos(keyword: str, *, limit: int = DEFAULT_LIMIT, caller: str = "") -> list[dict]:
    """按关键词检索 B 站视频，返回统一结构的列表；任何失败都降级成空列表。

    Args:
        keyword: 检索词。**核心词越少召回越好**，别把整句教学描述塞进来
            （"RAG原理：检索增强生成解决什么问题" 这种句子级查询召回会很差）
        limit: 期望条数（夹到 1..50），超过单页 20 条会翻页
        caller: 仅用于日志，标明调用来源
    """
    text = str(keyword or "").strip()
    if not text or not is_configured():
        return []

    size = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    try:
        from backend.src.utils.redis_client import cache_get, cache_set, _cache_key, _text_hash
        from backend.src.utils.constants import BILIBILI_SEARCH_CACHE_TTL
    except Exception:
        cache_get = None

    cache_key = None
    if cache_get is not None:
        cache_key = _cache_key("bilibili", _text_hash(f"{text}|{size}"))
        cached = await cache_get(cache_key)
        if isinstance(cached, list) and cached:
            return cached[:size]

    if _circuit_open():
        logger.info("[Bilibili] 熔断中，跳过并走降级 caller=%s query=%r", caller, text[:40])
        return []

    if await _quota_exceeded():
        logger.warning("[Bilibili] 今日调用配额已用尽 caller=%s query=%r", caller, text[:40])
        return []

    headers = {
        "User-Agent": _UA,
        "Referer": _REFERER,
        "Accept": "application/json, text/plain, */*",
    }
    timeout = _env_float("BILIBILI_TIMEOUT", 10)

    videos: list[dict] = []
    seen: set[str] = set()
    reason = ""
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            await _ensure_fingerprint(client)
            for page in range(1, _MAX_PAGES + 1):
                if len(videos) >= size:
                    break
                await _throttle()
                items, reason = await _fetch_page(client, text, page)
                if not items:
                    break
                for item in items:
                    if item["bvid"] in seen:
                        continue
                    seen.add(item["bvid"])
                    videos.append(item)
                if len(items) < _PAGE_SIZE:
                    break
    except Exception as exc:  # 兜底：任何意外都不能让上游拿到异常
        logger.warning("[Bilibili] 检索异常 caller=%s query=%r error=%s", caller, text[:40], exc)
        return []

    if reason == RISK_REASON:
        _open_circuit()
        logger.warning("[Bilibili] 被限流 caller=%s query=%r（412/429 或风控挑战），本进程暂停调用", caller, text[:40])
    elif reason:
        logger.warning("[Bilibili] 检索未成功 caller=%s query=%r 原因=%s", caller, text[:40], reason)

    videos = videos[:size]
    if cache_key is not None and videos:
        try:
            await cache_set(cache_key, videos, BILIBILI_SEARCH_CACHE_TTL)
        except Exception:
            logger.debug("[Bilibili] 写缓存失败（降级运行）", exc_info=True)

    logger.info("[Bilibili] caller=%s query=%r 返回 %d 条", caller, text[:40], len(videos))
    return videos
