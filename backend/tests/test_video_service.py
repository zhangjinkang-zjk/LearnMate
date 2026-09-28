"""外部视频搜索服务单元测试

测试目标：backend/src/service/video/service.py 的 ExternalVideoService
覆盖范围：
- BVID 提取与内嵌播放地址生成
- 检索词构造（节点标签优先于节点标题）
- search() 的双源编排：B 站优先、课程平台常补、B 站不可用时博查兜底
- 博查那条链路的映射（白名单过滤、来源标注、条数截断）
- search_node_videos() 按节点检索
- search_and_save() 的落库字段契约（上游调用方依赖它不变）
- 时长 / 播放量格式化

**不测真实接口**：两个检索源（B 站接口、博查）在测试里全部 mock，
一次真实请求都不发。
"""
import json
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
    _node_query,
    _parse_tags,
    _rank_by_relevance,
    _video_payload,
    search_node_videos,
)
from backend.src.utils.exceptions import ServiceError

VIDEO_MODULE = "backend.src.service.video.service"

# 博查那三次调用各自的档位，和 service 里的 caller 一一对应
_BOCHA_CALLER_TIERS = {
    "external_video_course": "course",
    "external_video_reading": "reading",
    "external_video_fallback": "embed",
}

BILI_URL = "https://www.bilibili.com/video/BV1xx411c7mD"
BILI_URL_2 = "https://www.bilibili.com/video/BV1P54y1S7xJ"
MOOC_URL = "https://www.icourse163.org/course/ZJU-1001"
WEIBO_URL = "https://weibo.com/1234/abcd"


def _result(url: str, title: str = "机械制图基础", **overrides):
    """博查返回的一条网页结果"""
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


def _bili_video(bvid="BV1xx411c7mD", title="B站视频", **overrides):
    """B 站客户端返回的一条视频（已经是内部结构）"""
    item = {
        "bvid": bvid,
        "title": title,
        "author": "某 UP 主",
        "duration": "12:34",
        "view_count": 49927,
        "description": "课程简介",
        "cover_url": "https://i2.hdslb.com/x.jpg",
        "page_url": f"https://www.bilibili.com/video/{bvid}",
        "embed_url": f"https://player.bilibili.com/player.html?bvid={bvid}",
        "source": "bilibili",
        "source_label": "B站",
    }
    item.update(overrides)
    return item


def _patch_bilibili(monkeypatch, videos=None):
    """替换 B 站客户端。默认返回空 —— 于是走博查兜底，老用例语义不变。"""
    mock = AsyncMock(return_value=[dict(v) for v in (videos or [])])
    monkeypatch.setattr(f"{VIDEO_MODULE}.search_bilibili_videos", mock)
    return mock


def _patch_bocha(monkeypatch, *, course=None, reading=None, embed=None):
    """替换博查。按 caller 分三档：课程平台 / 图文 / B 站兜底。"""
    buckets = {"course": course, "reading": reading, "embed": embed}

    async def _fake(query, *, count=10, include=None, summary=False, freshness="noLimit", caller=""):
        picked = buckets.get(_BOCHA_CALLER_TIERS.get(caller, ""))
        return [dict(item) for item in (picked or [])]

    mock = AsyncMock(side_effect=_fake)
    monkeypatch.setattr(f"{VIDEO_MODULE}.search_web", mock)
    return mock


def _patch_encoder(monkeypatch, scores=None):
    """替换相关性打分器。

    返回的「向量」故意是 1 维：query 恒为 1.0，所以 np.dot 出来的相似度
    就等于对应位置的分值 —— 测试可以直接指定每条结果该得多少分。
    scores 不给时全部返回 1.0（必定过阈值），不关心过滤的用例就不会被拖慢。
    """
    import numpy as np

    async def _fake(texts):
        count = max(0, len(texts) - 1)
        values = [1.0] * count if scores is None else list(scores)
        return np.array([[1.0]] + [[float(v)] for v in values], dtype=np.float32)

    mock = AsyncMock(side_effect=_fake)
    monkeypatch.setattr("backend.src.utils.knowledge_base.encode_many", mock)
    return mock


