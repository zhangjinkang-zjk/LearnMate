"""博查联网搜索客户端单元测试

测试目标：backend/src/utils/web_search_client.py
覆盖范围：
- 响应外层两种包裹（data.webPages / webPages）都能解析
- 未配置 key、HTTP 报错、超时、响应非 JSON —— 一律降级成空列表，不抛异常
- include 限定域名确实进了请求体
- count 夹取范围
- 缓存命中时不再发第二次请求

不测真实接口：本环境没有 BOCHA_API_KEY，全部靠 mock。
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.utils.web_search_client import MAX_COUNT, is_configured, search_web

MODULE = "backend.src.utils.web_search_client"


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """不连 Redis：缓存一律未命中、配额一律放行，并默认配上一个假 key"""
    import backend.src.utils.redis_client as rc

    monkeypatch.setattr(rc, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(rc, "cache_set", AsyncMock(return_value=None))
    monkeypatch.setattr(rc, "check_rate_limit_key", AsyncMock(return_value=True))
    monkeypatch.setenv("BOCHA_API_KEY", "sk-test-key")


def _patch_http(monkeypatch, response=None, exc=None):
    """替换 httpx.AsyncClient，返回被 mock 的 client 以便断言请求内容"""
    client = MagicMock()
    client.post = AsyncMock(side_effect=exc) if exc else AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=ctx))
    return client


def _page(url: str, **overrides):
    item = {
        "name": "机械制图基础",
        "url": url,
        "snippet": "讲三视图投影规律",
        "summary": "长文本摘要内容",
        "siteName": "哔哩哔哩",
        "datePublished": "2025-02-23T08:18:30+08:00",
        "siteIcon": "https://www.bilibili.com/favicon.ico",
    }
    item.update(overrides)
    return item


def _payload(value, wrapper: str = "data"):
    """wrapper='data' → {"data": {"webPages": ...}}；wrapper='flat' → {"webPages": ...}"""
    pages = {"totalEstimatedMatches": len(value), "value": value}
    if wrapper == "data":
        return {"code": 200, "log_id": "abc", "data": {"webPages": pages}}
    return {"log_id": "abc", "webPages": pages}


BILI = "https://www.bilibili.com/video/BV1xx411c7mD"


class TestResponseEnvelope:
    """响应外层包裹的两种说法都要兜住"""

    @pytest.mark.asyncio
    async def test_data_wrapped(self, monkeypatch):
        _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)], "data")))
        results = await search_web("机械制图", caller="test")
        assert len(results) == 1
        assert results[0]["url"] == BILI

    @pytest.mark.asyncio
    async def test_flat_wrapped(self, monkeypatch):
        _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)], "flat")))
        results = await search_web("机械制图", caller="test")
        assert len(results) == 1
        assert results[0]["url"] == BILI

    @pytest.mark.asyncio
    async def test_field_mapping(self, monkeypatch):
        """博查字段 → 内部统一结构"""
        _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))
        results = await search_web("机械制图", caller="test")
        item = results[0]
        assert item["title"] == "机械制图基础"
        assert item["snippet"] == "讲三视图投影规律"
        assert item["summary"] == "长文本摘要内容"
        assert item["site_name"] == "哔哩哔哩"
        assert item["published_at"] == "2025-02-23T08:18:30+08:00"

    @pytest.mark.asyncio
    async def test_result_without_url_dropped(self, monkeypatch):
        """没有 URL 的结果无法使用，直接丢弃"""
        pages = [_page(""), _page(BILI)]
        _patch_http(monkeypatch, _FakeResponse(payload=_payload(pages)))
        results = await search_web("机械制图", caller="test")
        assert [r["url"] for r in results] == [BILI]

    @pytest.mark.asyncio
    async def test_empty_value(self, monkeypatch):
        _patch_http(monkeypatch, _FakeResponse(payload=_payload([])))
        assert await search_web("机械制图", caller="test") == []


class TestDegradation:
    """失败一律降级成空列表 —— 绝不把异常文本当资料喂给模型"""

    @pytest.mark.asyncio
    async def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("BOCHA_API_KEY", raising=False)
        assert is_configured() is False
        _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))
        assert await search_web("机械制图", caller="test") == []

    @pytest.mark.asyncio
    async def test_http_500(self, monkeypatch):
        _patch_http(monkeypatch, _FakeResponse(status_code=500, text="server error"))
        assert await search_web("机械制图", caller="test") == []

    @pytest.mark.asyncio
    async def test_http_401(self, monkeypatch):
        """401 = key 无效 / 余额不足 / 频率超限，三种都可能，同样降级"""
        _patch_http(monkeypatch, _FakeResponse(status_code=401, text="unauthorized"))
        assert await search_web("机械制图", caller="test") == []

    @pytest.mark.asyncio
    async def test_timeout(self, monkeypatch):
        _patch_http(monkeypatch, exc=httpx.ConnectTimeout("timed out"))
        assert await search_web("机械制图", caller="test") == []

    @pytest.mark.asyncio
    async def test_non_json_body(self, monkeypatch):
        _patch_http(monkeypatch, _FakeResponse(payload=None, text="<html>502</html>"))
        assert await search_web("机械制图", caller="test") == []

    @pytest.mark.asyncio
    async def test_empty_query_skips_request(self, monkeypatch):
        """空检索词不该浪费一次付费调用"""
        client = _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))
        assert await search_web("   ", caller="test") == []
        client.post.assert_not_called()


class TestRequestShape:
    """请求体要符合博查约定"""

    @pytest.mark.asyncio
    async def test_include_domains_passed(self, monkeypatch):
        client = _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))
        await search_web("机械制图", include="bilibili.com,icourse163.org", caller="test")
        body = client.post.call_args.kwargs["json"]
        assert body["include"] == "bilibili.com,icourse163.org"

    @pytest.mark.asyncio
    async def test_include_omitted_when_absent(self, monkeypatch):
        client = _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))
        await search_web("机械制图", caller="test")
        assert "include" not in client.post.call_args.kwargs["json"]

    @pytest.mark.asyncio
    async def test_count_clamped(self, monkeypatch):
        client = _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))
        await search_web("机械制图", count=999, caller="test")
        assert client.post.call_args.kwargs["json"]["count"] == MAX_COUNT

    @pytest.mark.asyncio
    async def test_auth_header(self, monkeypatch):
        client = _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))
        await search_web("机械制图", caller="test")
        headers = client.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test-key"


class TestCaching:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_http(self, monkeypatch):
        import backend.src.utils.redis_client as rc

        monkeypatch.setattr(rc, "cache_get", AsyncMock(return_value=[{"url": BILI, "title": "缓存命中"}]))
        client = _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))

        results = await search_web("机械制图", caller="test")

        client.post.assert_not_called()
        assert results[0]["title"] == "缓存命中"

    @pytest.mark.asyncio
    async def test_success_writes_cache(self, monkeypatch):
        import backend.src.utils.redis_client as rc

        cache_set = AsyncMock(return_value=None)
        monkeypatch.setattr(rc, "cache_set", cache_set)
        _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))

        await search_web("机械制图", caller="test")

        cache_set.assert_awaited_once()


class TestQuota:
    @pytest.mark.asyncio
    async def test_quota_exceeded_skips_http(self, monkeypatch):
        import backend.src.utils.redis_client as rc

        # 限流助手返回 False = 超限
        monkeypatch.setattr(rc, "check_rate_limit_key", AsyncMock(return_value=False))
        client = _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))

        assert await search_web("机械制图", caller="test") == []
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_quota_means_unlimited(self, monkeypatch):
        """配额配 0 表示不限制"""
        import backend.src.utils.redis_client as rc

        monkeypatch.setenv("WEB_SEARCH_DAILY_QUOTA", "0")
        limiter = AsyncMock(return_value=False)
        monkeypatch.setattr(rc, "check_rate_limit_key", limiter)
        _patch_http(monkeypatch, _FakeResponse(payload=_payload([_page(BILI)])))

        results = await search_web("机械制图", caller="test")

        assert len(results) == 1
        limiter.assert_not_awaited()
