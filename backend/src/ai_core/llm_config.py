"""LLM 配置 + 优先级限流 — 前台请求优先于后台预生成，每用户每池独立并发"""
import asyncio
import hashlib
import json as _json
import logging
import threading
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

# 文本模型的端点和模型名，这里只是没配时的兜底；`.env` 里配了就以 `.env` 为准。
_TEXT_BASE_URL = os.getenv("AI_BASE_URL") or "https://api.xiaomimimo.com/v1"
_TEXT_MODEL = os.getenv("AI_MODEL") or "mimo-v2.5"

# 视觉模型的端点/模型名（PPT 截图审查等），默认留在 MiMo
_VISION_BASE_URL = os.getenv("VISION_BASE_URL") or "https://api.xiaomimimo.com/v1"
_VISION_MODEL = os.getenv("VISION_MODEL") or "mimo-v2.5"


def _is_deepseek_endpoint(base_url: str | None) -> bool:
    return "deepseek" in (base_url or "").lower()


def _model_line(kind: str, model: str, base_url: str, key_source: str) -> str:
    """拼一行启动日志。**只带 key 的来源变量名，不带 key 本身。**"""
    return f"LLM {kind}模型: {model} @ {base_url}（key 来源: {key_source}）"


def _first_set(*named: tuple[str, str | None]) -> tuple[str | None, str]:
    """按给定顺序取第一个非空的 key，同时返回它的来源环境变量名。

    只回来源名，**不回 key 的值** —— 日志里能看见的值就有可能被贴进工单和截图。
    """
    for name, value in named:
        if value:
            return value, name
    return None, "(未配置)"


def _pick_text_api_key(
    base_url: str | None,
    ai_api_key: str | None,
    vision_api_key: str | None,
    legacy_api_key: str | None,
) -> tuple[str | None, str]:
    """挑文本模型的 key，并说明它来自哪个环境变量。

    **key 必须和端点同源。** 端点和 key 配错时，服务商不会回"你的 key 配错了"，
    只会回 401 / invalid api_key —— 和"key 过期""余额不足"长得一模一样，
    排查时很容易往别处想。所以这里不按固定顺序取，先看端点是哪一家：

    - 端点在 DeepSeek（`AI_BASE_URL` 里带 deepseek）→ 优先项目原有的 `api_key`
      （就是那个 DeepSeek key）。`AI_API_KEY` 里通常还放着 MiMo 的 key，
      换端点时最容易只换端点不换 key，于是 MiMo 的 key 被发到 DeepSeek。
    - 其他端点（默认还是 MiMo）→ 先用 `AI_API_KEY`，再退到视觉 key，
      最后才用 `api_key`，避免只配了 MiMo 密钥的机器把 DeepSeek key 发到 MiMo。
    """
    if _is_deepseek_endpoint(base_url):
        return _first_set(
            ("api_key", legacy_api_key),
            ("AI_API_KEY", ai_api_key),
            ("VISION_API_KEY", vision_api_key),
        )
    return _first_set(
        ("AI_API_KEY", ai_api_key),
        ("VISION_API_KEY", vision_api_key),
        ("api_key", legacy_api_key),
    )


api_key, _TEXT_KEY_SOURCE = _pick_text_api_key(
    _TEXT_BASE_URL,
    os.getenv("AI_API_KEY"),
    os.getenv("VISION_API_KEY"),
    os.getenv("api_key"),
)

# 视觉模型的 key：优先 VISION_API_KEY，其次 AI_API_KEY（同为 MiMo 时是同一个 key），
# 最后才是 api_key。旧写法直接退到 api_key，在文本端点换成 DeepSeek 之后，
# 会把 DeepSeek 的 key 发到 MiMo 端点。
_vision_api_key, _VISION_KEY_SOURCE = _first_set(
    ("VISION_API_KEY", os.getenv("VISION_API_KEY")),
    ("AI_API_KEY", os.getenv("AI_API_KEY")),
    ("api_key", os.getenv("api_key")),
)