def _patch_sources(monkeypatch, *, bilibili=None, course=None, reading=None, embed=None, scores=None):
    """同时替换两个检索源和相关性打分器，返回 (bilibili_mock, bocha_mock)"""
    _patch_encoder(monkeypatch, scores)
    return (
        _patch_bilibili(monkeypatch, bilibili),
        _patch_bocha(monkeypatch, course=course, reading=reading, embed=embed),
    )


def _bocha_calls(bocha_mock):
    return {call.kwargs.get("caller"): call for call in bocha_mock.call_args_list}


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
#  检索词构造
# ═══════════════════════════════════════════════

class TestNodeQuery:
    def test_tags_take_priority(self):
        """节点标题是教学描述，标签才是行业通用说法 —— 必须优先用标签"""
        q = _node_query("上下文组装与Prompt注入设计", ["检索上下文组装", "RAG提示词约束", "切片编号引用"])
        assert q == "检索上下文组装 RAG提示词约束"

    def test_at_most_two_tags(self):
        q = _node_query("某主题", ["A", "B", "C", "D"])
        assert q == "A B"

    def test_blank_tags_ignored(self):
        assert _node_query("某主题", ["  ", "RAG原理"]) == "RAG原理"

    def test_falls_back_to_topic(self):
        assert _node_query("大模型应用调用基础：上下文窗口与生成参数") == "大模型应用调用基础 上下文窗口与生成参数"

    def test_no_tags_keeps_topic_without_punctuation(self):
        assert _node_query("IVF倒排索引：聚类分桶") == "IVF倒排索引 聚类分桶"

    def test_empty_everything(self):
        assert _node_query("") == ""

    def test_length_capped(self):
        assert len(_node_query("x" * 200)) <= 60


class TestParseTags:
    def test_json_text_column(self):
        """knowledge_tags 是 JSON **文本**列 —— 直接下标取值会拿到 '['"""
        assert _parse_tags('["Token计数", "上下文窗口"]') == ["Token计数", "上下文窗口"]

    def test_already_a_list(self):
        assert _parse_tags(["A", "B"]) == ["A", "B"]

    def test_broken_json(self):
        assert _parse_tags("{不是数组") == []

    def test_none_and_empty(self):
        assert _parse_tags(None) == []
        assert _parse_tags("") == []
        assert _parse_tags("[]") == []

    def test_non_list_json(self):
        assert _parse_tags('{"a": 1}') == []

    def test_blank_entries_dropped(self):
        assert _parse_tags('["A", "  ", ""]') == ["A"]


# ═══════════════════════════════════════════════
#  _video_payload
# ═══════════════════════════════════════════════

class TestVideoPayload:
    def test_formats_duration_and_views(self):
        payload = _video_payload(_bili_video())
        assert payload["duration_text"] == "12:34"
        assert payload["view_count_text"] == "5.0万次"
        assert payload["source_label"] == "B站"
        assert payload["preview_url"] == payload["embed_url"]

    def test_missing_values_render_empty(self):
        payload = _video_payload({"title": "无数据"})
        assert payload["duration_text"] == ""
        assert payload["view_count_text"] == ""
        assert payload["cover_url"] == ""
        assert payload["embed_url"] == ""


