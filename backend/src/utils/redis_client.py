"""
Redis 客户端封装（单例模式）

用法:
    from backend.src.utils.redis_client import get_redis, close_redis

    r = await get_redis()
    await r.set("key", "value")
    await r.get("key")

环境变量: REDIS_URL (默认 redis://localhost:6379/0)
"""
import asyncio
import hashlib
import json as _json
import logging
import os
from typing import Any, Optional

import redis.asyncio as aioredis
from backend.src.utils.constants import REDIS_CONNECT_TIMEOUT, REDIS_SOCKET_TIMEOUT

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """获取 Redis 连接（延迟初始化，单例）"""
    global _redis
    if _redis is None:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis = aioredis.from_url(
            url,
            decode_responses=True,      # 自动将 bytes 解码为 str
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            retry_on_timeout=True,
        )
        # 验证连接
        try:
            pong = await _redis.ping()
            logger.info("Redis 连接成功 (%s) ping=%s",
                         url.replace("redis://", "redis://***@") if "@" in url else url, pong)
        except Exception:
            logger.exception("Redis 连接失败, 服务将以降级模式运行 (无缓存/无SSE跨进程)")
            _redis = None
            raise
    return _redis


async def close_redis():
    """关闭 Redis 连接（应用关闭时调用）"""
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            logger.warning("Redis 关闭异常")
        _redis = None
        logger.info("Redis 连接已关闭")


def is_redis_available() -> bool:
    """检查 Redis 是否已连接"""
    return _redis is not None


# ═══════════════════════════════════════════════
#  通用缓存助手（所有模块共用）
# ═══════════════════════════════════════════════

def _cache_key(*parts: str) -> str:
    """生成带命名空间的缓存 key: cache:{part1}:{part2}:..."""
    return "cache:" + ":".join(parts)