def _build_chat_model(**kwargs) -> ChatOpenAI | None:
    key = kwargs.get("api_key")
    if not key:
        logger.warning("LLM API key 未配置；在设置 api_key 之前，AI 调用都会失败。")
        return None
    return ChatOpenAI(**kwargs)


_BASE_TEMPERATURE = 0.3

# 叙述类正文（文档/案例/阅读材料）用的温度：比默认档高，用来打散句式套路、减少"AI 味"。
# 仍受控——评分硬指标要求幻觉率 < 5%，过高会牺牲事实稳定性，故默认 0.7 而非 1.0。
# 结构化输出（习题/导图/PPT 的 JSON）与审核打分继续用默认档。
CREATIVE_TEMPERATURE = float(os.getenv("AI_CREATIVE_TEMPERATURE", "0.7"))


def _build_text_model(temperature: float) -> ChatOpenAI | None:
    return _build_chat_model(
        model=_TEXT_MODEL,
        api_key=api_key,
        base_url=_TEXT_BASE_URL,
        temperature=temperature,
        streaming=True,
        request_timeout=120,  # 单次请求超时 120 秒，避免断连后无限等待
    )


# 启动作业时把"这次跑的是哪个模型、打到哪个端点、key 从哪个变量取的"写进日志。
# 换模型只改 .env，代码里看不出来 —— 出问题时第一件要确认的就是"到底换成功了没有"，
# 而这件事以前只能靠猜。**只打模型名、端点和变量名，不打 key。**
logger.info("%s", _model_line("文本", _TEXT_MODEL, _TEXT_BASE_URL, _TEXT_KEY_SOURCE))
logger.info("%s", _model_line("视觉", _VISION_MODEL, _VISION_BASE_URL, _VISION_KEY_SOURCE))


_raw_llm = _build_text_model(_BASE_TEMPERATURE)

# 非默认温度档的模型按需惰性构建，避免为没人用的档位白建连接池。
_temp_models: dict[float, ChatOpenAI | None] = {}


def _profile_llm(temperature: float) -> ChatOpenAI | None:
    """取指定温度档的底层模型；默认档直接复用 _raw_llm。"""
    if temperature == _BASE_TEMPERATURE:
        return _raw_llm
    if temperature not in _temp_models:
        _temp_models[temperature] = _build_text_model(temperature)
    return _temp_models[temperature]

# 多模态 LLM（默认 MiMo，用于视觉审查 PPT 截图等）
_vision_llm = _build_chat_model(
    model=_VISION_MODEL,
    api_key=_vision_api_key,
    base_url=_VISION_BASE_URL,
    temperature=0.3,
    streaming=False,
)

# 每用户每池并发上限（峰值按 5 用户同时使用设计，总并发 ≤500）
_PER_USER = {
    "ppt": 20,          # 主力：单个 PPT 请求最多约 19 条章节线，5 用户约 100 路
    "document": 20,     # 文档生成（实际受 ThreadPool 限制，20 已够）
    "path": 8,          # 学习路径，低频
    "leader": 3,        # 大纲规划，单次调用，不需多路
    "reviewer": 50,     # 审核，5 用户 ×50=250，对齐 _review_sem
    "classroom": 5,     # 互动课堂：1 规划 + 4 幕并行 + 1 审核
    "advanced": 1,      # 进阶任务智能体：仅在学习里程碑触发时调用
    "transition": 1,    # 课堂等待页：单用户串行，避免过渡摘要放大并发
    "thread": 10,       # 其他同步任务
}
_DEFAULT_PER_USER = 5

_LLM_LOW_PRI_LIMIT = 10       # 有前台请求时，低优先级最多占 10 路

# 每用户每池并发池（异步）
_user_pool_async: dict[tuple[int, str], asyncio.Semaphore] = {}
_user_pool_async_lock = asyncio.Lock()

# 每用户每池并发池（同步 / 线程）
_user_pool_sync: dict[tuple[int, str], threading.BoundedSemaphore] = {}
_user_pool_sync_lock = threading.Lock()

# 优先级限流（全局）：有前台请求时，低优先级全局限流
_async_low = asyncio.Semaphore(_LLM_LOW_PRI_LIMIT)
_async_high_active = 0
_async_high_lock = asyncio.Lock()