class TestRelevanceFilter:
    """B 站接口永远返回满页，所以"有结果"是假信号 —— 必须按相似度筛一遍"""

    @pytest.mark.asyncio
    async def test_low_similarity_dropped(self, monkeypatch):
        _patch_encoder(monkeypatch, scores=[0.9, 0.4, 0.7])
        videos = [_bili_video(title=f"视频{i}") for i in range(3)]

        kept = await _rank_by_relevance(videos, "机械制图")

        assert [v["title"] for v in kept] == ["视频0", "视频2"]

    @pytest.mark.asyncio
    async def test_sorted_by_similarity(self, monkeypatch):
        """最相关的排最前面 —— B 站自己的排序里塞了很多噪音"""
        _patch_encoder(monkeypatch, scores=[0.6, 0.9, 0.7])
        videos = [_bili_video(title=f"视频{i}") for i in range(3)]

        kept = await _rank_by_relevance(videos, "机械制图")

        assert [v["title"] for v in kept] == ["视频1", "视频2", "视频0"]

    @pytest.mark.asyncio
    async def test_all_below_threshold(self, monkeypatch):
        _patch_encoder(monkeypatch, scores=[0.3, 0.2])
        videos = [_bili_video(title=f"视频{i}") for i in range(2)]

        assert await _rank_by_relevance(videos, "分组聚合与结果导出") == []

    @pytest.mark.asyncio
    async def test_encoder_failure_keeps_original(self, monkeypatch):
        """打分是锦上添花，绝不能因为它把已经拿到的结果弄丢"""
        monkeypatch.setattr(
            "backend.src.utils.knowledge_base.encode_many",
            AsyncMock(side_effect=RuntimeError("模型加载失败")),
        )
        videos = [_bili_video(title="视频0"), _bili_video(bvid="BV1P54y1S7xJ", title="视频1")]

        kept = await _rank_by_relevance(videos, "机械制图")

        assert [v["title"] for v in kept] == ["视频0", "视频1"]

    @pytest.mark.asyncio
    async def test_threshold_zero_disables_filter(self, monkeypatch):
        monkeypatch.setenv("EXTERNAL_VIDEO_MIN_SIMILARITY", "0")
        _patch_encoder(monkeypatch, scores=[0.01, 0.02])
        videos = [_bili_video(title="视频0"), _bili_video(bvid="BV1P54y1S7xJ", title="视频1")]

        kept = await _rank_by_relevance(videos, "机械制图")

        assert len(kept) == 2

    @pytest.mark.asyncio
    async def test_threshold_is_configurable(self, monkeypatch):
        monkeypatch.setenv("EXTERNAL_VIDEO_MIN_SIMILARITY", "0.85")
        _patch_encoder(monkeypatch, scores=[0.9, 0.8])
        videos = [_bili_video(title="视频0"), _bili_video(bvid="BV1P54y1S7xJ", title="视频1")]

        kept = await _rank_by_relevance(videos, "机械制图")

        assert [v["title"] for v in kept] == ["视频0"]

    @pytest.mark.asyncio
    async def test_empty_input_skips_encoder(self, monkeypatch):
        encoder = _patch_encoder(monkeypatch, scores=[])

        assert await _rank_by_relevance([], "机械制图") == []
        encoder.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blank_query_skips_encoder(self, monkeypatch):
        encoder = _patch_encoder(monkeypatch, scores=[0.9])

        kept = await _rank_by_relevance([_bili_video()], "   ")

        assert len(kept) == 1
        encoder.assert_not_awaited()


# ═══════════════════════════════════════════════
#  ExternalVideoService.search 的双源编排
# ═══════════════════════════════════════════════

