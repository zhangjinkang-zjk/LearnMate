# -*- coding: utf-8 -*-
"""框架文档登记表：表本身的形状、认框架、落盘文件名，以及抓取编排。

**这些断言守的是"登记表不许悄悄写错"**：一条 URL 打错域名、少写一个 `sources`、
标题里带着 Windows 不认的字符，症状全都是"学生那边少了一页 / 多了个怪文件名"，
而没有任何报错。所以在这里钉形状，不靠人去记。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.service.advanced import reference_docs
from backend.src.utils.framework_docs import (
    FRAMEWORKS,
    catalogue,
    folder_for_url,
    get_framework,
    match_frameworks,
    matches_domain,
    safe_filename,
)


@pytest.fixture(autouse=True)
def _no_fetch_cache(monkeypatch):
    """把抓取缓存关掉，让这个文件里的测试保持自洽。

    **这些测试会往真 Redis 里写，而缓存一上，它们就不再是自洽的了**：前一个测试抓到的
    假正文被后一个测试命中，于是后一个测试自己那个假抓取根本没被调用（`calls == []`），
    断言全错 —— 而且单跑和整跑结果不一样，换个顺序又不一样。2026-10-02 加缓存时就是这么
    挂掉三条的（那七条假正文还真的进了 Redis，真学生请求会读到它们）。

    缓存本身在 `test_reference_docs_cache.py` 里专门测，那边用内存字典替掉 Redis。
    """
    async def _miss(_key):
        return None

    async def _drop(_key, _value, _ttl):
        return None

    monkeypatch.setattr(reference_docs, "cache_get", _miss)
    monkeypatch.setattr(reference_docs, "cache_set", _drop)


# ═══════════════════════════════════════
#  登记表的形状
# ═══════════════════════════════════════

def test_every_framework_is_fully_filled_in():
    assert FRAMEWORKS, "登记表不能是空的"
    for item in FRAMEWORKS:
        assert item["id"] and item["id"] == item["id"].lower(), item
        assert item["name"], item
        assert item["aliases"], f"{item['id']} 没有别名，学生写了名字也认不出来"
        assert item["domains"], item
        assert item["sources"], f"{item['id']} 一页都没有"


def test_every_source_is_https_and_on_its_own_official_domain():
    """**这条是防手滑的主力。** 把一篇博客地址粘进"官方入口页"，学生是看不出来的 ——
    它会长得和官方文档一样可信，只是内容可能是旧版本的。
    """
    for item in FRAMEWORKS:
        for source in item["sources"]:
            url = source["url"]
            assert source["label"], source
            assert url.startswith("https://"), url
            host = url.split("/")[2]
            assert any(
                host == domain or host.endswith("." + domain) for domain in item["domains"]
            ), f"{item['id']} 的 {url} 不在它自己的官方域名里"


def test_framework_ids_are_unique():
    ids = [item["id"] for item in FRAMEWORKS]
    assert len(ids) == len(set(ids))


def test_the_catalogue_does_not_leak_urls():
    """前端只需要标识 —— 把 URL 铺出去，等于让它有机会自己拼一个来请求。"""
    for item in catalogue():
        assert set(item) == {"id", "name", "source_count"}


# ═══════════════════════════════════════
#  认框架 / 认域名
# ═══════════════════════════════════════

def test_it_recognises_a_framework_from_free_text():
    """给学生自己写的那份选型记录用 —— 它里面怎么写的都得认出来。"""
    text = "技术栈定了：后端用 FastAPI，编排用 LangChain，数据库先 SQLite。"
    found = {item["id"] for item in match_frameworks(text)}
    assert found == {"fastapi", "langchain"}


def test_it_finds_nothing_in_unrelated_text():
    assert match_frameworks("今天想学的是三视图和正投影") == []
    assert match_frameworks("") == []


def test_framework_lookup_is_case_insensitive():
    assert get_framework("FastAPI")["id"] == "fastapi"
    assert get_framework(" langchain ")["id"] == "langchain"
    assert get_framework("django") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://fastapi.tiangolo.com/tutorial/first-steps/",
        "http://docs.langchain.com/oss/python/langchain/agents",
        "https://python.langchain.com/llms.txt",
    ],
)
def test_official_domains_are_recognised(url):
    assert matches_domain(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://fastapi.tiangolo.com.evil.example/x",   # 后缀伪造
        "https://blog.example.com/fastapi-tutorial",
        "not a url",
        "",
    ],
)
def test_lookalike_domains_are_not(url):
    assert matches_domain(url) is False


# ═══════════════════════════════════════
#  给教练自己找的地址起目录名
# ═══════════════════════════════════════

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://vuejs.org/guide/quick-start.html", "vuejs.org"),
        ("https://www.gradio.app/docs", "gradio.app"),
        ("https://docs.trychroma.com/", "trychroma.com"),
        # `docs.com` 这种整个名字就是"docs"的，不能被削成空
        ("https://docs.com/x", "docs.com"),
        ("https://docs.python.org/3/", "python.org"),
    ],
)
def test_the_folder_name_comes_from_the_domain(url, expected):
    """**取域名，不猜产品名。** 我们只知道它落在哪个站上；把 `vuejs.org/...` 写成
    `Vue/` 是编的，而这个文件夹学生会当成资料的一部分看到。"""
    assert folder_for_url(url) == expected


@pytest.mark.parametrize("url", ["not a url", "", None])
def test_a_url_without_a_domain_yields_nothing(url):
    """取不出来就返回空 —— 由调用方兜底成 `网页文档`，而不是让它拼出一条
    `docs/框架文档//1-x.md` 那种路径。"""
    assert folder_for_url(url) == ""


# ═══════════════════════════════════════
#  落盘文件名
# ═══════════════════════════════════════

@pytest.mark.parametrize(
    "raw",
    [
        "起步：第一个应用",          # 全角冒号没问题，但不能带半角
        'a/b\\c:d*e?f"g<h>i|j',
        "  前后空白  ",
        "结尾有句点。",
    ],
)
def test_filenames_never_carry_windows_illegal_characters(raw):
    name = safe_filename(raw)
    assert not set(name) & set('\\/:*?"<>|'), name
    assert name.strip() == name
    assert name


def test_an_unusable_title_falls_back_instead_of_becoming_an_empty_name():
    """空名字会写出一个叫 `.md` 的文件 —— 学生根本不知道那是什么。"""
    assert safe_filename("", fallback="doc") == "doc"
    assert safe_filename("///", fallback="doc") == "doc"
    assert safe_filename("   ", fallback="doc") == "doc"


def test_a_long_title_is_truncated():
    assert len(safe_filename("标题" * 200)) <= 60


# ═══════════════════════════════════════
#  抓取编排
# ═══════════════════════════════════════

def _fake_fetch(monkeypatch, result_for):
    """按 URL 决定抓取结果：`result_for(url) -> (text, note)`。"""
    calls: list[str] = []

    async def fake(url):
        calls.append(url)
        return result_for(url)

    monkeypatch.setattr(reference_docs, "fetch_readable_text", fake)
    return calls


@pytest.mark.asyncio
async def test_it_produces_one_file_per_source_in_numbered_order(monkeypatch):
    _fake_fetch(monkeypatch, lambda url: (f"正文：{url}", ""))
    result = await reference_docs.collect(["fastapi"])

    fastapi = get_framework("fastapi")
    assert len(result["files"]) == len(fastapi["sources"])
    assert [f["path"] for f in result["files"]] == [
        "FastAPI/1-起步：第一个应用.md",
        "FastAPI/2-多文件项目的目录结构.md",
        "FastAPI/3-命令行工具 fastapi dev.md",
    ]
    assert result["failures"] == []
    assert result["frameworks"] == [{"id": "fastapi", "name": "FastAPI"}]


@pytest.mark.asyncio
async def test_a_page_that_cannot_be_fetched_is_reported_not_silently_dropped(monkeypatch):
    """文档站改版是常态。**少给一页必须说出来** —— 静默少给，学生会以为自己看到的就这些。"""
    fastapi = get_framework("fastapi")
    broken = fastapi["sources"][1]["url"]
    _fake_fetch(monkeypatch, lambda url: ("", "来源网页返回 HTTP 404") if url == broken else ("正文", ""))

    result = await reference_docs.collect(["fastapi"])

    assert len(result["files"]) == len(fastapi["sources"]) - 1
    assert len(result["failures"]) == 1
    failure = result["failures"][0]
    assert failure["url"] == broken
    assert failure["framework"] == "FastAPI"
    assert "404" in failure["reason"]


@pytest.mark.asyncio
async def test_an_exception_from_the_fetcher_becomes_a_failure_too(monkeypatch):
    """抓取器自己会兜异常；万一没兜住，也不能把整次请求带崩。"""

    async def boom(url):
        raise RuntimeError("炸了")

    monkeypatch.setattr(reference_docs, "fetch_readable_text", boom)
    result = await reference_docs.collect(["fastapi"])

    assert result["files"] == []
    assert len(result["failures"]) == len(get_framework("fastapi")["sources"])
    assert all("RuntimeError" in item["reason"] for item in result["failures"])


@pytest.mark.asyncio
async def test_an_unknown_framework_name_is_reported_and_never_fetched(monkeypatch):
    calls = _fake_fetch(monkeypatch, lambda url: ("正文", ""))
    result = await reference_docs.collect(["fastapi", "django"])

    assert result["unknown"] == ["django"]
    assert result["frameworks"] == [{"id": "fastapi", "name": "FastAPI"}]
    # 认不出的名字不该换来任何一次出网
    assert all("fastapi" in url for url in calls)


@pytest.mark.asyncio
async def test_nothing_requested_means_nothing_fetched(monkeypatch):
    calls = _fake_fetch(monkeypatch, lambda url: ("正文", ""))
    result = await reference_docs.collect([])

    assert calls == []
    assert result == {"frameworks": [], "unknown": [], "files": [], "failures": []}


@pytest.mark.asyncio
async def test_a_repeated_framework_is_only_fetched_once(monkeypatch):
    calls = _fake_fetch(monkeypatch, lambda url: ("正文", ""))
    await reference_docs.collect(["fastapi", "fastapi", "FastAPI"])
    assert len(calls) == len(get_framework("fastapi")["sources"])


@pytest.mark.asyncio
async def test_the_number_of_fetches_is_capped(monkeypatch):
    """请求体是客户端给的。没有这个上限，一句 `["fastapi"] * 8` 就是二十多次出网。"""
    calls = _fake_fetch(monkeypatch, lambda url: ("正文", ""))
    await reference_docs.collect([item["id"] for item in FRAMEWORKS] * 4)
    assert len(calls) <= reference_docs.MAX_DOCS_PER_REQUEST