_sync_low = threading.BoundedSemaphore(_LLM_LOW_PRI_LIMIT)
_sync_high_active = 0
_sync_high_lock = threading.Lock()


def _get_user_sync_sem(user_id: int, pool: str = "default") -> threading.BoundedSemaphore | None:
    if not user_id:
        return None
    key = (user_id, pool)
    if key in _user_pool_sync:
        return _user_pool_sync[key]
    with _user_pool_sync_lock:
        if key not in _user_pool_sync:
            limit = _PER_USER.get(pool, _DEFAULT_PER_USER)
            _user_pool_sync[key] = threading.BoundedSemaphore(limit)
        return _user_pool_sync[key]


class _PriorityLLM:
    """LLM 代理：每用户每池独立并发 + 全局优先级限流 + 可选的 Redis 响应缓存。"""

    def __init__(
        self,
        raw_llm=None,
        cache_ttl: int = 0,
        cache_ns: str = "llm",
        temp_profiles: bool = False,
    ):
        self._raw = raw_llm or _raw_llm
        self._cache_ttl = cache_ttl  # 0=不缓存；>0 缓存秒数（如 3600=1h）
        self._cache_ns = cache_ns
        # 是否允许调用方按 temperature= 参数切档。仅文本主模型开启；视觉模型是另一套
        # 端点和参数，切档会把它指向错误的模型。
        self._temp_profiles = temp_profiles

    def _target(self, temperature: float | None):
        """解析本次调用用哪个底层模型与缓存命名空间。

        温度不同，同一 prompt 的结果不可互相复用，所以命名空间必须带上温度档，
        否则调高温度后仍会读回默认档的缓存，切档形同虚设。
        """
        if temperature is None or not self._temp_profiles:
            return self._raw, self._cache_ns
        temp = float(temperature)
        if temp == _BASE_TEMPERATURE:
            return self._raw, self._cache_ns
        return _profile_llm(temp), f"{self._cache_ns}:t{temp:g}"

    def __getattr__(self, name):
        if self._raw is None:
            raise RuntimeError("AI model is not configured. Set api_key in backend/.env.")
        return getattr(self._raw, name)

    @staticmethod
    def _prompt_to_key(prompt) -> str | None:
        """将 prompt 转为 SHA256 缓存 key（仅纯文本 prompt 可缓存）"""
        try:
            raw = str(prompt)
            if len(raw) < 10:
                return None
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()
        except Exception:
            return None

    async def ainvoke(
        self,
        prompt,
        priority: str = "high",
        user_id: int = 0,
        pool: str = "default",
        temperature: float | None = None,
    ):
        raw_llm, cache_ns = self._target(temperature)
        # 计算缓存 key（仅在 cache_ttl > 0 时）
        _cache_key_str = self._prompt_to_key(prompt) if self._cache_ttl else None

        # 缓存快速通道：命中直接返回，不走 semaphore
        if _cache_key_str:
            try:
                from backend.src.utils.redis_client import cache_get as _cg, _cache_key as _ck
                _cached = await _cg(_ck(cache_ns, _cache_key_str))
                if _cached is not None and isinstance(_cached, dict) and "content" in _cached:
                    return AIMessage(
                        content=_cached["content"],
                        response_metadata=_cached.get("response_metadata", {}),
                    )
            except Exception:
                logger.debug("已忽略异常 backend/src/ai_core/llm_config.py:116", exc_info=True)

        user_sem = None
        if user_id:
            key = (user_id, pool)
            if key not in _user_pool_async:
                async with _user_pool_async_lock:
                    if key not in _user_pool_async:
                        limit = _PER_USER.get(pool, _DEFAULT_PER_USER)
                        _user_pool_async[key] = asyncio.Semaphore(limit)
            user_sem = _user_pool_async[key]

        async def _call():
            if raw_llm is None:
                raise RuntimeError("AI model is not configured. Set api_key in backend/.env.")
            if user_sem:
                async with user_sem:
                    resp = await raw_llm.ainvoke(prompt)
            else:
                resp = await raw_llm.ainvoke(prompt)
            # 异步回填缓存（仅非流式结果）
            if _cache_key_str and resp and resp.content and len(str(resp.content).strip()) > 5:
                try:
                    from backend.src.utils.redis_client import cache_set as _cs, _cache_key as _ck2
                    _meta = getattr(resp, "response_metadata", {}) or {}
                    await _cs(_ck2(cache_ns, _cache_key_str), {
                        "content": resp.content,
                        "response_metadata": {k: str(v) for k, v in _meta.items() if isinstance(v, (str, int, float))},
                    }, self._cache_ttl)
                except Exception:
                    logger.debug("已忽略异常 backend/src/ai_core/llm_config.py:144", exc_info=True)
            return resp

        global _async_high_active
        if priority == "high":
            async with _async_high_lock:
                _async_high_active += 1
            try:
                return await _call()
            finally:
                async with _async_high_lock:
                    _async_high_active -= 1
        else:
            async with _async_high_lock:
                throttled = _async_high_active > 0
            if throttled:
                async with _async_low:
                    return await _call()
            else:
                return await _call()

    async def astream(
        self,
        prompt,
        priority: str = "high",
        user_id: int = 0,
        pool: str = "default",
        temperature: float | None = None,
    ):
        """逐块产出正文。并发与优先级规则和 ainvoke 保持一致。

        不参与响应缓存：流式的意义就是"马上看到字"，命中缓存等于整段一次性返回，
        等于没流。缓存只服务 ainvoke。
        """
        raw_llm, _ = self._target(temperature)

        user_sem = None
        if user_id:
            key = (user_id, pool)
            if key not in _user_pool_async:
                async with _user_pool_async_lock:
                    if key not in _user_pool_async:
                        _user_pool_async[key] = asyncio.Semaphore(_PER_USER.get(pool, _DEFAULT_PER_USER))
            user_sem = _user_pool_async[key]

        async def _iter():
            if raw_llm is None:
                raise RuntimeError("AI model is not configured. Set api_key in backend/.env.")
            async for chunk in raw_llm.astream(prompt):
                text = getattr(chunk, "content", "") or ""
                if text:
                    yield text

        async def _call():
            if user_sem:
                async with user_sem:
                    async for text in _iter():
                        yield text
            else:
                async for text in _iter():
                    yield text

        global _async_high_active
        if priority == "high":
            async with _async_high_lock:
                _async_high_active += 1
            try:
                async for text in _call():
                    yield text
            finally:
                async with _async_high_lock:
                    _async_high_active -= 1
        else:
            async with _async_high_lock:
                throttled = _async_high_active > 0
            if throttled:
                async with _async_low:
                    async for text in _call():
                        yield text
            else:
                async for text in _call():
                    yield text

    def invoke(
        self,
        prompt,
        priority: str = "high",
        user_id: int = 0,
        pool: str = "default",
        temperature: float | None = None,
    ):
        raw_llm, _ = self._target(temperature)
        user_sem = _get_user_sync_sem(user_id, pool)

        def _call():
            if raw_llm is None:
                raise RuntimeError("AI model is not configured. Set api_key in backend/.env.")
            if user_sem:
                with user_sem:
                    return raw_llm.invoke(prompt)
            else:
                return raw_llm.invoke(prompt)

        global _sync_high_active
        if priority == "high":
            with _sync_high_lock:
                _sync_high_active += 1
            try:
                return _call()
            finally:
                with _sync_high_lock:
                    _sync_high_active -= 1
        else:
            with _sync_high_lock:
                throttled = _sync_high_active > 0
            if throttled:
                with _sync_low:
                    return _call()
            else:
                return _call()


# 环境变量 LLM_CACHE_TTL 控制 LLM 缓存秒数（默认 0=关闭，设置如 300=5分钟）
_DEFAULT_CACHE_TTL = int(os.getenv("LLM_CACHE_TTL", "0"))

llm = _PriorityLLM(cache_ttl=_DEFAULT_CACHE_TTL, temp_profiles=True)
llm_vision = _PriorityLLM(_vision_llm, cache_ttl=_DEFAULT_CACHE_TTL)
