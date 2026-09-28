"""外部视频搜索服务单元测试

测试目标：backend/src/service/video/service.py 的 ExternalVideoService
覆盖范围：
- BVID 提取与内嵌播放地址生成
- search() 对检索结果的映射（白名单过滤、来源标注、条数截断）
- search_and_save() 的落库字段契约（上游调用方依赖它不变）
- 时长 / 播放量格式化

不测真实接口：检索已改为博查，测试全部 mock 掉 search_web。
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.service.video.service import (
    ExternalVideoService,
    _embed_url_for,
    _extract_bvid,
    _format_duration,
    _format_view_count,
)

VIDEO_MODULE = "backend.src.service.video.service"

BILI_URL = "https://www.bilibili.com/video/BV1xx411c7mD"
MOOC_URL = "https://www.icourse163.org/course/ZJU-1001"
WEIBO_URL = "https://weibo.com/1234/abcd"


def _result(url: str, title: str = "机械制图基础", **overrides):
    item = {
        "title": title,
        "url": url,
        "snippet": "短摘要",
        "summary": "长摘要内容",
        "site_name": "站点名",
        "published_at": "2025-02-23T08:18:30+08:00",
    }
    item.update(overrides)
    return item


def _patch_search(monkeypatch, embed_results=None, course_results=None):
    """替换 video.service 里的 search_web，返回 mock 以便断言调用参数。

    视频搜索会分两次调用：caller='external_video' 查 embed 档（B 站），
    caller='external_video_course' 查课程/图文档。只传一个列表时两次返回同一批。
    """
    if course_results is None:
        course_results = embed_results

    async def _fake(query, *, count=10, include=None, summary=False, freshness="noLimit", caller=""):
        picked = embed_results if caller == "external_video" else course_results
        return [dict(item) for item in (picked or [])]

    mock = AsyncMock(side_effect=_fake)
    monkeypatch.setattr(f"{VIDEO_MODULE}.search_web", mock)
    return mock


# ═══════════════════════════════════════════════
#  BVID 提取
# ═══════════════════════════════════════════════

class TestExtractBvid:
    def test_standard(self):
        assert _extract_bvid(BILI_URL) == "BV1xx411c7mD"

    def test_with_query_params(self):
        url = "https://www.bilibili.com/video/BV1GJ411x7FH?p=2&spm_id_from=333.788"
        assert _extract_bvid(url) == "BV1GJ411x7FH"

    def test_lowercase_host(self):
        """带 www 与否、大小写都不影响"""
        assert _extract_bvid("https://bilibili.com/video/BV1xx411c7mD") == "BV1xx411c7mD"

    def test_short_link_has_no_bvid(self):
        """b23.tv 短链要跟随跳转才有 BV 号，这里不解析"""
        assert _extract_bvid("https://b23.tv/abcdefg") == ""

    def test_non_video_page(self):
        assert _extract_bvid("https://space.bilibili.com/123") == ""

    def test_non_bilibili(self):
        assert _extract_bvid(MOOC_URL) == ""

    def test_empty_and_none(self):
        assert _extract_bvid("") == ""
        assert _extract_bvid(None) == ""


class TestEmbedUrl:
    def test_bilibili_gets_official_player(self):
        assert _embed_url_for(BILI_URL) == "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD"

    def test_non_bilibili_has_no_embed(self):
        """白名单里只有 B 站能内嵌播放，其他来源一律不给 embed"""
        assert _embed_url_for(MOOC_URL) == ""

    def test_short_link_has_no_embed(self):
        assert _embed_url_for("https://b23.tv/abcdefg") == ""


# ═══════════════════════════════════════════════
#  ExternalVideoService.search
# ═══════════════════════════════════════════════

class TestExternalVideoServiceSearch:
    @pytest.mark.asyncio
    async def test_empty_topic_skips_search(self, monkeypatch):
        mock = _patch_search(monkeypatch, [_result(BILI_URL)])
        assert await ExternalVideoService.search("   ") == []
        mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_bilibili_result_mapped(self, monkeypatch):
        _patch_search(monkeypatch, [_result(BILI_URL, title="机械制图 教学视频")])

        videos = await ExternalVideoService.search("机械制图")

        assert len(videos) == 1
        video = videos[0]
        assert video["title"] == "机械制图 教学视频"
        assert video["page_url"] == BILI_URL
        assert video["embed_url"] == "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD"
        assert video["source_label"] == "B站"

    @pytest.mark.asyncio
    async def test_course_platform_has_no_embed(self, monkeypatch):
        _patch_search(monkeypatch, [_result(MOOC_URL, title="机械制图 国家精品课")])

        videos = await ExternalVideoService.search("机械制图")

        assert len(videos) == 1
        assert videos[0]["embed_url"] == ""
        assert videos[0]["source_label"] == "中国大学MOOC"

    @pytest.mark.asyncio
    async def test_non_whitelisted_domain_dropped(self, monkeypatch):
        """include 只是请求侧建议，博查可能仍返回名单外站点 —— 必须自己再筛一遍"""
        _patch_search(monkeypatch, [_result(WEIBO_URL), _result(BILI_URL)])

        videos = await ExternalVideoService.search("机械制图")

        assert [v["page_url"] for v in videos] == [BILI_URL]

    @pytest.mark.asyncio
    async def test_bilibili_non_video_pages_dropped(self, monkeypatch):
        """B 站上只有 /video/BVxxx 是能播的单个视频页。

        真实抓包里 B 站结果绝大多数是图文专栏（read/）、付费课程（cheese/）、
        收藏夹（medialist/）和未支持的 AV 号 —— 都不能内嵌，混进"视频"列表是错的。
        """
        _patch_search(monkeypatch, [
            _result("https://www.bilibili.com/read/cv26236201", title="图文专栏"),
            _result("https://www.bilibili.com/cheese/play/ss31493", title="付费课程"),
            _result("https://m.bilibili.com/medialist/play/384763561", title="收藏夹"),
            _result("https://m.bilibili.com/video/av838838220", title="AV 号"),
            _result(BILI_URL, title="真正的视频"),
        ])

        videos = await ExternalVideoService.search("机械制图")

        assert [v["title"] for v in videos] == ["真正的视频"]

    @pytest.mark.asyncio
    async def test_bilibili_url_canonicalized(self, monkeypatch):
        """移动域名和 query 尾巴都归一到规范地址"""
        _patch_search(monkeypatch, [_result("https://m.bilibili.com/video/BV1P54y1S7xJ?from=search")])

        video = (await ExternalVideoService.search("机械制图"))[0]

        assert video["page_url"] == "https://www.bilibili.com/video/BV1P54y1S7xJ"
        assert video["embed_url"] == "https://player.bilibili.com/player.html?bvid=BV1P54y1S7xJ"

    @pytest.mark.asyncio
    async def test_course_platform_pages_kept(self, monkeypatch):
        """course 档是课程页不是视频文件，不能按 B 站那套规则被筛掉"""
        _patch_search(monkeypatch, [_result(MOOC_URL)])

        videos = await ExternalVideoService.search("机械制图")

        assert len(videos) == 1
        assert videos[0]["page_url"] == MOOC_URL

    @pytest.mark.asyncio
    async def test_max_results_respected(self, monkeypatch):
        # BV 号的真实格式是 "BV" + 正好 10 位，构造数据必须合法，
        # 否则会被规范化成同一个地址、被去重合并掉
        results = [_result(f"https://www.bilibili.com/video/BV1{i:09d}") for i in range(6)]
        _patch_search(monkeypatch, results)

        videos = await ExternalVideoService.search("机械制图", max_results=2)

        assert len(videos) == 2
        assert len({v["page_url"] for v in videos}) == 2

    @pytest.mark.asyncio
    async def test_same_video_from_different_urls_deduped(self, monkeypatch):
        """同一集的移动端地址和规范地址指向同一个视频，只应出现一次"""
        _patch_search(monkeypatch, [
            _result("https://m.bilibili.com/video/BV1P54y1S7xJ/?from=search", title="移动端"),
            _result("https://www.bilibili.com/video/BV1P54y1S7xJ", title="网页端"),
        ])

        videos = await ExternalVideoService.search("机械制图", max_results=3)

        assert len(videos) == 1
        assert videos[0]["page_url"] == "https://www.bilibili.com/video/BV1P54y1S7xJ"

    @pytest.mark.asyncio
    async def test_missing_fields_degrade_to_empty(self, monkeypatch):
        """博查不给作者 / 时长 / 播放量 / 封面，字段必须在但为空，下游才不会炸"""
        _patch_search(monkeypatch, [_result(BILI_URL)])

        video = (await ExternalVideoService.search("机械制图"))[0]

        for key in ("title", "author", "duration", "view_count", "description",
                    "cover_url", "page_url", "embed_url", "source", "source_label"):
            assert key in video, f"缺少字段 {key}"
        assert video["author"] == ""
        assert video["view_count"] == 0
        assert video["cover_url"] == ""
        # 下游用它渲染时应该得到空串而不是 "0次"
        assert _format_view_count(video["view_count"]) == ""
        assert _format_duration(video["duration"]) == ""

    @pytest.mark.asyncio
    async def test_whitelist_split_between_two_queries(self, monkeypatch):
        """B 站必须单独查 —— 和十几个课程站点混在一次查询里会被挤掉名额"""
        mock = _patch_search(monkeypatch, [_result(BILI_URL)])

        await ExternalVideoService.search("机械制图")

        assert mock.await_count == 2
        embed_include = mock.call_args_list[0].kwargs["include"]
        course_include = mock.call_args_list[1].kwargs["include"]
        assert "bilibili.com" in embed_include
        assert "icourse163.org" not in embed_include
        assert "icourse163.org" in course_include
        assert "bilibili.com" not in course_include

    @pytest.mark.asyncio
    async def test_embedded_videos_rank_before_course_pages(self, monkeypatch):
        """能播的排前面：先占满 B 站，剩下的位子才给只能跳转的课程页"""
        _patch_search(
            monkeypatch,
            embed_results=[_result(BILI_URL, title="B站视频")],
            course_results=[_result(MOOC_URL, title="MOOC 课程")],
        )

        videos = await ExternalVideoService.search("机械制图", max_results=2)

        assert [v["title"] for v in videos] == ["B站视频", "MOOC 课程"]

    @pytest.mark.asyncio
    async def test_empty_results(self, monkeypatch):
        _patch_search(monkeypatch, [])
        assert await ExternalVideoService.search("不存在的内容") == []


# ═══════════════════════════════════════════════
#  ExternalVideoService.search_and_save（契约回归）
# ═══════════════════════════════════════════════

class TestSearchAndSaveContract:
    """上游 resource/service.py 与 tools/video_search.py 依赖这些字段名，改后端不能破坏它"""

    @pytest.mark.asyncio
    async def test_saved_shape(self, monkeypatch):
        _patch_search(monkeypatch, [_result(BILI_URL, title="机械制图基础")])

        record = MagicMock()
        record.id = 7
        record.topic = "机械制图"
        record.file_url = BILI_URL
        monkeypatch.setattr(f"{VIDEO_MODULE}.GeneratedResource.create", AsyncMock(return_value=record))

        saved = await ExternalVideoService.search_and_save("机械制图", 1)

        assert len(saved) == 1
        assert saved[0]["resource_id"] == 7
        assert saved[0]["resource_type"] == "external_video"
        assert saved[0]["source_label"] == "B站"
        assert saved[0]["title"] == "机械制图基础"
        # 没有播放量时要渲染成空串
        assert saved[0]["view_count_text"] == ""

    @pytest.mark.asyncio
    async def test_no_results_saves_nothing(self, monkeypatch):
        _patch_search(monkeypatch, [])
        create = AsyncMock()
        monkeypatch.setattr(f"{VIDEO_MODULE}.GeneratedResource.create", create)

        assert await ExternalVideoService.search_and_save("不存在的内容", 1) == []
        create.assert_not_awaited()


# ═══════════════════════════════════════════════
#  格式化
# ═══════════════════════════════════════════════

class TestFormatDuration:
    def test_seconds(self):
        assert _format_duration(90) == "1:30"

    def test_hours(self):
        assert _format_duration(3725) == "1:02:05"

    def test_colon_string(self):
        assert _format_duration("12:34") == "12:34"

    def test_zero_and_none(self):
        assert _format_duration(0) == ""
        assert _format_duration(None) == ""

    def test_garbage(self):
        assert _format_duration("abc") == ""


class TestFormatViewCount:
    def test_wan(self):
        assert _format_view_count(888888) == "88.9万次"

    def test_under_ten_thousand(self):
        assert _format_view_count(9999) == "9999次"

    def test_zero_and_none(self):
        assert _format_view_count(0) == ""
        assert _format_view_count(None) == ""
