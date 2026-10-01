# -*- coding: utf-8 -*-
"""SSE 双投递 + 限流 key 没有 TTL —— Redis 这条辅助链路上两个不吭声的 bug。

**一、SSE 每条事件投两次。** `notify_sse` 先写本地内存队列（零延迟），再把消息 publish 到
Redis；而 `_forward_redis_messages` 用 `psubscribe("sse:*")` 监听 —— **Redis Pub/Sub 会把
消息投给发布者自己**，于是同一个进程又把刚发出去的消息灌回同一个队列。部署形态
（`docker-compose.yml` 里有 redis 服务）下每条进度事件客户端都收两份：进度重复渲染、
`__close__` 两次。（本地裸跑没有 Redis，`notify_sse` 那步降级、转发器也不启动，所以看不到。）

修法：Redis 载荷外面包一层带来源标记的信封，转发时跳过自己发的。**本地那次投递要留着**
（它是 Redis 不可用时唯一的投递路径），所以要能区分"自己发的"和"别人发的"。

**二、限流 key 可能永远不过期。** `check_rate_limit_key` 原来是 `incr` 之后跟一条
`if count == 1: expire`。两步之间进程被打断、或 expire 失败，这把 key 就留在 Redis 里没有
TTL，之后只增不减 —— 超限之后**永久拒绝**该身份（登录、注册、付费接口当日配额都走它）。
"""

import asyncio
import json

import pytest

from backend.src.utils import redis_client


# ═══════════════════════════════════════════════
#  SSE：信封与转发
# ═══════════════════════════════════════════════

def test_an_envelope_round_trips():
    assert redis_client._unwrap_sse_payload(
        redis_client._wrap_sse_payload({"type": "progress", "pct": 30})
    ) == {"type": "progress", "pct": 30}


def test_a_legacy_payload_without_an_envelope_is_passed_through():
    """滚动重启期间 Stream 里可能还躺着旧格式（没信封）的消息，不能因为拆不出信封就丢掉。"""
    assert redis_client._unwrap_sse_payload('{"type": "progress"}') == {"type": "progress"}


def test_garbage_is_dropped():
    assert redis_client._unwrap_sse_payload("{不是 JSON") is None
    assert redis_client._unwrap_sse_payload(None) is None


class _FakeRedis:
    def __init__(self, pipeline):
        self.pipeline_factory = pipeline
        self.published: list[tuple[str, str]] = []
        self.streamed: list[tuple[str, dict]] = []

    def pipeline(self, transaction=True):
        return self.pipeline_factory()

    async def publish(self, channel, payload):
        self.published.append((channel, payload))

    async def xadd(self, key, fields, maxlen=None, approximate=False):
        self.streamed.append((key, fields))


@pytest.mark.asyncio
async def test_notify_publishes_an_envelope_and_still_delivers_locally(monkeypatch):
    """本进程的订阅者立刻拿到一份，同时发出去的那份带着自己的来源标记。"""
    monkeypatch.setattr(redis_client, "_sse_subscribers", {})
    fake = _FakeRedis(pipeline=None)
    monkeypatch.setattr(redis_client, "get_redis", lambda: _async_return(fake))

    q = redis_client.subscribe_sse("task:1")
    await redis_client.notify_sse("task:1", {"type": "progress", "pct": 10})

    assert q == [{"type": "progress", "pct": 10}], "本地投递被删掉了？那是没 Redis 时唯一的出路"
    channel, payload = fake.published[0]
    assert channel == "sse:task:1"
    assert json.loads(payload)["origin"] == redis_client._SSE_ORIGIN


class _FakePubSub:
    def __init__(self, messages):
        self._messages = messages

    async def psubscribe(self, pattern):
        return None

    async def listen(self):
        for message in self._messages:
            yield message
        # 转发器是个 while True：让它靠取消退出（真实循环也是这么收场的）
        raise asyncio.CancelledError()


class _FakeListeningRedis:
    def __init__(self, messages):
        self._messages = messages

    def pubsub(self):
        return _FakePubSub(self._messages)


def _pmessage(real_channel: str, payload: str) -> dict:
    return {"type": "pmessage", "channel": f"sse:{real_channel}", "data": payload}


@pytest.mark.asyncio
async def test_the_forwarder_skips_messages_this_process_published(monkeypatch):
    """核心回归：自己发的那条不能再灌一遍。"""
    monkeypatch.setattr(redis_client, "_sse_subscribers", {})
    own = redis_client._wrap_sse_payload({"type": "progress", "pct": 10})
    monkeypatch.setattr(redis_client, "get_redis", lambda: _async_return(_FakeListeningRedis([_pmessage("task:1", own)])))

    q = redis_client.subscribe_sse("task:1")
    await redis_client._forward_redis_messages()

    assert q == [], "自己发的事件被转发器又投了一次"


