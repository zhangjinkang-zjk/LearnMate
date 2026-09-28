"""教育来源白名单单元测试

测试目标：backend/src/utils/education_sources.py
覆盖范围：
- 域名匹配（含子域、www 前缀、大小写）
- label_for / tier_for / is_education_source
- include_domains 的形态
- 不该进白名单的站点（已停运的平台）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.utils.education_sources import (
    include_domains,
    is_education_source,
    label_for,
    tier_for,
)


class TestLabelFor:
    def test_direct_domain(self):
        assert label_for("https://www.icourse163.org/course/ZJU-1001") == "中国大学MOOC"

    def test_subdomain_matches(self):
        """space.bilibili.com 属于 B 站"""
        assert label_for("https://space.bilibili.com/12345") == "B站"

    def test_www_prefix_ignored(self):
        assert label_for("https://www.xuetangx.com/course/x") == "学堂在线"
        assert label_for("https://xuetangx.com/course/x") == "学堂在线"

    def test_uppercase_host(self):
        assert label_for("https://WWW.BILIBILI.COM/video/BV1xx411c7mD") == "B站"

    def test_outside_whitelist(self):
        assert label_for("https://weibo.com/1234/abcd") == ""

    def test_lookalike_domain_not_matched(self):
        """bilibili.com.evil.com 不是 B 站"""
        assert label_for("https://bilibili.com.evil.com/video/BV1xx411c7mD") == ""

    def test_open_163_does_not_match_plain_163(self):
        """只收了 open.163.com，不能把 www.163.com 也算进来"""
        assert label_for("https://www.163.com/news/article/xxx") == ""
        assert label_for("https://open.163.com/newview/movie/x") == "网易公开课"

    def test_empty_and_none(self):
        assert label_for("") == ""
        assert label_for(None) == ""

    def test_no_scheme_returns_empty(self):
        """没写协议的 URL 取不到 hostname，保守返回空串（不该崩）。

        博查返回的 url 永远是绝对地址，且视频链路在调用前已经挡掉了非 http(s) 的 URL，
        所以这里不需要为了容错去猜协议。
        """
        assert label_for("www.bilibili.com/video/BV1xx411c7mD") == ""


class TestTierFor:
    def test_embed_tier(self):
        assert tier_for("https://www.bilibili.com/video/BV1xx411c7mD") == "embed"

    def test_course_tier(self):
        assert tier_for("https://www.imooc.com/learn/1234") == "course"

    def test_reading_tier(self):
        assert tier_for("https://developer.mozilla.org/zh-CN/docs/Web/JavaScript") == "reading"

    def test_outside_whitelist(self):
        assert tier_for("https://weibo.com/x") == ""


class TestIsEducationSource:
    def test_inside(self):
        assert is_education_source("https://github.com/python/cpython") is True

    def test_outside(self):
        assert is_education_source("https://example.com/x") is False


class TestIncludeDomains:
    def test_comma_separated(self):
        value = include_domains()
        assert "," in value
        assert " " not in value

    def test_contains_expected_domains(self):
        domains = include_domains().split(",")
        for expected in ("bilibili.com", "smartedu.cn", "icourse163.org",
                         "xuetangx.com", "developer.mozilla.org"):
            assert expected in domains

    def test_within_api_limit(self):
        """博查 include 的域名数上限文档称 100（一说 20），保持安全余量"""
        assert len(include_domains().split(",")) <= 20

    def test_tencent_ke_classroom_excluded(self):
        """腾讯课堂已于 2024-10-01 停止运营，不能出现在白名单里"""
        assert "ke.qq.com" not in include_domains().split(",")
        assert label_for("https://ke.qq.com/course/123") == ""


class TestIncludeDomainsByTier:
    """分档查询：B 站必须单独查，否则名额会被十几个课程站点挤掉"""

    def test_default_returns_all(self):
        domains = include_domains().split(",")
        assert "bilibili.com" in domains
        assert "icourse163.org" in domains

    def test_embed_tier_only(self):
        assert include_domains("embed").split(",") == ["bilibili.com", "b23.tv"]

    def test_course_and_reading_tiers_exclude_bilibili(self):
        domains = include_domains("course", "reading").split(",")
        assert "bilibili.com" not in domains
        assert "b23.tv" not in domains
        assert "icourse163.org" in domains
        assert "developer.mozilla.org" in domains

    def test_unknown_tier_returns_empty(self):
        assert include_domains("does-not-exist") == ""