class TestSourceOrchestration:
    @pytest.mark.asyncio
    async def test_empty_topic_skips_all_sources(self, monkeypatch):
        bili, bocha = _patch_sources(monkeypatch, bilibili=[_bili_video()])

        assert await ExternalVideoService.search("   ") == []
        bili.assert_not_awaited()
        bocha.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bilibili_is_primary(self, monkeypatch):
        bili, _ = _patch_sources(monkeypatch, bilibili=[_bili_video(title="B站视频")])

        videos = await ExternalVideoService.search("机械制图", tags=["机械制图基础"])

        assert videos[0]["title"] == "B站视频"
        assert videos[0]["source_label"] == "B站"
        # 检索词用标签，不是标题
        assert bili.call_args_list[0].args[0] == "机械制图基础"

    @pytest.mark.asyncio
    async def test_bilibili_has_results_skips_bocha_fallback(self, monkeypatch):
        """有真视频在手就不必再花一次付费调用去查召回很差的 B 站档"""
        _, bocha = _patch_sources(monkeypatch, bilibili=[_bili_video()])

        await ExternalVideoService.search("机械制图")

        assert "external_video_fallback" not in _bocha_calls(bocha)

    @pytest.mark.asyncio
    async def test_bocha_fallback_used_when_bilibili_empty(self, monkeypatch):
        """B 站被限流 / 熔断 / 召回为空时，必须还有东西给用户"""
        _, bocha = _patch_sources(monkeypatch, bilibili=[], embed=[_result(BILI_URL, title="兜底视频")])

        videos = await ExternalVideoService.search("机械制图")

        assert [v["title"] for v in videos] == ["兜底视频"]
        assert "external_video_fallback" in _bocha_calls(bocha)

    @pytest.mark.asyncio
    async def test_irrelevant_bilibili_results_filtered_out(self, monkeypatch):
        """真实场景：节点「分组聚合与结果导出」在 B 站会召回「origin合并两个文件」"""
        _patch_sources(
            monkeypatch,
            bilibili=[_bili_video(title="origin合并两个文件")],
            scores=[0.49],
        )

        assert await ExternalVideoService.search("分组聚合与结果导出") == []

    @pytest.mark.asyncio
    async def test_filtered_empty_does_not_trigger_bocha_fallback(self, monkeypatch):
        """被相关性筛空 ≠ B 站没拿到。

        筛空说明这个检索词在 B 站本来就没有好结果，博查的 B 站召回只会更差，
        不该再花一次付费调用去确认这件事。
        """
        _, bocha = _patch_sources(
            monkeypatch,
            bilibili=[_bili_video(title="绝不相关")],
            scores=[0.3],
        )

        assert await ExternalVideoService.search("分组聚合与结果导出") == []
        assert "external_video_fallback" not in _bocha_calls(bocha)

    @pytest.mark.asyncio
    async def test_course_platform_always_queried(self, monkeypatch):
        """课程平台是博查的长处，B 站覆盖不到，无论 B 站结果如何都要补"""
        _, bocha = _patch_sources(
            monkeypatch,
            bilibili=[_bili_video()],
            course=[_result(MOOC_URL, title="MOOC 课程")],
        )

        videos = await ExternalVideoService.search("机械制图", max_results=3)

        assert [v["title"] for v in videos] == ["B站视频", "MOOC 课程"]
        assert "external_video_course" in _bocha_calls(bocha)

    @pytest.mark.asyncio
    async def test_query_tiers_do_not_overlap(self, monkeypatch):
        """B 站档和课程档必须分开查 —— 十几个课程站点混进来会把 B 站名额挤光"""
        _, bocha = _patch_sources(monkeypatch, bilibili=[])

        await ExternalVideoService.search("机械制图")

        calls = _bocha_calls(bocha)
        course_include = calls["external_video_course"].kwargs["include"]
        embed_include = calls["external_video_fallback"].kwargs["include"]
        assert "icourse163.org" in course_include
        assert "bilibili.com" not in course_include
        assert "bilibili.com" in embed_include
        assert "icourse163.org" not in embed_include

    @pytest.mark.asyncio
    async def test_course_and_reading_queried_separately(self, monkeypatch):
        """课程平台必须和图文**分开查**（回归）。

        实测把 course 和 reading 放进同一次 include 时，返回的 20 条**全是掘金文章**，
        一条 MOOC 都没有；单独查 course 则是 20 条全慕课网。名额被内容量更大的
        图文站点挤光了 —— 和 B 站那次是同一个病。
        """
        _, bocha = _patch_sources(monkeypatch, bilibili=[])

        await ExternalVideoService.search("机械制图")

        course_include = _bocha_calls(bocha)["external_video_course"].kwargs["include"]
        assert "icourse163.org" in course_include, "课程平台不在课程档里"
        assert "juejin.cn" not in course_include, "图文混进了课程档，会把课程名额挤光"

    @pytest.mark.asyncio
    async def test_reading_skipped_when_courses_fill_the_slots(self, monkeypatch):
        """图文是兜底不是主力：课程已经凑够就不查，省一次付费调用"""
        _, bocha = _patch_sources(
            monkeypatch,
            bilibili=[],
            course=[_result(f"{MOOC_URL}-{i}", title=f"课程{i}") for i in range(3)],
        )

        videos = await ExternalVideoService.search("机械制图", max_results=3)

        assert len(videos) == 3
        assert "external_video_reading" not in _bocha_calls(bocha)

    @pytest.mark.asyncio
    async def test_reading_used_when_slots_remain(self, monkeypatch):
        _, bocha = _patch_sources(
            monkeypatch,
            bilibili=[],
            course=[_result(MOOC_URL, title="慕课课程")],
            reading=[_result("https://juejin.cn/post/123", title="掘金文章")],
        )

        videos = await ExternalVideoService.search("机械制图", max_results=3)

        assert [v["title"] for v in videos] == ["慕课课程", "掘金文章"]
        assert "external_video_reading" in _bocha_calls(bocha)

    @pytest.mark.asyncio
    async def test_all_sources_empty(self, monkeypatch):
        _patch_sources(monkeypatch, bilibili=[], embed=[], course=[])

        assert await ExternalVideoService.search("不存在的内容") == []

    @pytest.mark.asyncio
    async def test_max_results_respected(self, monkeypatch):
        _patch_sources(
            monkeypatch,
            bilibili=[_bili_video(bvid=f"BV1{i:09d}") for i in range(6)],
        )

        videos = await ExternalVideoService.search("机械制图", max_results=2)

        assert len(videos) == 2
        assert len({v["page_url"] for v in videos}) == 2

    @pytest.mark.asyncio
    async def test_same_video_deduped_across_sources(self, monkeypatch):
        """B 站档和博查兜底档可能给出同一个视频，只应出现一次"""
        _patch_sources(
            monkeypatch,
            bilibili=[_bili_video(bvid="BV1P54y1S7xJ")],
            course=[_result(BILI_URL_2, title="同一个")],
        )

        videos = await ExternalVideoService.search("机械制图", max_results=3)

        assert len(videos) == 1