@pytest.mark.asyncio
async def test_the_forwarder_still_forwards_other_processes(monkeypatch):
    """不能靠"干脆不转发"来消除重复 —— 别的进程的消息必须照旧送进来。

    这条和上一条是一对：只有上一条的话，"把转发整段删掉"也能绿。
    """
    monkeypatch.setattr(redis_client, "_sse_subscribers", {})
    foreign = json.dumps(
        {redis_client._SSE_ENVELOPE_KEY: 1, "origin": "别的进程", "data": {"type": "done"}},
        ensure_ascii=False,
    )
    monkeypatch.setattr(redis_client, "get_redis", lambda: _async_return(_FakeListeningRedis([_pmessage("task:1", foreign)])))

    q = redis_client.subscribe_sse("task:1")
    await redis_client._forward_redis_messages()

    assert q == [{"type": "done"}], "别的进程的消息没送到（跨进程 SSE 直接废了）"


@pytest.mark.asyncio
async def test_the_forwarder_accepts_legacy_payloads_without_an_envelope(monkeypatch):
    """别的进程还在跑旧代码时，载荷没有信封 —— 不能当成垃圾丢掉。"""
    monkeypatch.setattr(redis_client, "_sse_subscribers", {})
    legacy = json.dumps({"type": "progress"}, ensure_ascii=False)
    monkeypatch.setattr(redis_client, "get_redis", lambda: _async_return(_FakeListeningRedis([_pmessage("task:1", legacy)])))

    q = redis_client.subscribe_sse("task:1")
    await redis_client._forward_redis_messages()

    assert q == [{"type": "progress"}]


class _FakeStreamRedis:
    def __init__(self, entries):
        self._entries = entries

    async def xrange(self, key, min="-", max="+", count=None):
        return self._entries


@pytest.mark.asyncio
async def test_replay_unwraps_the_envelope(monkeypatch):
    """新连接的历史回放拿到的必须还是业务载荷本身，不是信封。"""
    entries = [
        ("1-1", {"d": redis_client._wrap_sse_payload({"type": "progress"})}),
        ("1-2", {"d": '{"type": "legacy"}'}),
    ]
    monkeypatch.setattr(redis_client, "get_redis", lambda: _async_return(_FakeStreamRedis(entries)))

    assert await redis_client.replay_sse("task:1") == [{"type": "progress"}, {"type": "legacy"}]


# ═══════════════════════════════════════════════
#  限流：INCR 与 EXPIRE 必须一起走事务
# ═══════════════════════════════════════════════

class _FakePipeline:
    def __init__(self, client):
        self.client = client
        self.commands: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incr(self, key):
        self.commands.append(("incr", key))

    def expire(self, key, window, nx=False):
        self.commands.append(("expire", key, window, nx))

    async def execute(self):
        self.client.count += 1
        return [self.client.count, True]


class _RateLimitRedis:
    def __init__(self, count=0):
        self.count = count

    def pipeline(self, transaction=True):
        self.last_pipeline = _FakePipeline(self)
        return self.last_pipeline


def _async_return(value):
    async def _inner():
        return value

    return _inner()


@pytest.mark.asyncio
async def test_incr_and_expire_go_through_one_transaction(monkeypatch):
    """核心回归：两条命令在同一个 pipeline 里，而且 EXPIRE 带 nx。

    拆成两次独立请求就是"进程在两步之间死掉 → 这把 key 永远没有 TTL → 该身份永久被限流"。
    """
    fake = _RateLimitRedis(count=0)
    monkeypatch.setattr(redis_client, "get_redis", lambda: _async_return(fake))

    allowed = await redis_client.check_rate_limit_key("login", "1.2.3.4", max_requests=5, window=60)

    assert allowed is True
    assert fake.last_pipeline.commands == [
        ("incr", "ratelimit:login:1.2.3.4"),
        ("expire", "ratelimit:login:1.2.3.4", 60, True),
    ], "INCR 和 EXPIRE 不在同一次事务里（或者 EXPIRE 丢了 nx）"


@pytest.mark.asyncio
async def test_over_the_limit_is_refused(monkeypatch):
    fake = _RateLimitRedis(count=5)
    monkeypatch.setattr(redis_client, "get_redis", lambda: _async_return(fake))

    assert await redis_client.check_rate_limit_key("login", "1.2.3.4", max_requests=5) is False


@pytest.mark.asyncio
async def test_redis_being_down_still_fails_open(monkeypatch):
    """降级策略没变：Redis 不可用时不拦人。"""
    async def _boom():
        raise RuntimeError("Redis 挂了")

    monkeypatch.setattr(redis_client, "get_redis", _boom)

    assert await redis_client.check_rate_limit_key("login", "1.2.3.4", max_requests=1) is True


@pytest.mark.asyncio
async def test_an_empty_identity_never_touches_redis(monkeypatch):
    """匿名调用不计数 —— 这条守着 `if not identity: return True` 那道早返回。"""
    calls: list = []

    async def _spy():
        calls.append(1)
        return _RateLimitRedis()

    monkeypatch.setattr(redis_client, "get_redis", _spy)

    assert await redis_client.check_rate_limit_key("login", "", max_requests=1) is True
    assert calls == []
