# -*- coding: utf-8 -*-
"""网页抓取：正文提取，以及**它不能被模型当作 SSRF 的跳板**。

`read_web_page` 是交给模型的工具 —— URL 由**模型**填，不再由搜索引擎给。所以"只能抓
公网地址"这条闸是它的安全前提，不是加分项：少了它，一句 `http://169.254.169.254/`
就能让服务端去读自己的云元数据。

**重定向那一跳是重点。** 只检查入口然后放开跟转，等于没检查 —— 一跳就到内网。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.src.utils.web_page import (
    check_fetchable_url,
    clean_source_text,
    extract_visible_text,
    fetch_readable_text,
    landing_note,
    residual_markup_note,
    slice_article_markup,
    tidy_plain_text,
)

# 两个公网 IP 字面量。**用字面量而不是域名**：字面量走 getaddrinfo 不查 DNS，
# 这些测试才能在没有网络的机器上跑。93.184.216.x 是可路由的公网段。
PUBLIC_A = "http://93.184.216.34/docs"
PUBLIC_B = "https://93.184.216.35/docs/"


class _FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.encoding = "utf-8"

    @property
    def is_redirect(self):
        return 300 <= self.status_code < 400 and "location" in {k.lower() for k in self.headers}


def _page(paragraph: str, repeat: int = 60) -> bytes:
    """够长的正文（TEXT_MIN_CHARS 是 220，短了会被判成"需要动态渲染"）。

    **每段必须不一样。** `clean_source_text` 会把重复行并掉 —— 拿同一句重复 60 遍，
    并完只剩一行，反而短到被判成空页（这是实测踩出来的，不是推测）。
    """
    body = "".join("<p>%s 第 %d 段</p>" % (paragraph, i) for i in range(repeat))
    return ("<html><body><article>%s</article></body></html>" % body).encode("utf-8")


def _patch_http(monkeypatch, responses):
    """按调用顺序返回响应；返回 mock 出来的 client，用来断言"到底发没发请求"。"""
    client = MagicMock()
    client.get = AsyncMock(side_effect=list(responses))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=ctx))
    return client


# ═══════════════════════════════════════
#  闸：只抓公网
# ═══════════════════════════════════════

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:2221/learning/advanced/current",
        "http://localhost:2221/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
        "http://172.16.3.4/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
    ],
)
@pytest.mark.asyncio
async def test_internal_addresses_are_refused(url):
    allowed, reason = await check_fetchable_url(url)
    assert allowed is False, f"{url} 竟然被放行了 —— 模型可以拿它去探内网"
    assert reason


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://example.com/a.txt",
        "https://example.com/manual.pdf",
        "https://example.com/pack.zip",
        "not a url",
        "",
    ],
)
@pytest.mark.asyncio
async def test_non_page_urls_are_refused(url):
    allowed, _ = await check_fetchable_url(url)
    assert allowed is False


@pytest.mark.asyncio
async def test_a_public_address_is_allowed():
    allowed, reason = await check_fetchable_url(PUBLIC_A)
    assert allowed is True, reason


@pytest.mark.asyncio
async def test_a_refused_address_never_produces_a_request(monkeypatch):
    """闸要在**发请求之前**拦住。拦不住的话它就只是个提示。"""
    client = _patch_http(monkeypatch, [])
    text, note = await fetch_readable_text("http://127.0.0.1:2221/learning/advanced/current")
    assert text == ""
    assert note
    assert client.get.await_count == 0


@pytest.mark.asyncio
async def test_a_redirect_into_the_private_network_is_refused(monkeypatch):
    """只查首跳等于没查 —— 这个跳转必须被挡住。"""
    client = _patch_http(
        monkeypatch,
        [_FakeResponse(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})],
    )
    text, note = await fetch_readable_text(PUBLIC_A)
    assert text == ""
    assert "公网" in note
    # 只请求了首跳；内网那一跳根本没发出去
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_a_public_redirect_is_followed(monkeypatch):
    """跟是跟了，但**落点要说出来** —— 这里跳的是另一个主机（.34 → .35）。

    "落到了另一个站上"是这个仓库真踩过的坑：`docs.claude.com` 301 跳到
    `platform.claude.com`，那边整站返回一张「App unavailable in region」的封锁页，
    而链路上没有任何地方看得出抓到的不是原页。
    """
    client = _patch_http(
        monkeypatch,
        [
            _FakeResponse(301, headers={"location": PUBLIC_B}),
            _FakeResponse(200, content=_page("重定向之后的正文"), headers={"content-type": "text/html"}),
        ],
    )
    text, note = await fetch_readable_text(PUBLIC_A)
    assert "重定向之后的正文" in text
    assert PUBLIC_B in note
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_relative_redirects_are_resolved_before_the_check(monkeypatch):
    """相对跳转要先补成绝对地址，否则下一跳的检查是在查个空地址。"""
    client = _patch_http(
        monkeypatch,
        [
            _FakeResponse(302, headers={"location": "/docs/index.html"}),
            _FakeResponse(200, content=_page("相对跳转后的正文"), headers={"content-type": "text/html"}),
        ],
    )
    text, note = await fetch_readable_text(PUBLIC_A)
    assert note == ""
    assert client.get.await_count == 2
    assert client.get.await_args_list[1].args[0] == "http://93.184.216.34/docs/index.html"


@pytest.mark.asyncio
async def test_an_endless_redirect_chain_stops(monkeypatch):
    client = _patch_http(
        monkeypatch,
        [_FakeResponse(302, headers={"location": PUBLIC_B})] * 20,
    )
    text, note = await fetch_readable_text(PUBLIC_A)
    assert text == ""
    assert "重定向" in note
    assert client.get.await_count <= 8


@pytest.mark.asyncio
async def test_a_page_without_real_content_says_so_instead_of_pretending(monkeypatch):
    """读不到就报读不到 —— 这条链路上"假装读过"比"没读到"贵得多。"""
    _patch_http(
        monkeypatch,
        [_FakeResponse(200, content=b"<html><body><p>hi</p></body></html>",
                       headers={"content-type": "text/html"})],
    )
    text, note = await fetch_readable_text(PUBLIC_A)
    assert text == ""
    assert note


# ═══════════════════════════════════════
#  落在别的站上了吗
# ═══════════════════════════════════════

def test_a_move_to_another_host_is_reported():
    """**这条是拿真实故障写的。** `docs.claude.com/en/api/messages` 301 跳到
    `platform.claude.com/docs/en/api/messages`，那边整站是一张地区封锁页 ——
    抓取层照样报成功。落点必须说出来，否则学生拿到的是一张错误页而他不知道。
    """
    note = landing_note(
        "https://docs.claude.com/en/api/messages",
        "https://platform.claude.com/docs/en/api/messages",
    )

    assert note
    assert "platform.claude.com" in note


def test_a_same_host_path_rewrite_gets_no_note():
    """同主机改路径**不报**。

    文档站把 `/guide` 重写成 `/guide/introduction`、把 `/latest/` 换成 `/v3/` 都是
    日常操作，内容恰恰是对的。把它也报出来，结果是每份文档抬头都挂着一条警告 ——
    天天叫的警告等于没叫，真出事那次也没人看。
    """
    assert landing_note("https://vite.dev/guide", "https://vite.dev/guide/introduction") == ""


def test_an_https_upgrade_gets_no_note():
    assert landing_note("http://sbert.net/docs/", "https://sbert.net/docs/") == ""


def test_www_is_not_a_different_site():
    assert landing_note("https://www.gradio.app/docs", "https://gradio.app/docs") == ""


def test_staying_put_gets_no_note():
    url = "https://vuejs.org/guide/introduction.html"

    assert landing_note(url, url) == ""
    assert landing_note(url, "") == ""


@pytest.mark.asyncio
async def test_a_same_host_rewrite_does_not_reach_the_text(monkeypatch):
    """同主机跳完之后说明要是空的 —— 上面几条是纯函数，这条走完整条链。"""
    _patch_http(
        monkeypatch,
        [
            _FakeResponse(302, headers={"location": "/docs/index.html"}),
            _FakeResponse(200, content=_page("重写之后的正文"), headers={"content-type": "text/html"}),
        ],
    )
    text, note = await fetch_readable_text(PUBLIC_A)

    assert "重写之后的正文" in text
    assert note == ""


@pytest.mark.asyncio
async def test_a_cross_host_landing_also_shows_up_when_the_page_is_empty(monkeypatch):
    """抓空了**也要说落点**：跳到别的站之后只有一张壳子，多半是那个站没有这一页，
    而不是"这页需要动态渲染" —— 两种情况给学生的下一步不一样。"""
    _patch_http(
        monkeypatch,
        [
            _FakeResponse(301, headers={"location": PUBLIC_B}),
            _FakeResponse(200, content=b"<html><body><p>hi</p></body></html>",
                          headers={"content-type": "text/html"}),
        ],
    )
    text, note = await fetch_readable_text(PUBLIC_A)

    assert text == ""
    assert PUBLIC_B in note


# ═══════════════════════════════════════
#  markdown 原文：别拿 HTML 那套去处理它
# ═══════════════════════════════════════

_MD_BODY = (
    "# 集合\n\n"
    "> 一句话简介。\n\n"
    "```python\n"
    "def read_users():\n"
    "    return [\"Rick\", \"Morty\"]\n"
    "```\n\n"
    "export const Callout = () => <div className=\"my-6\">\n\n"
    + "\n".join(f"正文第 {i} 段，写够长度好过 TEXT_MIN_CHARS 那道门。" for i in range(20))
    + "\n"
)


def _md_response(body=_MD_BODY, content_type="text/markdown; charset=utf-8"):
    return _FakeResponse(200, content=body.encode("utf-8"), headers={"content-type": content_type})


@pytest.mark.asyncio
async def test_a_markdown_page_is_passed_through_as_is(monkeypatch):
    """**文档站的 `.md` 版本比渲染后的 HTML 干净得多**：没有侧边导航、没有壳子。

    但它有两个东西会被 HTML 那套处理坏：
      - 代码块里的缩进（Python 的四空格）；
      - 正文里的 HTML 片段/JSX（`export const Callout = () => <div>`）—— 那是内容，
        不是"没清干净的标记"，拿它去喂残留自检会在每份文件抬头挂一条假 ⚠️。
    """
    _patch_http(monkeypatch, [_md_response()])

    # 地址用公网字面量，不用域名 —— 同上（`PUBLIC_A` 那条）。SSRF 那道闸是**先**解析
    # 主机名再判公网，所以这个测试在被代理 fake-IP（DNS 把任何域名解到 198.18.0.0/15）
    # 的机器上会**卡在闸上**，正文根本走不到 markdown 那一段，报出来还是"正文为空"。
    # 这里要测的是 markdown 处理，闸本身有它自己的一组测试。
    text, note = await fetch_readable_text("http://93.184.216.34/guide/introduction.md")

    assert '    return ["Rick", "Morty"]' in text, "代码缩进被压掉了"
    assert 'export const Callout = () => <div className="my-6">' in text
    assert note == "", f"原样文本不该出残留标记的说明，实际是 {note!r}"


@pytest.mark.asyncio
async def test_markdown_is_recognised_by_its_suffix_when_the_header_lies(monkeypatch):
    """有的站把 `.md` 标成 `text/html` —— 内容类型和路径后缀，中一个就算。"""
    _patch_http(monkeypatch, [_md_response(content_type="text/html; charset=utf-8")])

    text, _ = await fetch_readable_text("https://93.184.216.35/guide/intro.md")

    assert '    return ["Rick", "Morty"]' in text


def test_plain_text_keeps_code_indentation_and_blank_lines():
    """`clean_source_text` 会把行内空白压成一个空格 —— 那是给 HTML 碎行用的，用在代码上就毁了。"""
    text = tidy_plain_text("def f():\n    if x:\n        return 1\n")

    assert "        return 1" in text


def test_plain_text_does_not_dedupe_lines():
    """按行去重对代码是错的：两行一样的 `return None` 是正常的。"""
    text = tidy_plain_text("def a():\n    return None\n\n\ndef b():\n    return None\n")

    assert text.count("return None") == 2


def test_plain_text_still_collapses_a_pile_of_blank_lines():
    assert tidy_plain_text("甲\n\n\n\n\n乙") == "甲\n\n乙"


def test_code_fence_metadata_is_stripped():
    """代码围栏后面挂的主题配置是人读不到的机器元数据，一个 langchain 页七十多处。"""
    raw = '```python Google theme={"theme":{"light":"catppuccin-latte","dark":"catppuccin-mocha"}}\nprint(1)\n```'

    text = tidy_plain_text(raw)

    assert text.startswith("```python Google\n")
    assert "catppuccin" not in text


def test_a_theme_blob_in_the_body_is_not_touched():
    """只在**围栏那一行**上动手 —— 正文里讲到 `theme={...}` 是内容。"""
    body = "配置长这样：theme={\"theme\":{\"light\":\"x\"}}，写在顶部。"

    assert body in tidy_plain_text(body)


# ═══════════════════════════════════════
#  正文提取
# ═══════════════════════════════════════

def test_scripts_and_styles_do_not_reach_the_text():
    markup = (
        "<html><head><style>p{color:red}</style><script>var a=1</script></head>"
        "<body><p>真的正文</p></body></html>"
    )
    text = extract_visible_text(markup)
    assert "真的正文" in text
    assert "color:red" not in text
    assert "var a=1" not in text


def test_inline_tags_do_not_break_the_line():
    """行内标签不许断行。

    以前每一段文字都被单独拼成一行，于是 `<p>你好 <b>世界</b></p>` 出来是两行 ——
    抓下来的正文会被**每一个** `<span>` `<b>` `<code>` 切成碎句。FastAPI 那几页的正文
    全是这么碎的（"Importing from" / 路径 / "as" / 包名 各占一行），学生读到的没法看。
    """
    text = extract_visible_text("<article><p>你好 <b>世界</b>，这是<code>一段</code>话。</p></article>")

    assert "你好 世界，这是一段话。" in text.replace("\n", "")


def test_inline_elements_separated_by_whitespace_keep_the_space():
    """`<b>甲</b> <b>乙</b>` 中间那个空格是一个纯空白文本节点 —— 丢掉会粘成「甲乙」。"""
    assert "甲 乙" in extract_visible_text("<p><b>甲</b> <b>乙</b></p>")


def test_block_tags_still_break_lines():
    text = extract_visible_text("<div><p>第一段</p><p>第二段</p></div>")

    assert [line for line in text.splitlines() if line.strip()] == ["第一段", "第二段"]


def test_pre_content_keeps_its_line_breaks():
    """终端输出和代码的换行**是内容**，压成一个空格就毁了。"""
    text = extract_visible_text("<pre>fastapi dev\nINFO  应用已启动\n</pre>")

    assert "fastapi dev" in text and "INFO" in text


def test_escaped_markup_does_not_show_up_as_text():
    """**这是学生在截图里看到的那一屏。**

    FastAPI 的文档为了显示彩色终端输出，把一段带内联样式的 HTML **转义后**放进 `<pre>`。
    `HTMLParser` 会把 `&lt;span&gt;` 解成 `<span>`，于是标签作为"正文"留下来了。
    """
    markup = (
        '<article><p>To run your app:</p><pre>'
        '&lt;span style="background-color:#007166"&gt;&lt;font color="#D3D7CF"&gt; '
        'FastAPI &lt;/font&gt;&lt;/span&gt; Starting development server'
        '</pre></article>'
    )
    text = extract_visible_text(markup)

    assert "<span" not in text and "<font" not in text
    assert "FastAPI" in text and "Starting development server" in text


def test_a_lone_tag_in_a_sentence_is_content_not_markup():
    """讲 HTML 的文档里，句子中间那个 `<div>` 是**内容**，删了就错了。

    所以只在"整行以标记为主"时才下手 —— 这是这层清理唯一容易做过火的地方。
    """
    assert "<div>" in extract_visible_text("<p>用 <code>&lt;div&gt;</code> 包起来就行。</p>")


def test_a_short_line_that_is_all_markup_is_still_stripped():
    """`<b>fastapi run</b>` 单独一行 —— 标签只占 7/18 字。

    按比例算刚好会漏掉（差 0.01），而那正是真页面上残留的那四个标签之一。
    所以"整行以标记开头"这种形态用更低的门槛：一两个标签就算。
    """
    assert "<b>" not in extract_visible_text("<pre>&lt;b&gt;fastapi run&lt;/b&gt;</pre>")


def test_a_prose_line_starting_with_a_tag_is_kept():
    """反过来那一面：一句话正好以标签开头，但后面全是正经内容，不能删。"""
    assert "<div>" in extract_visible_text("<p>&lt;div&gt; 是块级元素，用来分组。</p>")


def test_a_closed_tag_pair_mid_sentence_is_markup():
    """真页面上最后残留的那两个标签就是这个形状：`quit<b>)</b>`。

    **它是被 span 边界从中间切开的转义块**，所以既不以 `<` 开头（比例分支够不着），
    标签又只有两个（另一个比例分支也够不着）。只有"成对闭合"这条能收掉它 ——
    而正经内容里随手写的 `<div>`、泛型 `<T>` 从来不闭合，所以不误伤。
    """
    text = extract_visible_text("<p>Press CTRL+C to quit&lt;b&gt;)&lt;/b&gt;</p>")

    assert "<b>" not in text and "</b>" not in text
    assert "quit)" in text


def test_a_page_that_did_not_clean_up_says_so():
    """**这是"治本"里能做的那一半。**

    被转义、等着被 JS 渲染的标记，和"讲 HTML 的教程里当例子写的标记"，在静态 HTML 里
    是同一个字符串 —— 没有执行环境就判不出来。所以判据做不到 100%，退一步：
    **让"没抓干净"这件事说出来**，而不是让学生对着一屏 `<span>` 以为那就是文档原文。
    """
    dirty = "\n".join(f'<span style="background-color:#007166">第 {i} 行</span>' for i in range(30))
    note = residual_markup_note(f"{dirty}\n{'正文' * 200}")

    assert "标记" in note


def test_a_clean_page_gets_no_note():
    assert residual_markup_note("正文" * 500) == ""


def test_a_short_page_is_not_judged():
    """太短的东西（不足 200 字）多半还没抓到正文，按密度算会误报。"""
    assert residual_markup_note("<span>x</span>") == ""


def test_the_article_region_wins_over_the_page_chrome():
    markup = "<nav>首页 文档 博客</nav><article><p>正文在这里</p></article><footer>版权</footer>"
    sliced = slice_article_markup(markup)
    assert "正文在这里" in sliced
    assert "首页 文档 博客" not in sliced


def test_a_page_without_any_article_marker_is_returned_whole():
    """找不到标记就全给 —— 宁可多带导航，也不能把正文切没了。"""
    markup = "<html><body><p>没有 article 标签的一页</p></body></html>"
    assert slice_article_markup(markup) == markup


def test_the_main_region_wins_over_the_navigation_before_it():
    """**现代文档站压在正文前面的那道侧边导航，就靠这一条切掉。**

    实测（2026-10-02）：langchain / mcp / chroma / vue 的每一页，正文前面都压着
    34~114 行目录树的链接文字。它们全在 `<main>` 之前，而 `<main>` 之内就是正文 ——
    量过被切掉的那一段，长行只有站名和一条横幅广告，尾部两版完全一致（正文没丢）。
    """
    markup = "<div><nav>首页</nav><a>Guide</a><a>API</a></div><main><p>正文在这里</p></main>"

    sliced = slice_article_markup(markup)

    assert "正文在这里" in sliced
    assert "首页" not in sliced


def test_the_earlier_markers_still_win_over_main():
    """`<main>` 排在标记表**最后一条**，所以它只加不减。

    中文博客那几条和 `<article` 都排在它前面 —— 一个页面同时有两者的地方，行为
    必须和加这条之前一模一样。
    """
    markup = '<body><main><p>页面框架</p></main><div id="cnblogs_post_body">正文</div></body>'

    sliced = slice_article_markup(markup)

    assert "正文" in sliced
    assert "页面框架" not in sliced


def test_navigation_noise_lines_are_dropped_and_duplicates_collapse():
    text = clean_source_text("登录\n注册\n这一段才是内容\n这一段才是内容\n返回顶部")
    assert "登录" not in text
    assert "返回顶部" not in text
    assert text.count("这一段才是内容") == 1


# ═══════════════════════════════════════
#  工具层
# ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_the_tool_tells_the_model_not_to_guess_when_it_cannot_read(monkeypatch):
    """工具读不到时，返回里必须**明说不许凭记忆补**。"""
    from backend.src.ai_core.tools.search import read_web_page

    _patch_http(monkeypatch, [])
    answer = await read_web_page.ainvoke({"url": "http://127.0.0.1:2221/x"})
    assert "不要凭记忆" in answer
    assert "127.0.0.1" in answer


@pytest.mark.asyncio
async def test_the_tool_returns_the_body_and_the_address_it_read(monkeypatch):
    """回答时要能说清内容是哪来的，所以正文里必须带着地址。"""
    from backend.src.ai_core.tools.search import read_web_page

    _patch_http(
        monkeypatch,
        [_FakeResponse(200, content=_page("官方文档的正文"), headers={"content-type": "text/html"})],
    )
    answer = await read_web_page.ainvoke({"url": PUBLIC_A})
    assert "官方文档的正文" in answer
    assert PUBLIC_A in answer
