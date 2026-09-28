"""B 站视频检索客户端单元测试

测试目标：backend/src/utils/bilibili_client.py
覆盖范围：
- 字段规范化（<em> 高亮清理、封面协议补全、时长 "--"、bvid 合法性）
- 响应解析与风控识别（412 / 429 / code=-412 / v_voucher 挑战）
- 熔断：被限流后不再打接口，让调用方走降级路径

**全部不联网**：请求层用桩客户端替换，测试里一次真实请求都不发。

背景：这个接口是未公开的 web 接口，实测密集请求会被 **412 封 IP**
（换全新 buvid3 指纹照样 412、间隔拉到 3 秒也没用），所以熔断不是可选项。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx

from backend.src.utils import bilibili_client as bc


async def _none(*args, **kwargs):
    return None


async def _true(*args, **kwargs):
    return True


async def _noop(*args, **kwargs):
    return None


# ═══════════════════════════════════════════════
#  桩：替换掉 httpx.AsyncClient 的 get
# ═══════════════════════════════════════════════

class _StubResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("不是 JSON")
        return self._payload


class _StubClient:
    def __init__(self, response):
        self._response = response
        self.calls: list[tuple] = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _video_item(bvid="BV1xx411c7mD", **overrides):
    item = {
        "bvid": bvid,
        "title": '机械制图 <em class="keyword">基础</em>',
        "author": "某 UP 主",
        "duration": "12:34",
        "play": 49927,
        "description": "课程简介",
        "pic": "//i2.hdslb.com/bfs/archive/abc.jpg",
    }
    item.update(overrides)
    return item


def _bvid_at(index: int) -> str:
    """BV + 正好 10 位。写错位数会被规范化成同一个地址、被去重合并掉"""
    return f"BV1{index:09d}"


def _payload(items):
    return {"code": 0, "message": "OK", "data": {"result": items}}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """干净状态 + 不碰 Redis：既保证确定性，也不把真实缓存写脏"""
    monkeypatch.setattr(bc, "_buvid3", "")
    monkeypatch.setattr(bc, "_buvid4", "")
    monkeypatch.setattr(bc, "_circuit_until", 0.0)
    monkeypatch.setattr(bc, "_last_call_at", 0.0)
    monkeypatch.setenv("BILIBILI_MIN_INTERVAL", "0")  # 测试不等待

    from backend.src.utils import redis_client

    monkeypatch.setattr(redis_client, "cache_get", _none)
    monkeypatch.setattr(redis_client, "cache_set", _none)
    monkeypatch.setattr(redis_client, "check_rate_limit_key", _true)


# ═══════════════════════════════════════════════
#  字段规范化
# ═══════════════════════════════════════════════

class TestNormalizeVideo:
    def test_full_item(self):
        v = bc._normalize_video(_video_item())

        assert v["bvid"] == "BV1xx411c7mD"
        assert v["title"] == "机械制图 基础"  # <em> 高亮被清掉
        assert v["author"] == "某 UP 主"
        assert v["duration"] == "12:34"
        assert v["view_count"] == 49927
        assert v["cover_url"] == "https://i2.hdslb.com/bfs/archive/abc.jpg"
        assert v["page_url"] == "https://www.bilibili.com/video/BV1xx411c7mD"
        assert v["embed_url"] == "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD"
        assert v["source_label"] == "B站"

    def test_empty_bvid_dropped(self):
        """付费课程（课堂）、合集这些条目没有 bvid，拼不出可播放的单个视频页"""
        assert bc._normalize_video(_video_item(bvid="")) is None

    def test_short_bvid_dropped(self):
        """BV 号必须是 "BV" + 正好 10 位"""
        assert bc._normalize_video(_video_item(bvid="BV123")) is None

    def test_av_number_dropped(self):
        assert bc._normalize_video(_video_item(bvid="av838838220")) is None

    def test_duration_placeholder_is_empty(self):
        """取不到时长时接口给的是 "--"，不能当成有效时长传给前端"""
        assert bc._normalize_video(_video_item(duration="--"))["duration"] == ""

    def test_duration_garbage_is_empty(self):
        assert bc._normalize_video(_video_item(duration="未知"))["duration"] == ""

    def test_play_may_be_string(self):
        assert bc._normalize_video(_video_item(play="--"))["view_count"] == 0

    def test_cover_http_upgraded(self):
        v = bc._normalize_video(_video_item(pic="http://i0.hdslb.com/x.jpg"))
        assert v["cover_url"] == "https://i0.hdslb.com/x.jpg"

    def test_cover_missing_is_empty(self):
        assert bc._normalize_video(_video_item(pic=None))["cover_url"] == ""

    def test_html_entities_unescaped(self):
        v = bc._normalize_video(_video_item(title="RAG &amp; 检索"))
        assert v["title"] == "RAG & 检索"


# ═══════════════════════════════════════════════
#  _fetch_page 的解析与风控识别
# ═══════════════════════════════════════════════

class TestFetchPage:
    @pytest.mark.asyncio
    async def test_normal_page(self):
        client = _StubClient(_StubResponse(200, _payload([_video_item()])))

        items, reason = await bc._fetch_page(client, "机械制图", 1)

        assert reason == ""
        assert len(items) == 1
        assert client.calls[0][1]["search_type"] == "video"

    @pytest.mark.asyncio
    async def test_412_is_risk(self):
        client = _StubClient(_StubResponse(412, None, "blocked"))
        items, reason = await bc._fetch_page(client, "机械制图", 1)
        assert items == []
        assert reason == bc.RISK_REASON

    @pytest.mark.asyncio
    async def test_429_is_risk(self):
        client = _StubClient(_StubResponse(429, None))
        _, reason = await bc._fetch_page(client, "机械制图", 1)
        assert reason == bc.RISK_REASON

    @pytest.mark.asyncio
    async def test_risk_code_in_body(self):
        """HTTP 200 但 body 里 code=-412，同样是风控"""
        client = _StubClient(_StubResponse(200, {"code": -412, "message": "请求被拦截"}))
        _, reason = await bc._fetch_page(client, "机械制图", 1)
        assert reason == bc.RISK_REASON

    @pytest.mark.asyncio
    async def test_voucher_challenge_is_risk(self):
        """新接口会在正常响应里塞 v_voucher 验证挑战 —— 解不了，等同于被拦"""
        client = _StubClient(_StubResponse(200, {"code": 0, "data": {"v_voucher": "voucher_x"}}))
        _, reason = await bc._fetch_page(client, "机械制图", 1)
        assert reason == bc.RISK_REASON

    @pytest.mark.asyncio
    async def test_other_error_code_not_risk(self):
        client = _StubClient(_StubResponse(200, {"code": -400, "message": "请求错误"}))
        items, reason = await bc._fetch_page(client, "机械制图", 1)
        assert items == []
        assert reason and reason != bc.RISK_REASON

    @pytest.mark.asyncio
    async def test_result_missing_is_not_risk(self):
        """接口正常但这一页没有结果：算成功，不是风控"""
        client = _StubClient(_StubResponse(200, {"code": 0, "data": {}}))
        items, reason = await bc._fetch_page(client, "机械制图", 1)
        assert items == []
        assert reason == ""

    @pytest.mark.asyncio
    async def test_broken_json(self):
        client = _StubClient(_StubResponse(200, None, "<html>"))
        _, reason = await bc._fetch_page(client, "机械制图", 1)
        assert reason and reason != bc.RISK_REASON

    @pytest.mark.asyncio
    async def test_network_error(self):
        client = _StubClient(httpx.ConnectError("boom"))
        _, reason = await bc._fetch_page(client, "机械制图", 1)
        assert reason and reason != bc.RISK_REASON

    @pytest.mark.asyncio
    async def test_non_dict_items_skipped(self):
        client = _StubClient(_StubResponse(200, _payload(["字符串", _video_item()])))
        items, _ = await bc._fetch_page(client, "机械制图", 1)
        assert len(items) == 1


# ═══════════════════════════════════════════════
#  熔断
# ═══════════════════════════════════════════════

class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_open_circuit_skips_request(self, monkeypatch):
        """熔断期间绝不能继续打接口 —— 继续打只会把封禁拖得更久"""
        called = []

        async def _boom(*args, **kwargs):
            called.append(1)
            return [], ""

        monkeypatch.setattr(bc, "_fetch_page", _boom)
        monkeypatch.setattr(bc, "_ensure_fingerprint", _noop)
        bc._open_circuit()

        assert await bc.search_videos("熔断期间的查询词", limit=3) == []
        assert called == []

    @pytest.mark.asyncio
    async def test_circuit_expires(self, monkeypatch):
        """熔断是有期限的，过期后要恢复尝试"""
        async def _items(client, keyword, page):
            return [bc._normalize_video(_video_item())], ""

        monkeypatch.setattr(bc, "_fetch_page", _items)
        monkeypatch.setattr(bc, "_ensure_fingerprint", _noop)

        videos = await bc.search_videos("熔断已过期的查询词", limit=3)

        assert len(videos) == 1


# ═══════════════════════════════════════════════
#  search_videos 的边界
# ═══════════════════════════════════════════════

class TestSearchVideos:
    @pytest.mark.asyncio
    async def test_empty_keyword(self):
        assert await bc.search_videos("   ") == []

    @pytest.mark.asyncio
    async def test_disabled_by_env(self, monkeypatch):
        monkeypatch.setenv("BILIBILI_SEARCH_ENABLED", "0")
        assert await bc.search_videos("机械制图") == []

    @pytest.mark.asyncio
    async def test_limit_clamped_to_at_least_one(self, monkeypatch):
        async def _items(client, keyword, page):
            return [bc._normalize_video(_video_item())], ""

        monkeypatch.setattr(bc, "_fetch_page", _items)
        monkeypatch.setattr(bc, "_ensure_fingerprint", _noop)

        videos = await bc.search_videos("limit 归零的查询词", limit=0)

        assert len(videos) == 1

    @pytest.mark.asyncio
    async def test_risk_result_opens_circuit(self, monkeypatch):
        async def _risk(client, keyword, page):
            return [], bc.RISK_REASON

        monkeypatch.setattr(bc, "_fetch_page", _risk)
        monkeypatch.setattr(bc, "_ensure_fingerprint", _noop)

        assert await bc.search_videos("会被风控的查询词") == []
        assert bc._circuit_open() is True, "被限流后必须熔断"

    @pytest.mark.asyncio
    async def test_dedupes_across_pages(self, monkeypatch):
        """翻页时同一条可能重复出现。

        第一页必须凑满 _PAGE_SIZE 才会触发翻页，否则这个用例根本没测到翻页。
        """
        first_page = [bc._normalize_video(_video_item(bvid=_bvid_at(i))) for i in range(bc._PAGE_SIZE)]
        second_page = [
            bc._normalize_video(_video_item(bvid=_bvid_at(0))),      # 与第一页重复
            bc._normalize_video(_video_item(bvid=_bvid_at(99))),     # 新的
        ]
        pages = [first_page, second_page]

        async def _items(client, keyword, page):
            return pages[page - 1], ""

        monkeypatch.setattr(bc, "_fetch_page", _items)
        monkeypatch.setattr(bc, "_ensure_fingerprint", _noop)

        videos = await bc.search_videos("翻页去重的查询词", limit=bc._PAGE_SIZE + 1)

        assert len(videos) == bc._PAGE_SIZE + 1
        assert len({v["bvid"] for v in videos}) == bc._PAGE_SIZE + 1