def _text_hash(text: str) -> str:
    """MD5 哈希（用于缓存 key，非安全场景）"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


async def cache_get(key: str) -> Any | None:
    """从 Redis 读取 JSON 缓存，未命中或异常返回 None"""
    try:
        r = await get_redis()
        raw = await r.get(key)
        if raw is None:
            return None
        return _json.loads(raw)
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int):
    """写入 JSON 缓存到 Redis，异常静默降级"""
    try:
        r = await get_redis()
        await r.setex(key, ttl, _json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        logger.debug("Redis cache_set 失败 key=%s ttl=%d（降级运行）", key, ttl)


# ═══════════════════════════════════════════════
#  限流助手（固定窗口，INCR + EXPIRE）
# ═══════════════════════════════════════════════

async def check_rate_limit_key(prefix: str, identity: str, max_requests: int, window: int = 60) -> bool:
    """按任意匿名身份限流，例如客户端 IP 或邮箱。

    INCR 与 EXPIRE **必须一起进事务**（原来是一条 `incr` 之后跟一条 `if count == 1: expire`）：
    两次请求之间只要进程被打断、或者 expire 那一步失败，这把 key 就留在 Redis 里**没有 TTL**
    —— 之后 incr 只增不减，超过 max_requests 之后**永久拒绝**这个身份（登录、注册、付费
    接口的当日配额都走这里）。

    `expire(..., nx=True)` 表示"只在这把 key 还没有 TTL 时设置"：万一真留下了裸 key，
    下一次请求会把它补上过期时间，不会一坏到底。
    """
    if not identity:
        return True
    try:
        r = await get_redis()
        key = f"ratelimit:{prefix}:{identity}"
        async with r.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window, nx=True)
            count, _ = await pipe.execute()
        return count <= max_requests
    except Exception:
        return True  # Redis 不可用时保持现有降级策略


async def check_rate_limit(prefix: str, user_id: int, max_requests: int, window: int = 60) -> bool:
    """检查是否超过限流阈值

    Args:
        prefix: 限流场景前缀，如 "generate"
        user_id: 用户 ID（0 表示匿名）
        max_requests: 窗口内最大请求数
        window: 时间窗口（秒）

    Returns:
        True = 通过（未超限），False = 被限流（超限）
    """
    return await check_rate_limit_key(prefix, f"user:{user_id}" if user_id else "", max_requests, window)


# ═══════════════════════════════════════════════
#  SSE 帮助函数：用 Redis Stream + Pub/Sub 实现跨进程消息队列
# ═══════════════════════════════════════════════

# 内存中的 SSE 订阅者队列（同一个进程内直接用内存，避免 Redis 往返延迟）
_sse_subscribers: dict[str, list] = {}

# 本进程在 Redis 上的身份标记。见 notify_sse / _forward_redis_messages 的说明：
# 发布用的是普通连接、订阅用的是 psubscribe，**Redis 会把消息投给发布者自己** ——
# 不记来源的话，同一条事件会在同一个进程里被投两次（本地一次 + 转发回来一次）。
_SSE_ORIGIN = f"{os.getpid()}-{os.urandom(4).hex()}"

# Redis 载荷的外层信封标记。带它才做拆包，避免把恰好含 origin/data 键的业务事件认错。
_SSE_ENVELOPE_KEY = "__sse_envelope__"


def _wrap_sse_payload(data: dict) -> str:
    return _json.dumps(
        {_SSE_ENVELOPE_KEY: 1, "origin": _SSE_ORIGIN, "data": data},
        ensure_ascii=False,
    )


def _unwrap_sse_payload(raw: Any) -> Any:
    """拆信封；没有信封（旧格式、或别的进程还在跑旧代码）就原样返回。"""
    try:
        payload = _json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(payload, dict) and payload.get(_SSE_ENVELOPE_KEY) == 1:
        return payload.get("data")
    return payload


def subscribe_sse(channel: str) -> list:
    """订阅一个 SSE 频道，返回内存消息队列

    同一个进程内的 notify_sse 会直接写入此队列；
    其他进程的消息通过 Redis Pub/Sub 转发过来。
    """
    q: list = []
    _sse_subscribers.setdefault(channel, []).append(q)
    return q


def unsubscribe_sse(channel: str, q: list):
    """取消订阅"""
    queues = _sse_subscribers.get(channel, [])
    if q in queues:
        queues.remove(q)
    if not queues:
        _sse_subscribers.pop(channel, None)


async def notify_sse(channel: str, data: dict, max_stream_len: int = 200):
    """通知所有订阅者 + 发布到 Redis Pub/Sub + 存 Stream

    1. 本地进程: 直接写入内存队列（零延迟）
    2. 跨进程:   Redis Pub/Sub 推送
    3. 历史回放: Redis Stream 存储（新订阅者重放）
    """
    # 1) 本地内存队列
    queues = _sse_subscribers.get(channel, [])
    for q in queues:
        q.append(data)

    # 2) Redis Pub/Sub + Stream
    try:
        r = await get_redis()
        payload = _wrap_sse_payload(data)
        await r.publish(f"sse:{channel}", payload)
        # Stream 存最近 N 条，用于新连接重放
        await r.xadd(f"sse:{channel}:stream", {"d": payload}, maxlen=max_stream_len, approximate=True)
    except Exception:
        logger.debug("Redis SSE 推送失败 channel=%s (降级运行)", channel)


async def replay_sse(channel: str) -> list[dict]:
    """从 Redis Stream 回放历史消息（新订阅者重放）"""
    try:
        r = await get_redis()
        events = await r.xrange(f"sse:{channel}:stream", min="-", max="+", count=200)
        result = []
        for _, entry in events:
            data = _unwrap_sse_payload(entry.get("d", "{}"))
            if data is not None:
                result.append(data)
        return result
    except Exception:
        return []


async def _forward_redis_messages():
    """后台任务：监听 Redis Pub/Sub，将跨进程消息转发到本地内存队列

    在 main.py 的 startup 中启动一个 asyncio.Task 运行此函数。
    内含自动重连（Redis 断开后每 3 秒重试）。
    """
    retry_delay = 1
    while True:
        try:
            r = await get_redis()
            pubsub = r.pubsub()
            await pubsub.psubscribe("sse:*")
            logger.info("Redis SSE 转发器已启动 (监听 sse:*)")
            retry_delay = 1  # 连接成功后重置重试间隔
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                raw_channel = message["channel"]
                if isinstance(raw_channel, bytes):
                    raw_channel = raw_channel.decode()
                # channel 格式: "sse:{实际频道名}"
                real_channel = raw_channel.split(":", 1)[1] if ":" in raw_channel else raw_channel
                data_raw = message["data"]
                if isinstance(data_raw, bytes):
                    data_raw = data_raw.decode()
                # 跳过 Pub/Sub 内部消息
                if data_raw == "1":
                    continue
                # 自己发布的消息不用再灌一遍：notify_sse 的第 1 步已经投递过了。
                # 不做这一步的话，Redis 可用时每条事件都被投两次 —— 同一个进度在页面上
                # 渲染两遍，`__close__` 也收到两次。
                try:
                    envelope = _json.loads(data_raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(envelope, dict) and envelope.get("origin") == _SSE_ORIGIN:
                    continue
                data = _unwrap_sse_payload(data_raw)
                if data is None:
                    continue
                # 写入本地内存队列
                queues = _sse_subscribers.get(real_channel, [])
                for q in queues:
                    q.append(data)
        except asyncio.CancelledError:
            logger.info("Redis SSE 转发器已取消")
            return
        except Exception:
            logger.warning("Redis SSE 转发器断开，%ds 后重连…", retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)  # 指数退避，最长 30s