# ═══════════════════════════════════════════════
#  博查那条链路的映射
# ═══════════════════════════════════════════════

class TestBochaMapping:
    @pytest.mark.asyncio
    async def test_bilibili_result_mapped(self, monkeypatch):
        _patch_sources(monkeypatch, bilibili=[], embed=[_result(BILI_URL, title="机械制图 教学视频")])

        videos = await ExternalVideoService.search("机械制图")

        assert len(videos) == 1
        video = videos[0]
        assert video["title"] == "机械制图 教学视频"
        assert video["page_url"] == BILI_URL
        assert video["embed_url"] == "https://player.bilibili.com/player.html?bvid=BV1xx411c7mD"
        assert video["source_label"] == "B站"

    @pytest.mark.asyncio
    async def test_course_platform_has_no_embed(self, monkeypatch):
        _patch_sources(monkeypatch, bilibili=[], course=[_result(MOOC_URL, title="机械制图 国家精品课")])

        videos = await ExternalVideoService.search("机械制图")

        assert len(videos) == 1
        assert videos[0]["embed_url"] == ""
        assert videos[0]["source_label"] == "中国大学MOOC"

    @pytest.mark.asyncio
    async def test_non_whitelisted_domain_dropped(self, monkeypatch):
        """include 只是请求侧建议，博查可能仍返回名单外站点 —— 必须自己再筛一遍"""
        _patch_sources(monkeypatch, bilibili=[], embed=[_result(WEIBO_URL), _result(BILI_URL)])

        videos = await ExternalVideoService.search("机械制图")

        assert [v["page_url"] for v in videos] == [BILI_URL]

    @pytest.mark.asyncio
    async def test_bilibili_non_video_pages_dropped(self, monkeypatch):
        """B 站上只有 /video/BVxxx 是能播的单个视频页。

        真实抓包里 B 站结果绝大多数是图文专栏（read/）、付费课程（cheese/）、
        收藏夹（medialist/）和未支持的 AV 号 —— 都不能内嵌，混进"视频"列表是错的。
        """
        _patch_sources(monkeypatch, bilibili=[], embed=[
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
        _patch_sources(
            monkeypatch,
            bilibili=[],
            embed=[_result("https://m.bilibili.com/video/BV1P54y1S7xJ?from=search")],
        )

        video = (await ExternalVideoService.search("机械制图"))[0]

        assert video["page_url"] == "https://www.bilibili.com/video/BV1P54y1S7xJ"
        assert video["embed_url"] == "https://player.bilibili.com/player.html?bvid=BV1P54y1S7xJ"

    @pytest.mark.asyncio
    async def test_missing_fields_degrade_to_empty(self, monkeypatch):
        """博查不给作者 / 时长 / 播放量 / 封面，字段必须在但为空，下游才不会炸"""
        _patch_sources(monkeypatch, bilibili=[], embed=[_result(BILI_URL)])

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


# ═══════════════════════════════════════════════
#  search_node_videos
# ═══════════════════════════════════════════════

class _FakeNodeQuery:
    def __init__(self, node):
        self._node = node

    async def first(self):
        return self._node


class _FakePathNode:
    """替掉 PathNode.filter(...).first()"""

    def __init__(self, node):
        self.node = node
        self.filter_calls: list[dict] = []

    def filter(self, **kwargs):
        self.filter_calls.append(kwargs)
        return _FakeNodeQuery(self.node)


class _Node:
    def __init__(self, topic, tags):
        self.topic = topic
        self.knowledge_tags = tags


def _patch_node(monkeypatch, node):
    fake = _FakePathNode(node)
    monkeypatch.setattr("backend.src.models.path_model.PathNode", fake)
    return fake


class TestSearchNodeVideos:
    @pytest.mark.asyncio
    async def test_uses_node_tags_as_query(self, monkeypatch):
        """检索词取自节点的知识点标签，不是节点标题"""
        _patch_node(monkeypatch, _Node("上下文组装与Prompt注入设计", json.dumps(["检索上下文组装", "RAG提示词约束"])))
        bili, _ = _patch_sources(monkeypatch, bilibili=[_bili_video()])

        result = await search_node_videos(1, 2, max_results=3)

        assert bili.call_args_list[0].args[0] == "检索上下文组装 RAG提示词约束"
        assert result[0]["title"] == "B站视频"
        assert result[0]["view_count_text"] == "5.0万次"

    @pytest.mark.asyncio
    async def test_looks_up_node_within_path(self, monkeypatch):
        fake = _patch_node(monkeypatch, _Node("某主题", "[]"))
        _patch_sources(monkeypatch, bilibili=[_bili_video()])

        await search_node_videos(7, 9, max_results=3)

        assert fake.filter_calls == [{"id": 9, "path_id": 7}]

    @pytest.mark.asyncio
    async def test_missing_node_raises(self, monkeypatch):
        _patch_node(monkeypatch, None)
        _patch_sources(monkeypatch, bilibili=[])

        with pytest.raises(ServiceError):
            await search_node_videos(1, 2)

    @pytest.mark.asyncio
    async def test_tags_broken_json_falls_back_to_topic(self, monkeypatch):
        """标签列坏了也不能让整个接口失败"""
        _patch_node(monkeypatch, _Node("IVF倒排索引：聚类分桶", "{坏 JSON"))
        bili, _ = _patch_sources(monkeypatch, bilibili=[_bili_video()])

        await search_node_videos(1, 2)

        assert bili.call_args_list[0].args[0] == "IVF倒排索引 聚类分桶"


# ═══════════════════════════════════════════════
#  search_and_save（契约回归）
# ═══════════════════════════════════════════════

class TestSearchAndSaveContract:
    """上游 resource/service.py 与 tools/video_search.py 依赖这些字段名，改后端不能破坏它"""

    @pytest.mark.asyncio
    async def test_saved_shape(self, monkeypatch):
        _patch_sources(monkeypatch, bilibili=[_bili_video(title="机械制图基础")])

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
        assert saved[0]["duration_text"] == "12:34"
        assert saved[0]["view_count_text"] == "5.0万次"

    @pytest.mark.asyncio
    async def test_no_results_saves_nothing(self, monkeypatch):
        _patch_sources(monkeypatch, bilibili=[], embed=[], course=[])
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

    def test_minutes_over_sixty(self):
        """B 站把长视频写成 "217:17"（217 分钟），要能进位成 3:37:17"""
        assert _format_duration("217:17") == "3:37:17"

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
